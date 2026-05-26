"""Slit-scan processor: spatial-temporal scan through the video volume.

Three sub-modes:
- Planar cut (3D): diagonal plane cut for V/H modes — slit sweeps from one
  edge of the mask to the other across all frames, creating a true planar
  cut through the video cube that can be visualised in 3D.
- Vertical / Horizontal sweep: slit extraction with linearly varying position
  across a user-defined rectangular mask region (fit-to-frame or all-frames).
- Oblique: 2D plane cut through (x, y, t) space defined by 4 control points.
"""

import os

import numpy as np
from PIL import Image

from processing.base_processor import BaseProcessor


def _bilinear_sample_strip(frame, xs, ys):
    """Vectorised bilinear sampling for a strip of coordinates."""
    h, w = frame.shape[:2]
    xs = np.clip(xs, 0, w - 1.001)
    ys = np.clip(ys, 0, h - 1.001)
    x0 = np.floor(xs).astype(np.intp)
    y0 = np.floor(ys).astype(np.intp)
    x1 = np.minimum(x0 + 1, w - 1)
    y1 = np.minimum(y0 + 1, h - 1)
    dx = (xs - x0).astype(np.float32)[:, None]
    dy = (ys - y0).astype(np.float32)[:, None]
    val = (
        frame[y0, x0].astype(np.float32) * (1 - dx) * (1 - dy)
        + frame[y0, x1].astype(np.float32) * dx * (1 - dy)
        + frame[y1, x0].astype(np.float32) * (1 - dx) * dy
        + frame[y1, x1].astype(np.float32) * dx * dy
    )
    return val.astype(np.uint8)


