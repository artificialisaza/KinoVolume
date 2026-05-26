"""Cuboid Fill processor: captures ALL pixels within the mask per frame.

Each sampled frame's masked area is saved as a numbered image to disk.
Unlike void mode, face textures (TBLRFK) are NOT generated — only the
per-frame images are needed for the filled cuboid 3D visualisation.
Supports three extraction modes for foreground isolation:
  - Chroma Key: color-based transparency
  - Edge Detect: Canny edge detection + contour filling
  - AI Segment: U²-Net neural network segmentation
"""

import os

import numpy as np
from PIL import Image

from processing.base_processor import BaseProcessor
from processing.chroma_processor import apply_chroma_key
from processing.object_detector import extract_mask, apply_extraction_mask


class CuboidFillProcessor(BaseProcessor):
    """Saves full masked frames as individual images for filled cuboid."""

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

            # Create frames subdirectory for full frame images
            frames_dir = os.path.join(self._output_dir, "frames")
            os.makedirs(frames_dir, exist_ok=True)

            fmt = s.image_format
            ext = "tiff" if fmt == "tiff" else "png"

            # Chroma-key settings
            chroma_on = getattr(s, "chroma_enabled", False)
            chroma_color = getattr(s, "chroma_color", (0, 0, 0))
            chroma_tol = getattr(s, "chroma_tolerance", 0.1)
            chroma_fade = getattr(s, "chroma_fade", 0.05)

            # Extraction mode: "none", "chroma", "edge_detect", "ai_segment"
            extraction_mode = getattr(s, "extraction_mode", "none")
            # Keep backward compat: if chroma_enabled but extraction_mode not set
            if chroma_on and extraction_mode == "none":
                extraction_mode = "chroma"

            extraction_active = extraction_mode != "none"

            # Extraction params
            prompt_point = getattr(s, "extraction_prompt_point", None)
            invert = getattr(s, "extraction_invert", False)
            edge_canny_low = getattr(s, "edge_canny_low", 50)
            edge_canny_high = getattr(s, "edge_canny_high", 150)
            edge_dilate = getattr(s, "edge_dilate", 2)
            edge_min_area = getattr(s, "edge_min_area", 500)
            ai_model = getattr(s, "ai_model", "u2netp")
            ai_confidence = getattr(s, "ai_confidence", 0.5)

            # Extraction output must be PNG (supports alpha channel)
            if extraction_active:
                ext = "png"

            count = 0

            for frame_idx, frame in vs.get_frame_range(initial, last, sampling):
                if self.is_cancelled():
                    self.cancelled.emit()
                    return

                masked = frame[t : fh - b, l : fw - r, :]

                # Save full masked frame to disk immediately (not held in RAM)
                slice_path = os.path.join(frames_dir, f"frame_{count:06d}.{ext}")
                if extraction_mode == "chroma":
                    rgba = apply_chroma_key(masked, chroma_color, chroma_tol, chroma_fade)
                    img = Image.fromarray(rgba)
                elif extraction_mode in ("edge_detect", "ai_segment"):
                    mask = extract_mask(
                        masked,
                        mode=extraction_mode,
                        prompt_point=prompt_point,
                        invert=invert,
                        canny_low=edge_canny_low,
                        canny_high=edge_canny_high,
                        dilate_iter=edge_dilate,
                        min_area=edge_min_area,
                        ai_model=ai_model,
                        ai_confidence=ai_confidence,
                    )
                    rgba = apply_extraction_mask(masked, mask, invert=False)
                    img = Image.fromarray(rgba)
                else:
                    img = Image.fromarray(masked)
                if fmt == "tiff" and not extraction_active:
                    img.save(slice_path, compression="tiff_lzw")
                else:
                    img.save(slice_path)

                count += 1
                self.progress.emit(count, total)

            if count == 0:
                self.error.emit("No frames were processed.")
                return

            self.finished.emit({
                "output_dir": self._output_dir,
                "frames_dir": frames_dir,
                "dimensions": {
                    "width": mask_w,
                    "height": mask_h,
                    "depth": count,
                },
                "frames_processed": count,
                "extraction_mode": extraction_mode,
                "fill_mode": True,
            })

        except Exception as e:
            self.error.emit(str(e))
