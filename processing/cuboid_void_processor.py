import os

import numpy as np
from PIL import Image

from processing.base_processor import BaseProcessor


class CuboidVoidProcessor(BaseProcessor):
    """Extracts edge pixels from each frame to build 6 cuboid face textures."""

    def run(self):
        try:
            s = self._state
            vs = s.video_source
            fw, fh = vs.width, vs.height
            l, r = s.cuboid_border_left, s.cuboid_border_right
            t, b = s.cuboid_border_top, s.cuboid_border_bottom
            mask_w = fw - l - r
            mask_h = fh - t - b

            if mask_w < 2 or mask_h < 2:
                self.error.emit("Mask area is too small (need at least 2×2 px).")
                return

            initial = s.initial_frame
            last = s.last_frame
            sampling = s.sampling_rate
            total = max(1, (last - initial) // sampling + 1)

            # Pre-allocate edge arrays instead of appending to lists
            top_img = np.zeros((total, mask_w, 3), dtype=np.uint8)
            bottom_img = np.zeros((total, mask_w, 3), dtype=np.uint8)
            left_cols = np.zeros((total, mask_h, 3), dtype=np.uint8)
            right_cols = np.zeros((total, mask_h, 3), dtype=np.uint8)
            front = None
            back = None
            count = 0

            for frame_idx, frame in vs.get_frame_range(initial, last, sampling):
                if self.is_cancelled():
                    self.cancelled.emit()
                    return

                masked = frame[t : fh - b, l : fw - r, :]

                top_img[count] = masked[0, :, :]
                bottom_img[count] = masked[-1, :, :]
                left_cols[count] = masked[:, 0, :]
                right_cols[count] = masked[:, -1, :]

                if front is None:
                    front = masked.copy()
                # Keep reference to last masked region for back face
                back = masked

                count += 1
                self.progress.emit(count, total)

            if count == 0:
                self.error.emit("No frames were processed.")
                return

            # Copy back face from the last frame's data (it may be overwritten)
            back = back.copy()

            # Trim if fewer frames than expected
            if count < total:
                top_img = top_img[:count]
                bottom_img = bottom_img[:count]
                left_cols = left_cols[:count]
                right_cols = right_cols[:count]

            # Left/Right: transpose (num_frames, mask_h, 3) → (mask_h, num_frames, 3)
            left_img = np.transpose(left_cols, (1, 0, 2))
            right_img = np.transpose(right_cols, (1, 0, 2))

            faces = {
                "front": front,
                "back": back,
                "top": top_img,
                "bottom": bottom_img,
                "left": left_img,
                "right": right_img,
            }

            # Save face textures
            fmt = s.image_format
            ext = "tiff" if fmt == "tiff" else "png"
            face_paths = {}

            for name, data in faces.items():
                out_path = os.path.join(self._output_dir, f"{name}.{ext}")
                img = Image.fromarray(data)
                if fmt == "tiff":
                    img.save(out_path, compression="tiff_lzw")
                else:
                    img.save(out_path)
                face_paths[name] = out_path

            self.finished.emit({
                "output_dir": self._output_dir,
                "face_paths": face_paths,
                "dimensions": {
                    "width": mask_w,
                    "height": mask_h,
                    "depth": count,
                },
                "frames_processed": count,
            })

        except Exception as e:
            self.error.emit(str(e))
