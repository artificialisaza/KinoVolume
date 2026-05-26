from collections.abc import Generator

import cv2
import numpy as np


class VideoSource:
    """Wraps cv2.VideoCapture for frame access and metadata."""

    def __init__(self, file_path: str):
        self.file_path = file_path
        self._cap = cv2.VideoCapture(file_path)
        if not self._cap.isOpened():
            raise ValueError(f"Cannot open video file: {file_path}")

        self.frame_count = int(self._cap.get(cv2.CAP_PROP_FRAME_COUNT))
        self.fps = self._cap.get(cv2.CAP_PROP_FPS)
        self.width = int(self._cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        self.height = int(self._cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        self.duration_seconds = self.frame_count / self.fps if self.fps > 0 else 0.0

    def get_frame(self, index: int) -> np.ndarray | None:
        """Seek to frame index and return RGB numpy array, or None if invalid."""
        if index < 0 or index >= self.frame_count:
            return None
        self._cap.set(cv2.CAP_PROP_POS_FRAMES, index)
        ret, frame = self._cap.read()
        if not ret:
            return None
        return cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

    def get_frame_range(
        self, start: int, end: int, step: int = 1
    ) -> Generator[tuple[int, np.ndarray], None, None]:
        """Yield (frame_index, rgb_array) tuples by sequential reading.

        Reads frames sequentially using cap.read() which is much faster than
        seeking for each frame in compressed codecs. Skips frames where
        (index - start) % step != 0.
        """
        self._cap.set(cv2.CAP_PROP_POS_FRAMES, start)
        for index in range(start, end + 1):
            ret, frame = self._cap.read()
            if not ret:
                break
            if (index - start) % step == 0:
                yield index, cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

    def close(self):
        """Release the VideoCapture resource."""
        if self._cap is not None:
            self._cap.release()
            self._cap = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
        return False
