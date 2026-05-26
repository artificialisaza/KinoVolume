import os
import tempfile

import numpy as np
from PIL import Image

from processing.base_processor import BaseProcessor


class SliceProcessor(BaseProcessor):
    """Extracts a thin strip from each frame and concatenates into a 2D image.

    Uses memory-mapped arrays so that even very large videos do not
    overwhelm RAM.  When orthogonal mode is enabled, generates two
    perpendicular slices: one vertical, one horizontal.
    """

    def run(self):
        try:
            s = self._state
            vs = s.video_source

            initial = s.initial_frame
            last = s.last_frame
            sampling = s.sampling_rate
            total = max(1, (last - initial) // sampling + 1)

            fmt = s.image_format
            ext = "tiff" if fmt == "tiff" else "png"

            if getattr(s, "orthogonal_enabled", False):
                self._run_orthogonal(s, vs, initial, last, sampling, total, fmt, ext)
            else:
                self._run_single(s, vs, initial, last, sampling, total, fmt, ext)

        except Exception as e:
            self.error.emit(str(e))

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _save_image(arr, path, fmt):
        """Save a numpy array (or memmap) to an image file."""
        img = Image.fromarray(arr)
        if fmt == "tiff":
            img.save(path, compression="tiff_lzw")
        else:
            img.save(path)

    # ------------------------------------------------------------------

    def _run_single(self, s, vs, initial, last, sampling, total, fmt, ext):
        """Standard single-slit scan using a memory-mapped output array."""
        orientation = s.slit_orientation
        pos = s.slit_position
        width = s.slit_width
        reverse_time = getattr(s, "slice_reverse_time", False)
        fh, fw = vs.height, vs.width
        channels = 3

        # Pre-compute output dimensions
        if orientation == "Vertical":
            out_h = fh
            out_w = total * width
        else:
            out_h = total * width
            out_w = fw

        # Create a temporary memory-mapped file for the result
        tmp_fd, tmp_path = tempfile.mkstemp(
            dir=self._output_dir, suffix=".dat"
        )
        os.close(tmp_fd)

        try:
            result = np.memmap(
                tmp_path, dtype=np.uint8, mode="w+",
                shape=(out_h, out_w, channels),
            )

            count = 0
            for frame_idx, frame in vs.get_frame_range(initial, last, sampling):
                if self.is_cancelled():
                    del result
                    os.remove(tmp_path)
                    self.cancelled.emit()
                    return

                # Reverse-time: write each slit from the opposite end of the output.
                write_idx = (total - 1 - count) if reverse_time else count

                if orientation == "Vertical":
                    slit = frame[:, pos : pos + width, :]
                    result[:, write_idx * width : (write_idx + 1) * width, :] = slit
                else:
                    slit = frame[pos : pos + width, :, :]
                    result[write_idx * width : (write_idx + 1) * width, :, :] = slit

                count += 1
                self.progress.emit(count, total)

            if count == 0:
                del result
                os.remove(tmp_path)
                self.error.emit("No frames were processed.")
                return

            # Trim in case fewer frames were decoded than expected.
            # In reverse-time mode the populated slits live at the END of the
            # output (high indices), so trim from the front instead.
            if count < total:
                if reverse_time:
                    start = (total - count) * width
                    if orientation == "Vertical":
                        final = np.array(result[:, start:, :])
                    else:
                        final = np.array(result[start:, :, :])
                else:
                    if orientation == "Vertical":
                        final = np.array(result[:, : count * width, :])
                    else:
                        final = np.array(result[: count * width, :, :])
            else:
                final = result

            out_path = os.path.join(self._output_dir, f"slice.{ext}")
            self._save_image(final, out_path, fmt)

            finished_h = final.shape[0]
            finished_w = final.shape[1]
            del result
            os.remove(tmp_path)

            self.finished.emit({
                "output_dir": self._output_dir,
                "image_path": out_path,
                "width": finished_w,
                "height": finished_h,
                "frames_processed": count,
            })
        except Exception:
            # Ensure cleanup on unexpected errors
            try:
                del result
            except Exception:
                pass
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
            raise

    def _run_orthogonal(self, s, vs, initial, last, sampling, total, fmt, ext):
        """Generate two perpendicular slices plus optional display frames.

        Uses memory-mapped arrays so large frame ranges stay within RAM limits.
        """
        v_pos = s.slit_position      # vertical slit X position
        v_width = s.slit_width
        h_pos = s.ortho_position     # horizontal slit Y position
        h_width = getattr(s, "ortho_width", 1)
        reverse_time = getattr(s, "slice_reverse_time", False)
        fh, fw = vs.height, vs.width
        channels = 3

        # Pre-compute output dimensions
        v_out_h = fh
        v_out_w = total * v_width
        h_out_h = total * h_width
        h_out_w = fw

        # Create temporary memory-mapped files
        tmp_v_fd, tmp_v_path = tempfile.mkstemp(dir=self._output_dir, suffix=".dat")
        os.close(tmp_v_fd)
        tmp_h_fd, tmp_h_path = tempfile.mkstemp(dir=self._output_dir, suffix=".dat")
        os.close(tmp_h_fd)

        try:
            v_result = np.memmap(
                tmp_v_path, dtype=np.uint8, mode="w+",
                shape=(v_out_h, v_out_w, channels),
            )
            h_result = np.memmap(
                tmp_h_path, dtype=np.uint8, mode="w+",
                shape=(h_out_h, h_out_w, channels),
            )

            count = 0

            # Collect display frame indices
            display_frame_indices = set()
            df_mode = getattr(s, "display_frames_mode", "Central frame")
            if df_mode == "Central frame":
                display_frame_indices.add((initial + last) // 2)
            elif df_mode == "Every N frames":
                n = max(1, getattr(s, "display_frames_n", 100))
                # Step through sampled frames (not raw video frames)
                display_frame_indices = set(range(initial, last + 1, n * sampling))
            elif df_mode == "N frames total":
                n = max(1, getattr(s, "display_frames_n", 10))
                # Distribute N frames evenly across the sampled range
                sampled_count = max(1, (last - initial) // sampling + 1)
                if n >= sampled_count:
                    display_frame_indices = set(range(initial, last + 1, sampling))
                else:
                    step = max(1, (sampled_count - 1) / max(1, n - 1))
                    for i in range(n):
                        idx = initial + round(i * step) * sampling
                        idx = min(idx, last)
                        display_frame_indices.add(idx)
            elif df_mode == "Specific frames":
                for part in getattr(s, "display_frames_list", "").split(","):
                    part = part.strip()
                    if part.isdigit():
                        idx = int(part)
                        if initial <= idx <= last:
                            display_frame_indices.add(idx)

            # Create display_frames subfolder
            display_frames_dir = os.path.join(self._output_dir, "display_frames")
            if display_frame_indices:
                os.makedirs(display_frames_dir, exist_ok=True)

            saved_display_frames = {}

            for frame_idx, frame in vs.get_frame_range(initial, last, sampling):
                if self.is_cancelled():
                    del v_result, h_result
                    os.remove(tmp_v_path)
                    os.remove(tmp_h_path)
                    self.cancelled.emit()
                    return

                # Reverse-time: write each slit from the opposite end of the output.
                v_write = (total - 1 - count) if reverse_time else count
                h_write = (total - 1 - count) if reverse_time else count

                # Vertical slit → write directly into memmap
                v_result[:, v_write * v_width : (v_write + 1) * v_width, :] = \
                    frame[:, v_pos : v_pos + v_width, :]

                # Horizontal slit → write directly into memmap
                h_result[h_write * h_width : (h_write + 1) * h_width, :, :] = \
                    frame[h_pos : h_pos + h_width, :, :]

                # Save display frame if requested
                if frame_idx in display_frame_indices:
                    df_path = os.path.join(
                        display_frames_dir, f"frame_{frame_idx:06d}.{ext}"
                    )
                    self._save_image(frame, df_path, fmt)
                    saved_display_frames[frame_idx] = df_path

                count += 1
                self.progress.emit(count, total)

            if count == 0:
                del v_result, h_result
                os.remove(tmp_v_path)
                os.remove(tmp_h_path)
                self.error.emit("No frames were processed.")
                return

            # Seek and save any display frames that weren't hit by the sampling loop
            for df_idx in display_frame_indices - saved_display_frames.keys():
                df_frame = vs.get_frame(df_idx)
                if df_frame is not None:
                    df_path = os.path.join(
                        display_frames_dir, f"frame_{df_idx:06d}.{ext}"
                    )
                    self._save_image(df_frame, df_path, fmt)
                    saved_display_frames[df_idx] = df_path

            # Trim if fewer frames were decoded than expected
            if count < total:
                if reverse_time:
                    v_start = (total - count) * v_width
                    h_start = (total - count) * h_width
                    v_final = np.array(v_result[:, v_start:, :])
                    h_final = np.array(h_result[h_start:, :, :])
                else:
                    v_final = np.array(v_result[:, : count * v_width, :])
                    h_final = np.array(h_result[: count * h_width, :, :])
            else:
                v_final = v_result
                h_final = h_result

            v_path = os.path.join(self._output_dir, f"slice_vertical.{ext}")
            self._save_image(v_final, v_path, fmt)
            h_path = os.path.join(self._output_dir, f"slice_horizontal.{ext}")
            self._save_image(h_final, h_path, fmt)

            v_shape = (v_final.shape[0], v_final.shape[1])
            h_shape = (h_final.shape[0], h_final.shape[1])

            del v_result, h_result
            os.remove(tmp_v_path)
            os.remove(tmp_h_path)

            self.finished.emit({
                "output_dir": self._output_dir,
                "orthogonal": True,
                "vertical_path": v_path,
                "horizontal_path": h_path,
                "vertical_dims": {"width": v_shape[1], "height": v_shape[0]},
                "horizontal_dims": {"width": h_shape[1], "height": h_shape[0]},
                "slit_position": v_pos,
                "ortho_position": h_pos,
                "frame_width": vs.width,
                "frame_height": vs.height,
                "initial_frame": initial,
                "last_frame": last,
                "sampling_rate": sampling,
                "frames_processed": count,
                "display_frames": saved_display_frames,
            })
        except Exception:
            # Ensure cleanup on unexpected errors
            try:
                del v_result
            except Exception:
                pass
            try:
                del h_result
            except Exception:
                pass
            for p in (tmp_v_path, tmp_h_path):
                if os.path.exists(p):
                    os.remove(p)
            raise
