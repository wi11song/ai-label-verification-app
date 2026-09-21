"""Straighten a label when the text baseline is tilted a few degrees.

The angle comes from the horizontal projection of the ink. A small, clear tilt
is rotated back. An uncertain angle, or a large one, keeps the original photo.
"""

from PIL import Image

import numpy as np

_PROBE_EDGE = 220
_ANGLES = (-4, -3, -2, 2, 3, 4)
_MIN_ANGLE = 2
_GAIN = 1.08
_INK_BELOW = 180


def deskew(image: Image.Image) -> Image.Image:
    angle = _clear_tilt(image)
    if angle is None:
        return image
    return image.rotate(
        angle,
        resample=Image.Resampling.BICUBIC,
        expand=True,
        fillcolor=_fill(image),
    )


def _clear_tilt(image: Image.Image) -> int | None:
    if min(image.size) < 200:
        return None
    sample = _sample(image)
    baseline = _score_array(np.asarray(sample, dtype=np.uint8))
    if baseline <= 0:
        return None
    best_angle = 0
    best = baseline
    for angle in _ANGLES:
        turned = sample.rotate(angle, resample=Image.Resampling.NEAREST, expand=False, fillcolor=255)
        score = _score_array(np.asarray(turned, dtype=np.uint8))
        if score > best:
            best = score
            best_angle = angle
    if abs(best_angle) < _MIN_ANGLE or best < baseline * _GAIN:
        return None
    return best_angle


def _sample(image: Image.Image) -> Image.Image:
    gray = image.convert("L")
    long_edge = max(gray.size)
    if long_edge <= _PROBE_EDGE:
        return gray
    scale = _PROBE_EDGE / long_edge
    size = (max(1, round(gray.width * scale)), max(1, round(gray.height * scale)))
    return gray.resize(size, Image.Resampling.BILINEAR)


def _score_array(values: np.ndarray) -> float:
    ink = values < _INK_BELOW
    if int(ink.sum()) < 30:
        return 0.0
    rows = ink.sum(axis=1).astype(np.float64)
    return float(rows.var())



def _fill(image: Image.Image) -> tuple[int, int, int]:
    rgb = image.convert("RGB")
    pixel = rgb.getpixel((0, 0))
    if isinstance(pixel, int):
        return (pixel, pixel, pixel)
    return pixel[0], pixel[1], pixel[2]
