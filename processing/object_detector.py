"""Object extraction from video frames via edge detection or AI segmentation.

Two extraction backends:
  1. Edge Detection — Canny + morphological ops (no extra dependencies)
  2. AI Segmentation — U²-Net salient object detection via ONNX Runtime

Both support:
  - Fully automatic mode (detect all foreground)
  - Point-prompt mode (user clicks → only the object at that point)
"""

import os
import logging
from pathlib import Path

import cv2
import numpy as np

from config import (
    DETECTION_MODEL_CACHE_DIR,
    DETECTION_U2NETP_URL,
    DETECTION_U2NETP_FILENAME,
    DETECTION_U2NET_URL,
    DETECTION_U2NET_FILENAME,
    DETECTION_INPUT_SIZE,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Model download / cache helpers
# ---------------------------------------------------------------------------

def _model_cache_dir() -> Path:
    """Return the model cache directory, creating it if needed."""
    d = Path(os.path.expanduser(DETECTION_MODEL_CACHE_DIR))
    d.mkdir(parents=True, exist_ok=True)
    return d


def _model_path(model_name: str) -> Path:
    """Return the expected local path for a model."""
    filename = DETECTION_U2NETP_FILENAME if model_name == "u2netp" else DETECTION_U2NET_FILENAME
    # Also check resources/models/ inside the package (for bundled builds)
    pkg_path = Path(__file__).resolve().parent.parent / "resources" / "models" / filename
    if pkg_path.exists():
        return pkg_path
    return _model_cache_dir() / filename


def is_model_available(model_name: str = "u2netp") -> bool:
    """Check whether the ONNX model file exists locally."""
    return _model_path(model_name).exists()


def is_onnxruntime_available() -> bool:
    """Check whether onnxruntime is installed."""
    try:
        import onnxruntime  # noqa: F401
        return True
    except ImportError:
        return False


def download_model(model_name: str = "u2netp", progress_callback=None) -> Path:
    """Download the ONNX model to the cache directory.

    Args:
        model_name: "u2netp" (4.7 MB, fast) or "u2net" (176 MB, quality)
        progress_callback: optional callable(bytes_downloaded, total_bytes)

    Returns:
        Path to the downloaded model file.

    Raises:
        RuntimeError: If download fails.
    """
    import urllib.request
    import tempfile
    import shutil

    url = DETECTION_U2NETP_URL if model_name == "u2netp" else DETECTION_U2NET_URL
    dest = _model_cache_dir() / (DETECTION_U2NETP_FILENAME if model_name == "u2netp" else DETECTION_U2NET_FILENAME)

    if dest.exists():
        return dest

    logger.info("Downloading %s from %s …", model_name, url)

    # Download to a temp file first, then move atomically
    tmp_fd, tmp_path = tempfile.mkstemp(dir=dest.parent, suffix=".tmp")
    os.close(tmp_fd)
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "KinoVolume/0.1"})
        with urllib.request.urlopen(req, timeout=120) as resp:
            total = int(resp.headers.get("Content-Length", 0))
            downloaded = 0
            with open(tmp_path, "wb") as f:
                while True:
                    chunk = resp.read(1024 * 256)  # 256 KB chunks
                    if not chunk:
                        break
                    f.write(chunk)
                    downloaded += len(chunk)
                    if progress_callback:
                        progress_callback(downloaded, total)
        shutil.move(tmp_path, dest)
        logger.info("Model saved to %s", dest)
        return dest
    except Exception as exc:
        # Clean up partial download
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
        raise RuntimeError(f"Failed to download {model_name}: {exc}") from exc


# ---------------------------------------------------------------------------
# Edge Detection extraction
# ---------------------------------------------------------------------------

