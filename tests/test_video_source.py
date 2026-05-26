import os
import tempfile

import cv2
import numpy as np
import pytest

from models.video_source import VideoSource

# --- Fixtures ---

@pytest.fixture
def synthetic_video_path():
    """Create a synthetic 10-frame color video and return its path."""
    tmp = tempfile.NamedTemporaryFile(suffix=".avi", delete=False)
    tmp.close()
    path = tmp.name

    width, height, fps, num_frames = 64, 48, 30.0, 10
    fourcc = cv2.VideoWriter_fourcc(*"MJPG")
    writer = cv2.VideoWriter(path, fourcc, fps, (width, height))

    for i in range(num_frames):
        # Each frame has a unique solid color based on frame index
        r = (i * 25) % 256
        g = (i * 50) % 256
        b = (i * 75) % 256
        frame = np.full((height, width, 3), (b, g, r), dtype=np.uint8)  # BGR
        writer.write(frame)

    writer.release()
    yield path
    os.unlink(path)


# --- Tests ---

class TestVideoSourceMetadata:
    def test_metadata_correct(self, synthetic_video_path):
        with VideoSource(synthetic_video_path) as vs:
            assert vs.frame_count == 10
            assert vs.width == 64
            assert vs.height == 48
            assert vs.fps == pytest.approx(30.0, abs=1.0)
            assert vs.duration_seconds == pytest.approx(10 / 30.0, abs=0.1)

    def test_invalid_file_raises(self):
        with pytest.raises(ValueError, match="Cannot open video file"):
            VideoSource("/nonexistent/path/fake.mp4")


class TestVideoSourceFrameAccess:
    def test_get_frame_first(self, synthetic_video_path):
        with VideoSource(synthetic_video_path) as vs:
            frame = vs.get_frame(0)
            assert frame is not None
            assert frame.shape == (48, 64, 3)
            # Frame 0: r=0, g=0, b=0 → RGB should be (0, 0, 0)
            assert frame.dtype == np.uint8

    def test_get_frame_negative_returns_none(self, synthetic_video_path):
        with VideoSource(synthetic_video_path) as vs:
            assert vs.get_frame(-1) is None

    def test_get_frame_out_of_bounds_returns_none(self, synthetic_video_path):
        with VideoSource(synthetic_video_path) as vs:
            assert vs.get_frame(999) is None

    def test_get_frame_returns_rgb(self, synthetic_video_path):
        with VideoSource(synthetic_video_path) as vs:
            # Frame 1: BGR written as (75, 50, 25); RGB should be (25, 50, 75)
            frame = vs.get_frame(1)
            assert frame is not None
            # Check a pixel — video codec may introduce minor compression artifacts
            pixel = frame[24, 32]  # center pixel
            assert pixel[0] == pytest.approx(25, abs=5)  # R
            assert pixel[1] == pytest.approx(50, abs=5)  # G
            assert pixel[2] == pytest.approx(75, abs=5)  # B


class TestVideoSourceFrameRange:
    def test_get_frame_range_step2(self, synthetic_video_path):
        with VideoSource(synthetic_video_path) as vs:
            frames = list(vs.get_frame_range(0, 9, 2))
            indices = [idx for idx, _ in frames]
            assert indices == [0, 2, 4, 6, 8]
            for _, frame in frames:
                assert frame.shape == (48, 64, 3)

    def test_get_frame_range_all(self, synthetic_video_path):
        with VideoSource(synthetic_video_path) as vs:
            frames = list(vs.get_frame_range(0, 9, 1))
            assert len(frames) == 10

    def test_get_frame_range_partial(self, synthetic_video_path):
        with VideoSource(synthetic_video_path) as vs:
            frames = list(vs.get_frame_range(3, 7, 1))
            indices = [idx for idx, _ in frames]
            assert indices == [3, 4, 5, 6, 7]


class TestVideoSourceContextManager:
    def test_context_manager_closes(self, synthetic_video_path):
        vs = VideoSource(synthetic_video_path)
        vs.close()
        # After close, cap should be None
        assert vs._cap is None
