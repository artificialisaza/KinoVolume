"""Rings processor: creates a dendrochronology-style ring visualization.

Each video frame maps to a concentric ring at increasing radius.
Center = first frame's center pixel, outermost ring = last frame.

Rendering uses an inverse-mapping approach: every output pixel is mapped
back through polar coordinates to find which frame (ring) and which
source position it corresponds to.  This avoids scatter-then-fill
artifacts and scales to very large output sizes without memory issues.

Phase 1 collects per-frame colour strips, which are then resampled to a
uniform angular resolution and stacked into a 2-D look-up table (LUT).
Phase 2 renders the output image by indexing straight into this LUT with
pure vectorised numpy — no Python loops — so even very large images
render quickly.
"""

import os

import numpy as np
from PIL import Image

from config import RINGS_MAX_OUTPUT_DIAMETER
from processing.base_processor import BaseProcessor


def _bilinear_sample_array(frame, xs, ys):
    """Vectorised bilinear sampling for arrays of sub-pixel coordinates.

    Args:
        frame: (H, W, C) uint8
        xs, ys: 1-D float arrays (already clamped to [0, W-1] / [0, H-1]).

    Returns:
        (N, C) uint8 array of sampled colours.
    """
    h, w = frame.shape[:2]
    x0 = np.floor(xs).astype(np.intp)
    y0 = np.floor(ys).astype(np.intp)
    x1 = np.minimum(x0 + 1, w - 1)
    y1 = np.minimum(y0 + 1, h - 1)
    np.clip(x0, 0, w - 1, out=x0)
    np.clip(y0, 0, h - 1, out=y0)

    dx = (xs - x0).astype(np.float32)[:, None]
    dy = (ys - y0).astype(np.float32)[:, None]

    val = (
        frame[y0, x0].astype(np.float32) * (1 - dx) * (1 - dy)
        + frame[y0, x1].astype(np.float32) * dx * (1 - dy)
        + frame[y1, x0].astype(np.float32) * (1 - dx) * dy
        + frame[y1, x1].astype(np.float32) * dx * dy
    )
    return val.astype(np.uint8)


