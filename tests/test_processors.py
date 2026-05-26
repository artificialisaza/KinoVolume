"""Tests for SliceProcessor and CuboidVoidProcessor."""

import os
import tempfile

import cv2
import numpy as np
import pytest
from PIL import Image
from PySide6.QtWidgets import QApplication

from models.video_source import VideoSource
from models.project_state import ProjectState


# Ensure a QApplication exists for QThread signal delivery
@pytest.fixture(scope="session", autouse=True)
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


# ── Helpers ──────────────────────────────────────────────────────────────────

@pytest.fixture
def synthetic_video(tmp_path):
    """Create a short test video with known pixel values."""
    path = str(tmp_path / "test.avi")
    w, h, nframes = 40, 30, 20
    fourcc = cv2.VideoWriter_fourcc(*"MJPG")
    writer = cv2.VideoWriter(path, fourcc, 10.0, (w, h))

    for i in range(nframes):
        frame = np.zeros((h, w, 3), dtype=np.uint8)
        frame[:, :, 2] = min(255, i * 12)
        for x in range(w):
            frame[:, x, 1] = min(255, x * 6)
        for y in range(h):
            frame[y, :, 0] = min(255, y * 8)
        writer.write(frame)

    writer.release()
    return path, w, h, nframes


@pytest.fixture
def state_and_video(synthetic_video, tmp_path):
    """Provide a ProjectState already loaded with the synthetic video."""
    path, w, h, nframes = synthetic_video
    vs = VideoSource(path)
    state = ProjectState()
    state.set_video_source(vs)
    out_dir = str(tmp_path / "output")
    os.makedirs(out_dir, exist_ok=True)
    return state, out_dir, w, h, nframes


def run_processor(proc):
    """Run a processor synchronously by calling its run() method directly."""
    results = {}
    errors = []
    proc.finished.connect(lambda r: results.update(r))
    proc.error.connect(lambda e: errors.append(e))
    proc.run()  # Call run() directly — synchronous, no thread
    if errors:
        raise RuntimeError(errors[0])
    return results


# ── Slice Processor ────────────────────────────────────────────────────────

class TestSliceProcessor:
    def test_vertical_slice_output_dimensions(self, state_and_video):
        from processing.slice_processor import SliceProcessor

        state, out_dir, w, h, nframes = state_and_video
        state.slit_orientation = "Vertical"
        state.slit_position = 10
        state.slit_width = 2
        state.initial_frame = 0
        state.last_frame = nframes - 1
        state.sampling_rate = 1

        proc = SliceProcessor(state, out_dir)
        results = run_processor(proc)

        img = np.array(Image.open(results["image_path"]))
        assert img.shape[0] == h
        assert img.shape[1] == nframes * 2
        assert results["frames_processed"] == nframes

    def test_horizontal_slice_output_dimensions(self, state_and_video):
        from processing.slice_processor import SliceProcessor

        state, out_dir, w, h, nframes = state_and_video
        state.slit_orientation = "Horizontal"
        state.slit_position = 5
        state.slit_width = 3
        state.initial_frame = 0
        state.last_frame = nframes - 1
        state.sampling_rate = 1

        proc = SliceProcessor(state, out_dir)
        results = run_processor(proc)

        img = np.array(Image.open(results["image_path"]))
        assert img.shape[0] == nframes * 3
        assert img.shape[1] == w

    def test_sampling_reduces_output(self, state_and_video):
        from processing.slice_processor import SliceProcessor

        state, out_dir, w, h, nframes = state_and_video
        state.slit_orientation = "Vertical"
        state.slit_position = 0
        state.slit_width = 1
        state.initial_frame = 0
        state.last_frame = nframes - 1
        state.sampling_rate = 2

        proc = SliceProcessor(state, out_dir)
        results = run_processor(proc)

        img = np.array(Image.open(results["image_path"]))
        expected_frames = len(range(0, nframes, 2))
        assert img.shape[1] == expected_frames * 1


# ── Cuboid Void Processor ─────────────────────────────────────────────────

class TestCuboidVoidProcessor:
    def test_face_textures_created(self, state_and_video):
        from processing.cuboid_void_processor import CuboidVoidProcessor

        state, out_dir, w, h, nframes = state_and_video
        state.cuboid_border_left = 2
        state.cuboid_border_right = 2
        state.cuboid_border_top = 2
        state.cuboid_border_bottom = 2
        state.initial_frame = 0
        state.last_frame = nframes - 1
        state.sampling_rate = 1

        proc = CuboidVoidProcessor(state, out_dir)
        results = run_processor(proc)

        assert "face_paths" in results
        for name in ("front", "back", "top", "bottom", "left", "right"):
            assert name in results["face_paths"]
            assert os.path.exists(results["face_paths"][name])

    def test_face_dimensions(self, state_and_video):
        from processing.cuboid_void_processor import CuboidVoidProcessor

        state, out_dir, w, h, nframes = state_and_video
        l, r, t, b = 3, 3, 4, 4
        state.cuboid_border_left = l
        state.cuboid_border_right = r
        state.cuboid_border_top = t
        state.cuboid_border_bottom = b
        state.initial_frame = 0
        state.last_frame = nframes - 1
        state.sampling_rate = 1

        mask_w = w - l - r
        mask_h = h - t - b

        proc = CuboidVoidProcessor(state, out_dir)
        results = run_processor(proc)

        front = np.array(Image.open(results["face_paths"]["front"]))
        assert front.shape[:2] == (mask_h, mask_w)

        back = np.array(Image.open(results["face_paths"]["back"]))
        assert back.shape[:2] == (mask_h, mask_w)

        top = np.array(Image.open(results["face_paths"]["top"]))
        assert top.shape[:2] == (nframes, mask_w)

        left = np.array(Image.open(results["face_paths"]["left"]))
        assert left.shape[:2] == (nframes, mask_h)

    def test_sampling_changes_depth(self, state_and_video):
        from processing.cuboid_void_processor import CuboidVoidProcessor

        state, out_dir, w, h, nframes = state_and_video
        state.cuboid_border_left = 1
        state.cuboid_border_right = 1
        state.cuboid_border_top = 1
        state.cuboid_border_bottom = 1
        state.initial_frame = 0
        state.last_frame = nframes - 1
        state.sampling_rate = 4

        proc = CuboidVoidProcessor(state, out_dir)
        results = run_processor(proc)

        expected_frames = len(range(0, nframes, 4))
        assert results["dimensions"]["depth"] == expected_frames