class SlitscanProcessor(BaseProcessor):
    """Extracts a spatial-temporal scan from video frames."""

    def run(self):
        try:
            s = self._state
            mask_type = s.slitscan_mask_type
            sampling_mode = s.slitscan_sampling_mode

            if mask_type == "Oblique":
                self._run_oblique_scan(s)
            elif sampling_mode == "Planar cut (3D)":
                self._run_planar_cut(s)
            elif mask_type in ("Vertical", "Horizontal"):
                self._run_slit_scan(s)
            else:
                self.error.emit(f"Unknown mask type: {mask_type}")
        except Exception as e:
            self.error.emit(str(e))

    # ── Planar cut (diagonal sweep through cube) ──────────────────

    def _run_planar_cut(self, s):
        """Extract a diagonal plane from the video cube.

        The slit sweeps linearly from one edge of the mask to the other
        across all sampled frames, creating a true diagonal planar cut
        through the video volume.  The result can be displayed in 3D.

        Vertical: slit sweeps horizontally (L→R or R→L) across frames → YT plane.
        Horizontal: slit sweeps vertically (T→B or B→T) across frames → XT plane.
        """
        video_src = s.video_source
        fw, fh = video_src.width, video_src.height

        mask_type = s.slitscan_mask_type
        slit_w = max(1, s.slitscan_slit_width)
        scan_dir = s.slitscan_scan_direction
        reverse_time = s.slitscan_reverse_time
        is_vertical = mask_type == "Vertical"

        # Mask region insets
        bl = s.slitscan_border_left
        br = s.slitscan_border_right
        bt = s.slitscan_border_top
        bb = s.slitscan_border_bottom
        mask_x1 = max(0, bl)
        mask_x2 = max(0, fw - br)
        mask_y1 = max(0, bt)
        mask_y2 = max(0, fh - bb)
        mask_w = max(1, mask_x2 - mask_x1)
        mask_h = max(1, mask_y2 - mask_y1)

        initial = s.initial_frame
        last = s.last_frame
        sampling = s.sampling_rate
        num_frames = max(1, (last - initial) // sampling + 1)

        # Resolve scan direction — slit sweeps from start to end
        if is_vertical:
            left_to_right = (scan_dir == "L→R")
            start_pos = mask_x1 if left_to_right else (mask_x2 - slit_w)
            end_pos = (mask_x2 - slit_w) if left_to_right else mask_x1
        else:
            top_to_bottom = (scan_dir == "T→B")
            start_pos = mask_y1 if top_to_bottom else (mask_y2 - slit_w)
            end_pos = (mask_y2 - slit_w) if top_to_bottom else mask_y1

        # Clamp
        if is_vertical:
            max_p = mask_x2 - slit_w
            start_pos = max(mask_x1, min(start_pos, max_p))
            end_pos = max(mask_x1, min(end_pos, max_p))
        else:
            max_p = mask_y2 - slit_w
            start_pos = max(mask_y1, min(start_pos, max_p))
            end_pos = max(mask_y1, min(end_pos, max_p))

        num_cols = num_frames  # always use all frames for planar cut

        if is_vertical:
            out_w = num_cols * slit_w
            out_h = mask_h
        else:
            out_w = mask_w
            out_h = num_cols * slit_w

        # Compute frame indices
        frame_indices = []
        for col in range(num_cols):
            t_frac = col / max(1, num_cols - 1) if num_cols > 1 else 0.0
            f_idx = initial + int(round(t_frac * (num_frames - 1))) * sampling
            f_idx = min(f_idx, last)
            frame_indices.append(f_idx)
        if reverse_time:
            frame_indices.reverse()

        # Slit position per column: linear sweep from start to end
        positions = []
        for col in range(num_cols):
            t_frac = col / max(1, num_cols - 1) if num_cols > 1 else 0.0
            pos = start_pos + t_frac * (end_pos - start_pos)
            positions.append(int(round(pos)))

        # Pre-allocate output
        total_pixels = out_w * out_h
        use_memmap = total_pixels > 200_000_000
        out_path_tmp = None
        if use_memmap:
            import tempfile
            tmp = tempfile.NamedTemporaryFile(suffix=".dat", delete=False)
            out_path_tmp = tmp.name
            tmp.close()
            output = np.memmap(out_path_tmp, dtype=np.uint8, mode="w+",
                               shape=(out_h, out_w, 3))
        else:
            output = np.zeros((out_h, out_w, 3), dtype=np.uint8)

        count = 0
        for col, f_idx in enumerate(frame_indices):
            if self.is_cancelled():
                self.cancelled.emit()
                self._cleanup(output, use_memmap, out_path_tmp)
                return

            fd = video_src.get_frame(f_idx)
            if fd is None:
                continue
            pos = positions[col]

            if is_vertical:
                strip = fd[mask_y1:mask_y2, pos:pos + slit_w, :]
                if strip.size > 0:
                    output[:, col * slit_w:(col + 1) * slit_w, :] = strip
            else:
                strip = fd[pos:pos + slit_w, mask_x1:mask_x2, :]
                if strip.size > 0:
                    output[col * slit_w:(col + 1) * slit_w, :, :] = strip

            count += 1
            self.progress.emit(count, num_cols)

        if count == 0:
            self.error.emit("No frames were processed.")
            self._cleanup(output, use_memmap, out_path_tmp)
            return

        # Save
        fmt = s.image_format
        ext = "tiff" if fmt == "tiff" else "png"
        fname = f"slitscan_{mask_type.lower()}_planar.{ext}"
        out_path = os.path.join(self._output_dir, fname)
        img = Image.fromarray(output)
        if fmt == "tiff":
            img.save(out_path, compression="tiff_lzw")
        else:
            img.save(out_path)

        self._cleanup(output, use_memmap, out_path_tmp)

        self.finished.emit({
            "output_dir": self._output_dir,
            "image_path": out_path,
            "width": out_w,
            "height": out_h,
            "frames_processed": count,
            "mask_type": mask_type,
            "sampling_mode": "Planar cut (3D)",
            "scan_direction": scan_dir,
            "frame_width": fw,
            "frame_height": fh,
            "mask_left": bl, "mask_right": br,
            "mask_top": bt, "mask_bottom": bb,
        })

    # ── Vertical / Horizontal slit scan (sweep) ────────────────────

    def _run_slit_scan(self, s):
        video_src = s.video_source
        fw, fh = video_src.width, video_src.height

        mask_type = s.slitscan_mask_type
        slit_w = max(1, s.slitscan_slit_width)
        scan_dir = s.slitscan_scan_direction
        reverse_time = s.slitscan_reverse_time
        sampling_mode = s.slitscan_sampling_mode
        is_vertical = mask_type == "Vertical"

        # Mask region insets
        l = s.slitscan_border_left
        r = s.slitscan_border_right
        t = s.slitscan_border_top
        b = s.slitscan_border_bottom
        mask_x1 = max(0, l)
        mask_x2 = max(0, fw - r)
        mask_y1 = max(0, t)
        mask_y2 = max(0, fh - b)
        mask_w = max(1, mask_x2 - mask_x1)
        mask_h = max(1, mask_y2 - mask_y1)

        initial = s.initial_frame
        last = s.last_frame
        sampling = s.sampling_rate
        num_frames = max(1, (last - initial) // sampling + 1)

        # Resolve scan direction
        if is_vertical:
            left_to_right = (scan_dir == "L→R")
            axis_size = mask_w
            start_x = mask_x1 if left_to_right else mask_x2 - slit_w
            end_x = (mask_x2 - slit_w) if left_to_right else mask_x1
        else:
            top_to_bottom = (scan_dir == "T→B")
            axis_size = mask_h
            start_y = mask_y1 if top_to_bottom else mask_y2 - slit_w
            end_y = (mask_y2 - slit_w) if top_to_bottom else mask_y1

        # Clamp
        if is_vertical:
            max_p = mask_x2 - slit_w
            start_x = max(mask_x1, min(start_x, max_p))
            end_x = max(mask_x1, min(end_x, max_p))
            displacement = end_x - start_x
        else:
            max_p = mask_y2 - slit_w
            start_y = max(mask_y1, min(start_y, max_p))
            end_y = max(mask_y1, min(end_y, max_p))
            displacement = end_y - start_y

        # Determine number of output columns
        if sampling_mode == "Fit to frame size":
            available = abs(displacement)
            max_cols = max(1, available // max(1, slit_w) + 1)
            num_cols = min(num_frames, max_cols)
        else:
            num_cols = num_frames

        if is_vertical:
            out_w = num_cols * slit_w
            out_h = mask_h
            pos_start = start_x
            pos_end = end_x
        else:
            out_w = mask_w
            out_h = num_cols * slit_w
            pos_start = start_y
            pos_end = end_y

        # Pre-compute frame position for each output column
        frame_indices = []
        for col in range(num_cols):
            t_frac = col / max(1, num_cols - 1) if num_cols > 1 else 0.0
            f_idx = initial + int(round(t_frac * (num_frames - 1))) * sampling
            f_idx = min(f_idx, last)
            frame_indices.append(f_idx)

        if reverse_time:
            frame_indices.reverse()

        # Slit position per column: linear interpolation from start to end
        positions = []
        for col in range(num_cols):
            t_frac = col / max(1, num_cols - 1) if num_cols > 1 else 0.0
            pos = pos_start + t_frac * (pos_end - pos_start)
            positions.append(int(round(pos)))

        # Pre-allocate output
        total_pixels = out_w * out_h
        use_memmap = total_pixels > 200_000_000
        out_path_tmp = None
        if use_memmap:
            import tempfile
            tmp = tempfile.NamedTemporaryFile(suffix=".dat", delete=False)
            out_path_tmp = tmp.name
            tmp.close()
            output = np.memmap(out_path_tmp, dtype=np.uint8, mode="w+",
                               shape=(out_h, out_w, 3))
        else:
            output = np.zeros((out_h, out_w, 3), dtype=np.uint8)

        # Fast path: decode frames sequentially, minimal caching
        count = 0
        for col, f_idx in enumerate(frame_indices):
            if self.is_cancelled():
                self.cancelled.emit()
                self._cleanup(output, use_memmap, out_path_tmp)
                return

            fd = video_src.get_frame(f_idx)
            if fd is None:
                continue
            pos = positions[col]

            if is_vertical:
                strip = fd[mask_y1:mask_y2, pos:pos + slit_w, :]
                if strip.size > 0:
                    output[:, col * slit_w:(col + 1) * slit_w, :] = strip
            else:
                strip = fd[pos:pos + slit_w, mask_x1:mask_x2, :]
                if strip.size > 0:
                    output[col * slit_w:(col + 1) * slit_w, :, :] = strip

            count += 1
            self.progress.emit(count, num_cols)

        if count == 0:
            self.error.emit("No frames were processed.")
            self._cleanup(output, use_memmap, out_path_tmp)
            return

        # Anti-alias edge blend at seams when slit_w > 1
        if slit_w > 1 and count > 1:
            for c in range(1, count):
                seam = c * slit_w
                if is_vertical:
                    axis_max = out_w
                else:
                    axis_max = out_h
                if seam >= axis_max:
                    continue
                for px in range(min(2, slit_w)):
                    left_hi = seam - 1 - px
                    right_lo = seam + px
                    if left_hi >= 0 and right_lo < axis_max:
                        if is_vertical:
                            blend = ((output[:, right_lo, :].astype(np.float32) * 0.5
                                      + output[:, left_hi, :].astype(np.float32) * 0.5)
                                     .astype(np.uint8))
                            output[:, right_lo, :] = blend
                        else:
                            blend = ((output[right_lo, :, :].astype(np.float32) * 0.5
                                      + output[left_hi, :, :].astype(np.float32) * 0.5)
                                     .astype(np.uint8))
                            output[right_lo, :, :] = blend

        # Save
        fmt = s.image_format
        ext = "tiff" if fmt == "tiff" else "png"
        fname = f"slitscan_{mask_type.lower()}.{ext}"
        out_path = os.path.join(self._output_dir, fname)
        img = Image.fromarray(output)
        if fmt == "tiff":
            img.save(out_path, compression="tiff_lzw")
        else:
            img.save(out_path)

        self._cleanup(output, use_memmap, out_path_tmp)

        self.finished.emit({
            "output_dir": self._output_dir,
            "image_path": out_path,
            "width": out_w,
            "height": out_h,
            "frames_processed": count,
            "mask_type": mask_type,
            "sampling_mode": sampling_mode,
            "frame_width": fw,
            "frame_height": fh,
            "mask_left": l, "mask_right": r,
            "mask_top": t, "mask_bottom": b,
        })

    def _cleanup(self, output, use_memmap, out_path_tmp):
        if use_memmap and out_path_tmp:
            try:
                del output
            except Exception:
                pass
            try:
                os.unlink(out_path_tmp)
            except OSError:
                pass

    # ── Oblique plane cut scan ─────────────────────────────────────

    def _run_oblique_scan(self, s):
        """Vectorised oblique plane cut through (x, y, t) space.

        Uses bilinear spatial interpolation and linear temporal interpolation
        to sample the video volume at arbitrary 3D positions defined by
        4 control points.
        """
        video_src = s.video_source
        fw, fh = video_src.width, video_src.height

        points = s.slitscan_oblique_points
        if len(points) < 4:
            self.error.emit(
                "Oblique mode requires 4 control points. "
                "Define them using the 3D mask selector."
            )
            return

        initial = s.initial_frame
        last = s.last_frame
        total_frames = max(1, (last - initial) // s.sampling_rate + 1)

        P00 = np.array(points[0], dtype=np.float64)
        P10 = np.array(points[1], dtype=np.float64)
        P11 = np.array(points[2], dtype=np.float64)
        P01 = np.array(points[3], dtype=np.float64)

        out_w = s.slitscan_oblique_output_w
        out_h = s.slitscan_oblique_output_h
        if out_w <= 0 or out_h <= 0:
            # Auto-compute from point extents
            all_x = [p[0] for p in points]
            all_y = [p[1] for p in points]
            all_t = [p[2] for p in points]
            dx = max(all_x) - min(all_x)
            dy = max(all_y) - min(all_y)
            dt = max(all_t) - min(all_t)
            # Use the two largest extents as width/height
            extents = sorted([dx, dy, dt], reverse=True)
            out_w = max(256, int(extents[0]) + 1)
            out_h = max(256, int(extents[1]) + 1)

        output = np.zeros((out_h, out_w, 3), dtype=np.uint8)

        # Build parameter grid for bilinear quad interpolation
        u_arr = np.linspace(0, 1, out_w, dtype=np.float64)
        v_arr = np.linspace(0, 1, out_h, dtype=np.float64)
        U, V = np.meshgrid(u_arr, v_arr)

        # Bilinear interpolation of the 4 corner points
        X = (1 - U) * (1 - V) * P00[0] + U * (1 - V) * P10[0] + U * V * P11[0] + (1 - U) * V * P01[0]
        Y = (1 - U) * (1 - V) * P00[1] + U * (1 - V) * P10[1] + U * V * P11[1] + (1 - U) * V * P01[1]
        T = (1 - U) * (1 - V) * P00[2] + U * (1 - V) * P10[2] + U * V * P11[2] + (1 - U) * V * P01[2]

        X = np.clip(X, 0, fw - 1).astype(np.float32)
        Y = np.clip(Y, 0, fh - 1).astype(np.float32)
        T = np.clip(T, initial, last).astype(np.float64)

        # Process row-by-row in batches, grouping pixels by frame index
        # for efficient frame caching and vectorised spatial sampling.
        batch_rows = max(1, min(64, out_h))
        frame_cache = {}
        max_cache = 60

        for row_start in range(0, out_h, batch_rows):
            if self.is_cancelled():
                self.cancelled.emit()
                return
            row_end = min(row_start + batch_rows, out_h)

            batch_X = X[row_start:row_end, :].ravel()
            batch_Y = Y[row_start:row_end, :].ravel()
            batch_T = T[row_start:row_end, :].ravel()

            # Floor and ceil frame indices
            t_floor = np.floor(batch_T).astype(np.int64)
            t_ceil = np.minimum(t_floor + 1, last)
            t_frac = (batch_T - t_floor).astype(np.float32)

            # Get unique frame indices needed for this batch
            unique_frames = np.unique(np.concatenate([t_floor, t_ceil]))

            # Load needed frames into cache
            for fi in unique_frames:
                fi_int = int(fi)
                if fi_int not in frame_cache:
                    fd = video_src.get_frame(fi_int)
                    if fd is not None:
                        frame_cache[fi_int] = fd
                    # Evict oldest if cache too large
                    if len(frame_cache) > max_cache:
                        oldest = min(frame_cache.keys())
                        del frame_cache[oldest]

            # Vectorised bilinear spatial sampling
            n_pixels = len(batch_X)
            result_pixels = np.zeros((n_pixels, 3), dtype=np.float32)

            # Spatial interpolation coordinates
            x0 = np.floor(batch_X).astype(np.intp)
            y0 = np.floor(batch_Y).astype(np.intp)
            x1 = np.minimum(x0 + 1, fw - 1)
            y1 = np.minimum(y0 + 1, fh - 1)
            dx = (batch_X - x0).astype(np.float32)
            dy = (batch_Y - y0).astype(np.float32)

            # Sample from floor frames
            for fi in np.unique(t_floor):
                fi_int = int(fi)
                frame = frame_cache.get(fi_int)
                if frame is None:
                    continue
                mask = t_floor == fi
                idx = np.where(mask)[0]
                if len(idx) == 0:
                    continue

                lx0 = x0[idx]
                ly0 = y0[idx]
                lx1 = x1[idx]
                ly1 = y1[idx]
                ldx = dx[idx, None]
                ldy = dy[idx, None]

                val = (
                    frame[ly0, lx0].astype(np.float32) * (1 - ldx) * (1 - ldy)
                    + frame[ly0, lx1].astype(np.float32) * ldx * (1 - ldy)
                    + frame[ly1, lx0].astype(np.float32) * (1 - ldx) * ldy
                    + frame[ly1, lx1].astype(np.float32) * ldx * ldy
                )

                frac = t_frac[idx]
                # Where frac is ~0 or floor==ceil, just use this frame
                no_interp = (frac < 0.001) | (t_floor[idx] == t_ceil[idx])
                result_pixels[idx[no_interp]] = val[no_interp]

                # Where temporal interpolation is needed, store floor contribution
                interp_mask = ~no_interp
                if np.any(interp_mask):
                    interp_idx = idx[interp_mask]
                    result_pixels[interp_idx] = val[interp_mask] * (1 - frac[interp_mask, None])

            # Sample from ceil frames (only where temporal interpolation needed)
            needs_interp = (t_frac >= 0.001) & (t_floor != t_ceil)
            for fi in np.unique(t_ceil[needs_interp]):
                fi_int = int(fi)
                frame = frame_cache.get(fi_int)
                if frame is None:
                    continue
                mask = (t_ceil == fi) & needs_interp
                idx = np.where(mask)[0]
                if len(idx) == 0:
                    continue

                lx0 = x0[idx]
                ly0 = y0[idx]
                lx1 = x1[idx]
                ly1 = y1[idx]
                ldx = dx[idx, None]
                ldy = dy[idx, None]

                val = (
                    frame[ly0, lx0].astype(np.float32) * (1 - ldx) * (1 - ldy)
                    + frame[ly0, lx1].astype(np.float32) * ldx * (1 - ldy)
                    + frame[ly1, lx0].astype(np.float32) * (1 - ldx) * ldy
                    + frame[ly1, lx1].astype(np.float32) * ldx * ldy
                )

                frac = t_frac[idx]
                result_pixels[idx] += val * frac[:, None]

            # Write batch to output
            batch_h = row_end - row_start
            output[row_start:row_end, :, :] = np.clip(
                result_pixels.reshape(batch_h, out_w, 3), 0, 255
            ).astype(np.uint8)

            self.progress.emit(row_end, out_h)

        # Save output image
        fmt = s.image_format
        ext = "tiff" if fmt == "tiff" else "png"
        out_path = os.path.join(self._output_dir, f"slitscan_oblique.{ext}")
        img = Image.fromarray(output)
        if fmt == "tiff":
            img.save(out_path, compression="tiff_lzw")
        else:
            img.save(out_path)

        self.finished.emit({
            "output_dir": self._output_dir,
            "image_path": out_path,
            "width": out_w,
            "height": out_h,
            "frames_processed": total_frames,
            "mask_type": "Oblique",
            "sampling_mode": "Oblique",
            "oblique_points": [tuple(p) for p in points],
            "frame_width": fw,
            "frame_height": fh,
        })