def extract_edge_mask(
    image: np.ndarray,
    canny_low: int = 50,
    canny_high: int = 150,
    dilate_iter: int = 2,
    min_area: int = 500,
    prompt_point: tuple[int, int] | None = None,
) -> np.ndarray:
    """Generate a binary mask using Canny edge detection + contour filling.

    Args:
        image: RGB uint8 array (H, W, 3)
        canny_low: Canny lower threshold
        canny_high: Canny upper threshold
        dilate_iter: number of morphological dilation iterations to close gaps
        min_area: minimum contour area (pixels) to keep
        prompt_point: (x, y) — if given, only keep the contour containing this point

    Returns:
        Binary mask uint8 (H, W) — 255 = foreground, 0 = background
    """
    gray = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY)

    # Apply Gaussian blur to reduce noise
    blurred = cv2.GaussianBlur(gray, (5, 5), 0)

    # Canny edge detection
    edges = cv2.Canny(blurred, canny_low, canny_high)

    # Morphological closing to connect edge gaps
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    if dilate_iter > 0:
        edges = cv2.dilate(edges, kernel, iterations=dilate_iter)
        edges = cv2.erode(edges, kernel, iterations=max(1, dilate_iter - 1))

    # Find contours and fill them
    contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    mask = np.zeros(image.shape[:2], dtype=np.uint8)

    if prompt_point is not None:
        # Point-prompt: keep only the contour containing the clicked point
        px, py = prompt_point
        best_contour = None
        best_area = float("inf")
        for cnt in contours:
            area = cv2.contourArea(cnt)
            if area < min_area:
                continue
            # pointPolygonTest: >0 means inside
            if cv2.pointPolygonTest(cnt, (float(px), float(py)), False) >= 0:
                # Pick the smallest enclosing contour
                if area < best_area:
                    best_area = area
                    best_contour = cnt
        if best_contour is not None:
            cv2.drawContours(mask, [best_contour], -1, 255, thickness=cv2.FILLED)
        else:
            # Fallback: find the closest contour to the point
            min_dist = float("inf")
            for cnt in contours:
                if cv2.contourArea(cnt) < min_area:
                    continue
                dist = abs(cv2.pointPolygonTest(cnt, (float(px), float(py)), True))
                if dist < min_dist:
                    min_dist = dist
                    best_contour = cnt
            if best_contour is not None:
                cv2.drawContours(mask, [best_contour], -1, 255, thickness=cv2.FILLED)
    else:
        # Auto: keep all contours above min_area
        for cnt in contours:
            if cv2.contourArea(cnt) >= min_area:
                cv2.drawContours(mask, [cnt], -1, 255, thickness=cv2.FILLED)

    return mask


# ---------------------------------------------------------------------------
# AI Segmentation extraction (U²-Net via ONNX Runtime)
# ---------------------------------------------------------------------------

_onnx_session = None
_onnx_model_name = None


def _get_onnx_session(model_name: str = "u2netp"):
    """Lazy-load the ONNX Runtime inference session (cached)."""
    global _onnx_session, _onnx_model_name

    if _onnx_session is not None and _onnx_model_name == model_name:
        return _onnx_session

    import onnxruntime as ort

    path = _model_path(model_name)
    if not path.exists():
        raise FileNotFoundError(
            f"Model file not found: {path}. "
            f"Run download_model('{model_name}') first."
        )

    providers = ort.get_available_providers()
    # Prefer GPU providers when available
    preferred = []
    for p in ["CUDAExecutionProvider", "CoreMLExecutionProvider", "DmlExecutionProvider"]:
        if p in providers:
            preferred.append(p)
    preferred.append("CPUExecutionProvider")

    logger.info("Loading ONNX model %s with providers %s", model_name, preferred)
    _onnx_session = ort.InferenceSession(str(path), providers=preferred)
    _onnx_model_name = model_name
    return _onnx_session


def _preprocess_u2net(image: np.ndarray, input_size: int = DETECTION_INPUT_SIZE) -> np.ndarray:
    """Preprocess an RGB image for U²-Net input.

    Returns:
        Float32 array (1, 3, input_size, input_size) normalized.
    """
    h, w = image.shape[:2]
    resized = cv2.resize(image, (input_size, input_size), interpolation=cv2.INTER_LINEAR)
    # Normalize to [0, 1] then apply ImageNet-style normalization
    x = resized.astype(np.float32) / 255.0
    mean = np.array([0.485, 0.456, 0.406], dtype=np.float32)
    std = np.array([0.229, 0.224, 0.225], dtype=np.float32)
    x = (x - mean) / std
    # HWC → CHW → NCHW
    x = x.transpose(2, 0, 1)[np.newaxis, ...]
    return x


def _postprocess_u2net(output: np.ndarray, original_h: int, original_w: int) -> np.ndarray:
    """Convert U²-Net output to a probability map at original resolution.

    Returns:
        Float32 array (H, W) in [0, 1] — probability of foreground.
    """
    # U²-Net outputs multiple heads; use the first (finest) one
    pred = output[0]  # shape: (1, 1, H, W) or (1, H, W)
    if pred.ndim == 4:
        pred = pred[0, 0]
    elif pred.ndim == 3:
        pred = pred[0]

    # Sigmoid (outputs may not be sigmoided depending on export)
    if pred.min() < 0 or pred.max() > 1:
        pred = 1.0 / (1.0 + np.exp(-pred))

    # Normalize to [0, 1]
    pred_min, pred_max = pred.min(), pred.max()
    if pred_max - pred_min > 1e-6:
        pred = (pred - pred_min) / (pred_max - pred_min)

    # Resize back to original dimensions
    prob_map = cv2.resize(pred.astype(np.float32), (original_w, original_h),
                          interpolation=cv2.INTER_LINEAR)
    return prob_map


