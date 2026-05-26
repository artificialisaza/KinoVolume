"""Slit-tear processor: samples pixels along user-drawn lines through time.

For each sampled frame the processor extracts the pixels that lie under
the rasterised drawn paths, assembles them into a vertical strip, and
writes the strip to disk.  After all frames are processed the strips
are assembled into a single 2D image (height = total sampled pixels,
width = number of frames).

Disk-based pipeline — individual strips are saved as .npy files so that
memory usage stays bounded regardless of frame count.
"""

import os
import shutil

import numpy as np
from PIL import Image

from processing.base_processor import BaseProcessor
from ui.widgets.drawing_canvas import DrawingCanvas


class SlitTearProcessor(BaseProcessor):
    """Extracts pixel strips along drawn lines across all sampled frames."""

    def run(self):
        try:
            s = self._state
            vs = s.video_source
            fw, fh = vs.width, vs.height

            lines = s.slittear_lines  # list of polylines [(x,y), ...]
            line_width = getattr(s, "slittear_line_width", 1)

            if not lines:
                self.error.emit("No lines drawn. Draw at least one line on the frame.")
                return

            # Rasterize all lines to ordered pixel coordinates
            rasterized = []
            for line_points in lines:
                pixels = DrawingCanvas.rasterize_polyline(line_points)
                if pixels:
                    rasterized.append(pixels)

            if not rasterized:
                self.error.emit("No valid pixels in drawn lines.")
                return

            # Expand pixels with line_width (perpendicular band)
            expanded = []
            for pixels in rasterized:
                if line_width <= 1:
                    expanded.append(pixels)
                else:
                    expanded.append(self._expand_band(pixels, line_width, fw, fh))

            # Build the full coordinate list with separators
            all_coords = []       # (x, y) or None for separator
            line_pixel_counts = []  # expanded pixel count per line

            for i, pixels in enumerate(expanded):
                if i > 0:
                    all_coords.append(None)  # gray separator row
                for px, py in pixels:
                    px = max(0, min(px, fw - 1))
                    py = max(0, min(py, fh - 1))
                    all_coords.append((px, py))
                line_pixel_counts.append(len(pixels))

            total_height = len(all_coords)

            # Pre-build vectorised lookup arrays for fast per-frame extraction
            # Separate pixel coords from separator positions
            pixel_rows = []       # indices into the strip that are real pixels
            pixel_xs = []
            pixel_ys = []
            sep_rows = []         # indices that are separator rows
            for idx, coord in enumerate(all_coords):
                if coord is None:
                    sep_rows.append(idx)
                else:
                    pixel_rows.append(idx)
                    pixel_xs.append(coord[0])
                    pixel_ys.append(coord[1])
            pixel_rows = np.array(pixel_rows, dtype=np.intp)
            pixel_xs = np.array(pixel_xs, dtype=np.intp)
            pixel_ys = np.array(pixel_ys, dtype=np.intp)
            sep_rows_arr = np.array(sep_rows, dtype=np.intp)

            initial = s.initial_frame
            last = s.last_frame
            sampling = s.sampling_rate
            total_frames = max(1, (last - initial) // sampling + 1)

            # Disk-based strip storage
            strips_dir = os.path.join(self._output_dir, "_strips_tmp")
            os.makedirs(strips_dir, exist_ok=True)

            count = 0
            for frame_idx, frame in vs.get_frame_range(initial, last, sampling):
                if self.is_cancelled():
                    self.cancelled.emit()
                    return

                # Vectorised extraction — no Python per-pixel loop
                strip = np.zeros((total_height, 3), dtype=np.uint8)
                strip[pixel_rows] = frame[pixel_ys, pixel_xs]
                if len(sep_rows_arr):
                    strip[sep_rows_arr] = 128  # separator gray

                np.save(
                    os.path.join(strips_dir, f"s_{count:06d}.npy"),
                    strip,
                )
                count += 1
                self.progress.emit(count, total_frames)

            if count == 0:
                self.error.emit("No frames were processed.")
                return

            # Assemble final image from saved strips
            result = np.zeros((total_height, count, 3), dtype=np.uint8)
            for i in range(count):
                result[:, i] = np.load(
                    os.path.join(strips_dir, f"s_{i:06d}.npy")
                )

            # Save 2D image
            fmt = s.image_format
            ext = "tiff" if fmt == "tiff" else "png"
            out_path = os.path.join(self._output_dir, f"slittear.{ext}")
            img = Image.fromarray(result)
            if fmt == "tiff":
                img.save(out_path, compression="tiff_lzw")
            else:
                img.save(out_path)

            # Clean up temp strips
            shutil.rmtree(strips_dir, ignore_errors=True)

            self.finished.emit({
                "output_dir": self._output_dir,
                "image_path": out_path,
                "width": count,
                "height": total_height,
                "frames_processed": count,
                "frame_width": fw,
                "frame_height": fh,
                "line_pixel_counts": line_pixel_counts,
                "rasterized_lines": [list(px) for px in rasterized],
            })

        except Exception as e:
            self.error.emit(str(e))

    # ── helpers ───────────────────────────────────────────────────

    @staticmethod
    def _expand_band(pixels, width, fw, fh):
        """Expand each path pixel into a perpendicular band of *width* pixels.

        For each pixel, the local tangent is estimated from its neighbours
        and the perpendicular direction is used to sample *width* pixels
        centred on the path.  Out-of-bounds samples are clamped.
        """
        n = len(pixels)
        if n == 0:
            return pixels

        half = width // 2
        expanded = []

        for i in range(n):
            # Tangent from neighbours
            if i == 0:
                dx = pixels[1][0] - pixels[0][0]
                dy = pixels[1][1] - pixels[0][1]
            elif i == n - 1:
                dx = pixels[-1][0] - pixels[-2][0]
                dy = pixels[-1][1] - pixels[-2][1]
            else:
                dx = pixels[i + 1][0] - pixels[i - 1][0]
                dy = pixels[i + 1][1] - pixels[i - 1][1]

            # Perpendicular (rotate tangent 90°)
            length = max(1, (dx * dx + dy * dy) ** 0.5)
            perp_x = -dy / length
            perp_y = dx / length

            px, py = pixels[i]
            for offset in range(-half, half + 1):
                sx = max(0, min(int(round(px + perp_x * offset)), fw - 1))
                sy = max(0, min(int(round(py + perp_y * offset)), fh - 1))
                expanded.append((sx, sy))

        return expanded
