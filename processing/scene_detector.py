"""Hard cut detection using mean absolute frame difference.

Works on colour and grayscale / black-and-white video alike.
Compares consecutive frames by mean pixel difference — a sudden
spike indicates a hard cut (shot boundary).
"""

import logging
import cv2
import numpy as np

_log = logging.getLogger(__name__)

# Default threshold: mean absolute difference per pixel (0–255 scale).
# Typical intra-shot difference is 2–8; a hard cut is usually 30+.
_DEFAULT_THRESHOLD = 25.0


def _frame_diff(frame_a, frame_b):
    """Return the mean absolute pixel difference between two frames."""
    diff = cv2.absdiff(frame_a, frame_b)
    return float(np.mean(diff))


def find_next_cut(video_path, start_frame, direction=1,
                  threshold=_DEFAULT_THRESHOLD, step=1):
    """Search for the nearest hard cut from *start_frame*.

    Reads frames sequentially (fast) rather than random-seeking.

    Args:
        video_path:   path to the video file
        start_frame:  frame index to start searching from
        direction:    +1 for forward, -1 for backward
        threshold:    mean pixel difference to consider a cut (0–255)
        step:         compare every *step*-th frame pair
    Returns:
        Frame index of the detected cut, or None if none found.
    """
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        _log.error("find_next_cut: cannot open %s", video_path)
        return None

    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    if total < 2:
        _log.warning("find_next_cut: video has < 2 frames (total=%d)", total)
        cap.release()
        return None

    step = max(1, step)

    try:
        if direction >= 0:
            return _search_forward(cap, start_frame, total, threshold, step)
        else:
            return _search_backward(cap, start_frame, total, threshold, step)
    except Exception:
        _log.exception("find_next_cut failed")
        return None
    finally:
        cap.release()


def _search_forward(cap, start, total, threshold, step):
    """Read sequentially forward, comparing consecutive frames."""
    seek_to = max(0, start)
    cap.set(cv2.CAP_PROP_POS_FRAMES, seek_to)
    ret, prev_frame = cap.read()
    if not ret:
        _log.warning("_search_forward: cannot read frame %d", seek_to)
        return None

    idx = seek_to + 1
    while idx < total:
        ret, frame = cap.read()
        if not ret:
            break
        if (idx - seek_to) % step == 0:
            diff = _frame_diff(prev_frame, frame)
            if diff >= threshold:
                _log.info("Cut at frame %d (diff=%.1f)", idx, diff)
                return idx
            prev_frame = frame
        idx += 1

    _log.info("No cut found forward from frame %d", start)
    return None


def _search_backward(cap, start, total, threshold, step):
    """Search backward using chunked sequential reads."""
    CHUNK = 200
    end = min(start, total - 1)
    while end > 0:
        begin = max(0, end - CHUNK)
        cap.set(cv2.CAP_PROP_POS_FRAMES, begin)

        # Read the chunk sequentially
        frames = []
        for i in range(begin, end + 1):
            ret, frame = cap.read()
            if not ret:
                break
            if (i - begin) % step == 0 or i == end:
                frames.append((i, frame))

        # Walk pairs in reverse to find the cut nearest to start
        for j in range(len(frames) - 1, 0, -1):
            idx_b, frame_b = frames[j]
            idx_a, frame_a = frames[j - 1]
            diff = _frame_diff(frame_a, frame_b)
            if diff >= threshold:
                _log.info("Cut at frame %d (diff=%.1f)", idx_b, diff)
                return idx_b

        end = begin
        if begin == 0:
            break

    _log.info("No cut found backward from frame %d", start)
    return None