def extract_ai_mask(
    image: np.ndarray,
    model_name: str = "u2netp",
    confidence: float = 0.5,
    prompt_point: tuple[int, int] | None = None,
) -> np.ndarray:
    """Generate a binary mask using U²-Net AI segmentation.

    Args:
        image: RGB uint8 array (H, W, 3)
        model_name: "u2netp" (fast) or "u2net" (quality)
        confidence: threshold for the probability map (0.0–1.0)
        prompt_point: (x, y) — if given, only keep the connected component
                      containing this point

    Returns:
        Binary mask uint8 (H, W) — 255 = foreground, 0 = background
    """
    session = _get_onnx_session(model_name)
    h, w = image.shape[:2]

    # Preprocess
    input_tensor = _preprocess_u2net(image)

    # Inference
    input_name = session.get_inputs()[0].name
    outputs = session.run(None, {input_name: input_tensor})

    # Postprocess → probability map
    prob_map = _postprocess_u2net(outputs[0], h, w)

    # Threshold to binary mask
    mask = (prob_map >= confidence).astype(np.uint8) * 255

    if prompt_point is not None:
        # Keep only the connected component containing the clicked point
        px, py = prompt_point
        px = max(0, min(px, w - 1))
        py = max(0, min(py, h - 1))

        num_labels, labels = cv2.connectedComponents(mask)
        target_label = labels[py, px]
        if target_label == 0:
            # Clicked on background — find nearest foreground component
            # by dilating from the point
            search_radius = max(w, h) // 10
            best_label = 0
            for r in range(1, search_radius):
                y1 = max(0, py - r)
                y2 = min(h, py + r + 1)
                x1 = max(0, px - r)
                x2 = min(w, px + r + 1)
                region = labels[y1:y2, x1:x2]
                fg_labels = region[region > 0]
                if len(fg_labels) > 0:
                    # Pick the most common label in the search region
                    best_label = int(np.bincount(fg_labels).argmax())
                    break
            target_label = best_label

        if target_label > 0:
            mask = ((labels == target_label).astype(np.uint8)) * 255
        else:
            # No foreground found near the point — return empty mask
            mask = np.zeros((h, w), dtype=np.uint8)

    return mask


# ---------------------------------------------------------------------------
# Unified API
# ---------------------------------------------------------------------------

def apply_extraction_mask(
    image: np.ndarray,
    mask: np.ndarray,
    invert: bool = False,
) -> np.ndarray:
    """Apply a binary mask to an RGB image, producing an RGBA image.

    Foreground pixels (mask=255) keep full opacity; background becomes transparent.

    Args:
        image: RGB uint8 (H, W, 3)
        mask: Binary uint8 (H, W) — 255 = foreground
        invert: if True, swap foreground/background

    Returns:
        RGBA uint8 (H, W, 4)
    """
    if invert:
        alpha = 255 - mask
    else:
        alpha = mask
    return np.dstack([image, alpha])


def extract_mask(
    image: np.ndarray,
    mode: str,
    prompt_point: tuple[int, int] | None = None,
    invert: bool = False,
    # Edge detection params
    canny_low: int = 50,
    canny_high: int = 150,
    dilate_iter: int = 2,
    min_area: int = 500,
    # AI params
    ai_model: str = "u2netp",
    ai_confidence: float = 0.5,
) -> np.ndarray:
    """Unified extraction: returns a binary mask (H, W) uint8.

    Args:
        image: RGB uint8 (H, W, 3)
        mode: "edge_detect" or "ai_segment"
        prompt_point: (x, y) or None for auto
        invert: flip foreground/background
        (remaining args forwarded to the specific backend)

    Returns:
        Binary mask uint8 (H, W) — 255 = foreground, 0 = background
    """
    if mode == "edge_detect":
        mask = extract_edge_mask(
            image,
            canny_low=canny_low,
            canny_high=canny_high,
            dilate_iter=dilate_iter,
            min_area=min_area,
            prompt_point=prompt_point,
        )
    elif mode == "ai_segment":
        mask = extract_ai_mask(
            image,
            model_name=ai_model,
            confidence=ai_confidence,
            prompt_point=prompt_point,
        )
    else:
        raise ValueError(f"Unknown extraction mode: {mode}")

    if invert:
        mask = 255 - mask

    return mask