class RingsProcessor(BaseProcessor):
    """Builds a 2D ring image from video frames."""

    # Fixed angular resolution for the resampled LUT.
    _ANGULAR_RES = 4096

    def run(self):
        try:
            s = self._state
            vs = s.video_source
            fw, fh = vs.width, vs.height

            cx = s.rings_center_x
            cy = s.rings_center_y
            sampling_mode = s.rings_sampling_mode
            reverse_time = getattr(s, "rings_reverse_time", False)

            initial = s.initial_frame
            last = s.last_frame
            sampling = s.sampling_rate
            num_frames = max(1, (last - initial) // sampling + 1)

            # Max radius limited by distance from center to nearest edge
            max_radius = min(cx, cy, fw - cx, fh - cy)
            max_radius = max(1, max_radius)

            is_equal_area = sampling_mode == "Equal-area"

            # Determine ring count and output size
            if sampling_mode == "Fit to frame size":
                num_rings = min(num_frames, max_radius)
            else:
                max_diam = getattr(s, "rings_max_output", RINGS_MAX_OUTPUT_DIAMETER)
                num_rings = num_frames
                diameter = num_rings * 2
                if diameter > max_diam:
                    num_rings = max_diam // 2

            diameter = num_rings * 2
            out_center = float(num_rings)
            R = float(num_rings)

            # Pre-calculate which frames to use
            if num_rings >= num_frames:
                frame_indices = None
            else:
                frame_indices = set()
                for i in range(num_rings):
                    idx = int(i * (num_frames - 1) / max(1, num_rings - 1))
                    frame_indices.add(idx)

            # ----------------------------------------------------------
            # Phase 1: collect one perimeter colour strip per ring
            # ----------------------------------------------------------
            ANG = self._ANGULAR_RES
            ring_strips = []
            ring_idx = 0
            count = 0
            total = num_rings

            frame_count_idx = 0
            for _, frame_data in vs.get_frame_range(initial, last, sampling):
                if self.is_cancelled():
                    self.cancelled.emit()
                    return

                if frame_indices is not None and frame_count_idx not in frame_indices:
                    frame_count_idx += 1
                    continue

                if ring_idx >= num_rings:
                    break

                i = ring_idx
                src_r = i * max_radius / num_rings if num_rings > 0 else 0.0

                if i == 0:
                    px = _bilinear_sample_array(
                        frame_data,
                        np.array([float(cx)]),
                        np.array([float(cy)]),
                    )
                    # Broadcast single pixel to full angular resolution
                    ring_strips.append(np.broadcast_to(px, (ANG, 3)).copy())
                else:
                    # Sample at uniform angular resolution
                    thetas = np.linspace(0, 2 * np.pi, ANG, endpoint=False)
                    src_x = np.clip(cx + src_r * np.cos(thetas), 0, fw - 1)
                    src_y = np.clip(cy + src_r * np.sin(thetas), 0, fh - 1)
                    pixels = _bilinear_sample_array(frame_data, src_x, src_y)
                    ring_strips.append(pixels)  # (ANG, 3)

                ring_idx += 1
                count += 1
                frame_count_idx += 1
                self.progress.emit(count, total)

            if count == 0:
                self.error.emit("No frames were processed.")
                return

            actual_rings = len(ring_strips)

            # Reverse ring order if requested (center ← last frame)
            if reverse_time:
                ring_strips.reverse()

            # Stack into a single LUT: (num_rings, ANG, 3) uint8
            lut = np.stack(ring_strips, axis=0)  # (actual_rings, ANG, 3)

            # ----------------------------------------------------------
            # Phase 2: render via pure vectorised LUT lookup
            # ----------------------------------------------------------
            output = np.zeros((diameter, diameter, 4), dtype=np.uint8)

            BATCH = max(1, min(512, diameter))
            for y_start in range(0, diameter, BATCH):
                if self.is_cancelled():
                    self.cancelled.emit()
                    return

                y_end = min(y_start + BATCH, diameter)
                batch_h = y_end - y_start

                yy = np.arange(y_start, y_end, dtype=np.float32)
                xx = np.arange(diameter, dtype=np.float32)
                gy, gx = np.meshgrid(yy, xx, indexing="ij")

                dy = gy - out_center
                dx = gx - out_center
                dist = np.sqrt(dx * dx + dy * dy)
                angle = np.arctan2(dy, dx)
                # Map angle to [0, 1) keeping the same orientation as the
                # source frame.  Using `(angle + pi)` shifts the result by
                # half the LUT, flipping the output 180°; instead use a
                # simple positive modulo so source-right (theta=0) maps to
                # output-right.
                angle_norm = (angle / (2 * np.pi)) % 1.0  # [0, 1)

                inside = dist < R
                if not np.any(inside):
                    continue

                flat_dist = dist[inside]
                flat_angle = angle_norm[inside]

                # Map output radius → ring index (float)
                if is_equal_area:
                    ring_f = np.clip(
                        actual_rings * (flat_dist / R) ** 2,
                        0, actual_rings - 1,
                    )
                else:
                    ring_f = np.clip(flat_dist, 0, actual_rings - 1)

                # Map angle → angular index (float)
                ang_f = flat_angle * ANG  # [0, ANG)

                # Bilinear interpolation indices for ring and angle axes
                r0 = np.floor(ring_f).astype(np.intp)
                r1 = np.minimum(r0 + 1, actual_rings - 1)
                rf = (ring_f - r0).astype(np.float32)

                a0 = np.floor(ang_f).astype(np.intp) % ANG
                a1 = (a0 + 1) % ANG
                af = (ang_f - np.floor(ang_f)).astype(np.float32)

                # Four-corner LUT lookup (vectorised, no Python loop)
                c00 = lut[r0, a0].astype(np.float32)  # (N, 3)
                c01 = lut[r0, a1].astype(np.float32)
                c10 = lut[r1, a0].astype(np.float32)
                c11 = lut[r1, a1].astype(np.float32)

                # Bilinear blend
                rf2 = rf[:, None]
                af2 = af[:, None]
                blended = (
                    c00 * (1 - rf2) * (1 - af2)
                    + c01 * (1 - rf2) * af2
                    + c10 * rf2 * (1 - af2)
                    + c11 * rf2 * af2
                )

                # Anti-alias outer edge
                alpha = np.full(len(flat_dist), 255.0, dtype=np.float32)
                edge_zone = flat_dist > (R - 1)
                alpha[edge_zone] = np.clip(
                    (R - flat_dist[edge_zone]) * 255, 0, 255,
                )

                batch_out = np.zeros((batch_h, diameter, 4), dtype=np.uint8)
                rgba = np.empty((len(flat_dist), 4), dtype=np.uint8)
                rgba[:, :3] = np.clip(blended, 0, 255).astype(np.uint8)
                rgba[:, 3] = alpha.astype(np.uint8)
                batch_out[inside] = rgba
                output[y_start:y_end] = batch_out

            # Save output
            fmt = s.image_format
            ext = "tiff" if fmt == "tiff" else "png"
            out_path = os.path.join(self._output_dir, f"rings.{ext}")
            img = Image.fromarray(output, "RGBA")
            if fmt == "tiff":
                img.save(out_path, compression="tiff_lzw")
            else:
                img.save(out_path)

            self.finished.emit({
                "output_dir": self._output_dir,
                "image_path": out_path,
                "width": diameter,
                "height": diameter,
                "frames_processed": count,
            })

        except Exception as e:
            self.error.emit(str(e))
