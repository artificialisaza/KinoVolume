"""Cylinder processor: extract a circular mask from each frame.

Void mode: samples pixels along the circle perimeter from each frame,
building a surface texture. First and last frames provide circular caps.

Fill mode: saves the full circular masked area per frame to disk.
"""

import os

import numpy as np
from PIL import Image

from processing.base_processor import BaseProcessor


class CylinderProcessor(BaseProcessor):
    """Extracts perimeter pixels into a surface texture + circular cap textures."""

    def run(self):
        try:
            s = self._state
            vs = s.video_source
            fw, fh = vs.width, vs.height

            cx = s.cylinder_center_x
            cy = s.cylinder_center_y
            radius = s.cylinder_radius

            if radius < 2:
                self.error.emit("Cylinder radius too small (need at least 2 px).")
                return

            initial = s.initial_frame
            last = s.last_frame
            sampling = s.sampling_rate
            total = max(1, (last - initial) // sampling + 1)

            fmt = s.image_format
            ext = "tiff" if fmt == "tiff" else "png"

            # Number of perimeter sample points
            circumference = max(int(2 * np.pi * radius), 6)

            # Pre-compute perimeter sample coordinates (vectorised)
            thetas = np.linspace(0, 2 * np.pi, circumference, endpoint=False)
            peri_x = np.clip(
                np.round(cx + radius * np.cos(thetas)).astype(np.intp),
                0, fw - 1,
            )
            peri_y = np.clip(
                np.round(cy + radius * np.sin(thetas)).astype(np.intp),
                0, fh - 1,
            )

            # Pre-allocate surface texture: (num_frames, circumference, 3)
            surface_img = np.zeros((total, circumference, 3), dtype=np.uint8)

            front_cap = None
            last_frame_data = None
            count = 0

            for frame_idx, frame in vs.get_frame_range(initial, last, sampling):
                if self.is_cancelled():
                    self.cancelled.emit()
                    return

                # Vectorised perimeter sampling — no Python per-pixel loop
                surface_img[count] = frame[peri_y, peri_x, :3]

                # Keep first frame for front cap
                if front_cap is None:
                    front_cap = frame

                # Always keep reference to latest frame for back cap
                last_frame_data = frame

                count += 1
                self.progress.emit(count, total)

            if count == 0:
                self.error.emit("No frames were processed.")
                return

            # Trim if fewer frames than expected
            if count < total:
                surface_img = surface_img[:count]

            # Extract caps only once each (vectorised)
            front_cap_img = self._extract_circular_cap(
                front_cap, cx, cy, radius, fw, fh,
            )
            back_cap_img = self._extract_circular_cap(
                last_frame_data, cx, cy, radius, fw, fh,
            )

            # Save textures
            os.makedirs(self._output_dir, exist_ok=True)

            paths = {}
            for name, data in [
                ("surface", surface_img),
                ("cap_front", front_cap_img),
                ("cap_back", back_cap_img),
            ]:
                out_path = os.path.join(self._output_dir, f"{name}.{ext}")
                img = Image.fromarray(data)
                if fmt == "tiff":
                    img.save(out_path, compression="tiff_lzw")
                else:
                    img.save(out_path)
                paths[name] = out_path

            diameter = radius * 2
            self.finished.emit({
                "output_dir": self._output_dir,
                "face_paths": paths,
                "dimensions": {
                    "width": diameter,
                    "height": diameter,
                    "depth": count,
                    "radius": radius,
                    "circumference": circumference,
                },
                "frames_processed": count,
            })

        except Exception as e:
            self.error.emit(str(e))

    @staticmethod
    def _extract_circular_cap(frame, cx, cy, radius, fw, fh):
        """Extract a square crop containing the circular area, black outside.

        Returns (2*radius, 2*radius, 3) uint8 array — fully vectorised.
        """
        diameter = radius * 2
        cap = np.zeros((diameter, diameter, 3), dtype=np.uint8)

        # Build coordinate grids
        yy, xx = np.ogrid[:diameter, :diameter]
        dist_sq = (xx - radius) ** 2 + (yy - radius) ** 2
        inside = dist_sq <= radius * radius

        # Map cap coords → frame coords, clamped
        fy = np.clip(np.arange(diameter) + (cy - radius), 0, fh - 1).astype(np.intp)
        fx = np.clip(np.arange(diameter) + (cx - radius), 0, fw - 1).astype(np.intp)

        # Vectorised extraction: frame[fy][:, fx] gives (diameter, diameter, 3)
        crop = frame[np.ix_(fy, fx)][:, :, :3]
        cap[inside] = crop[inside]
        return cap
