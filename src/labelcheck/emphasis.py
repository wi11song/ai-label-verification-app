"""Compare the stroke weight of GOVERNMENT WARNING: with the warning body.

The crops come from OCR boxes. A crop that is too small, too faint, or piled
on the other crop is inconclusive. An inconclusive result is not a guess.
"""

from PIL import Image

import numpy as np

# The bourbon sample's prefix stroke is about twice the body, in pixels.
# A smaller gap is not called bold, because a wrong guess would fail a good label.
_HEAVIER_RATIO = 1.45
_HEAVIER_GAP = 1.0
_MIN_SIDE = 12
_MIN_CONTRAST = 40
_OVERLAP = 0.45


def compare_crops(prefix: Image.Image, body: Image.Image) -> str:
    """Return match, mismatch, or inconclusive."""
    prefix_weight = stroke_weight(prefix)
    body_weight = stroke_weight(body)
    if prefix_weight is None or body_weight is None:
        return "inconclusive"
    heavier = prefix_weight >= body_weight * _HEAVIER_RATIO
    gap = prefix_weight - body_weight >= _HEAVIER_GAP
    if heavier and gap:
        return "match"
    return "mismatch"


def stroke_weight(crop: Image.Image) -> float | None:
    """Median ink-run length in pixels. None when the crop cannot be judged."""
    gray = np.asarray(crop.convert("L"), dtype=np.float32)
    height, width = gray.shape
    if height < _MIN_SIDE or width < _MIN_SIDE:
        return None
    low, high = np.percentile(gray, (10, 90))
    if float(high - low) < _MIN_CONTRAST:
        return None
    ink = gray <= (float(low) + float(high)) / 2
    density = float(ink.mean())
    if density < 0.03 or density > 0.8:
        return None
    runs = _runs(ink) + _runs(ink.T)
    if len(runs) < 8:
        return None
    return float(np.median(runs))


def boxes_overlap(prefix: tuple[float, float, float, float], body: tuple[float, float, float, float]) -> bool:
    left = max(prefix[0], body[0])
    top = max(prefix[1], body[1])
    right = min(prefix[2], body[2])
    bottom = min(prefix[3], body[3])
    if right <= left or bottom <= top:
        return False
    shared = (right - left) * (bottom - top)
    prefix_area = max((prefix[2] - prefix[0]) * (prefix[3] - prefix[1]), 1.0)
    body_area = max((body[2] - body[0]) * (body[3] - body[1]), 1.0)
    return shared / min(prefix_area, body_area) >= _OVERLAP


def _runs(ink: np.ndarray) -> list[int]:
    lengths: list[int] = []
    for row in ink:
        run = 0
        for bit in row:
            if bit:
                run += 1
                continue
            if run >= 2:
                lengths.append(run)
            run = 0
        if run >= 2:
            lengths.append(run)
    return lengths
