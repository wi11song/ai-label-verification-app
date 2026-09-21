"""A few degrees of tilt are corrected. An uncertain angle is left alone."""

import numpy as np
from PIL import Image, ImageDraw

from labelcheck.deskew import deskew


def test_a_straight_label_is_kept():
    image = _bars()

    assert deskew(image).tobytes() == image.tobytes()


def test_a_clear_tilt_is_straightened():
    tilted = _bars().rotate(4, resample=Image.Resampling.BICUBIC, expand=True, fillcolor="white")

    fixed = deskew(tilted)

    assert _row_variance(fixed) > _row_variance(tilted)


def test_a_blank_photo_is_kept():
    blank = Image.new("RGB", (400, 300), (240, 240, 240))

    assert deskew(blank).tobytes() == blank.tobytes()


def _bars() -> Image.Image:
    image = Image.new("RGB", (640, 420), "white")
    draw = ImageDraw.Draw(image)
    for top in range(30, 390, 28):
        draw.rectangle((40, top, 600, top + 5), fill="black")
    return image


def _row_variance(image: Image.Image) -> float:
    ink = np.asarray(image.convert("L"), dtype=np.uint8) < 180
    return float(ink.sum(axis=1).astype(np.float64).var())
