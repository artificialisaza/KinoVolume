"""Chroma-key transparency: make a user-selected color transparent in images.

Works like a green screen / chroma key: pixels matching the target color
become transparent (alpha=0). Tolerance controls the match range, and fade
creates smooth edges around the transparent region.
"""

import numpy as np


def apply_chroma_key(
    image: np.ndarray,
    target_color: tuple[int, int, int],
    tolerance: float,
    fade: float,
) -> np.ndarray:
    """Make pixels matching target_color transparent.

    Args:
        image: RGB uint8 array (H, W, 3)
        target_color: (R, G, B) values 0-255
        tolerance: 0.0-1.0 — fraction of max RGB distance.
                   Pixels within this distance become fully transparent.
        fade: 0.0-1.0 — range beyond tolerance where alpha fades
              from 0 (transparent) to 255 (opaque).

    Returns:
        RGBA uint8 array (H, W, 4) with transparency applied.
    """
    max_dist = 441.67  # sqrt(255^2 * 3)
    tol_dist = tolerance * max_dist
    fade_dist = fade * max_dist

    # Per-pixel Euclidean distance from target color
    diff = image.astype(np.float32) - np.array(target_color, dtype=np.float32)
    dist = np.sqrt(np.sum(diff * diff, axis=2))

    # Build alpha channel
    alpha = np.full(dist.shape, 255, dtype=np.uint8)

    # Within tolerance → fully transparent
    alpha[dist <= tol_dist] = 0

    # Within fade range → gradual transparency
    if fade_dist > 0:
        fade_mask = (dist > tol_dist) & (dist <= tol_dist + fade_dist)
        alpha[fade_mask] = (
            (dist[fade_mask] - tol_dist) / fade_dist * 255
        ).astype(np.uint8)

    # Combine into RGBA
    rgba = np.dstack([image, alpha])
    return rgba
