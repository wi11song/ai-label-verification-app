"""Decide whether a label photo can be read before OCR starts.

A failed check is a bad photo, not a failed label. Corrupt files are errors.
Blur, size, and glare are needs-review notes for the comparison step.
"""

from dataclasses import dataclass
from io import BytesIO

import numpy as np
from PIL import Image, ImageOps

from labelcheck.thresholds import (
    BLUR_RESIZE_WIDTH,
    BLUR_VARIANCE_MIN,
    FLAT_STD_MAX,
    GLARE_BAND_FRACTION,
    GLARE_CONTRAST,
    GLARE_ROW_MEAN,
    MAX_IMAGE_BYTES,
    MIN_SHORT_EDGE,
    WHITE_FRACTION_MAX,
    WHITE_LEVEL,
)

UNREADABLE_IMAGE_SUMMARY = (
    "This image is too blurry to read. Upload a sharper photo, or review the label yourself."
)
IMAGE_TOO_SMALL = (
    "This image is too small to read. Upload a larger photo, or review the label yourself."
)
IMAGE_WASHED_OUT = (
    "This image is washed out and cannot be read. Upload a photo without the glare, "
    "or review the label yourself."
)
UNSUPPORTED_IMAGE = "This file is not a readable image. Use a JPEG or PNG."
IMAGE_TOO_LARGE = "This image is too large. Use a photo under 10 MB."

# MPO is the JPEG multi-picture format some phone cameras write.
_ALLOWED_FORMATS = {"JPEG", "PNG", "WEBP", "TIFF", "MPO"}


@dataclass(frozen=True)
class ImageCheck:
    readable: bool
    width: int = 0
    height: int = 0
    note: str | None = None
    error: str | None = None


def check_image(data: bytes) -> ImageCheck:
    if not data:
        return ImageCheck(False, error=UNSUPPORTED_IMAGE)
    if len(data) > MAX_IMAGE_BYTES:
        return ImageCheck(False, error=IMAGE_TOO_LARGE)
    try:
        with Image.open(BytesIO(data)) as image:
            image.load()
            if image.format not in _ALLOWED_FORMATS:
                return ImageCheck(False, error=UNSUPPORTED_IMAGE)
            oriented = ImageOps.exif_transpose(image)
            oriented.load()
            upright = oriented.copy()
    except (OSError, ValueError):
        return ImageCheck(False, error=UNSUPPORTED_IMAGE)

    width, height = upright.size
    if min(width, height) < MIN_SHORT_EDGE:
        return ImageCheck(False, width, height, note=IMAGE_TOO_SMALL)

    pixels = _resized_gray(upright)
    if _is_washed_out(pixels):
        return ImageCheck(False, width, height, note=IMAGE_WASHED_OUT)
    if _laplacian_variance(pixels) < BLUR_VARIANCE_MIN:
        return ImageCheck(False, width, height, note=UNREADABLE_IMAGE_SUMMARY)
    return ImageCheck(True, width, height)


def _resized_gray(image: Image.Image) -> np.ndarray:
    gray = image.convert("L")
    if gray.width != BLUR_RESIZE_WIDTH:
        height = max(1, round(gray.height * (BLUR_RESIZE_WIDTH / gray.width)))
        gray = gray.resize((BLUR_RESIZE_WIDTH, height), Image.Resampling.BILINEAR)
    return np.asarray(gray, dtype=np.float64)


def _is_washed_out(pixels: np.ndarray) -> bool:
    if float(pixels.std()) <= FLAT_STD_MAX:
        return True
    if float(np.mean(pixels >= WHITE_LEVEL)) >= WHITE_FRACTION_MAX:
        return True
    return _has_glare_band(pixels)


def _has_glare_band(pixels: np.ndarray) -> bool:
    row_means = pixels.mean(axis=1)
    bright = row_means >= GLARE_ROW_MEAN
    longest = current = 0
    for is_bright in bright:
        if is_bright:
            current += 1
            longest = max(longest, current)
        else:
            current = 0
    if longest < GLARE_BAND_FRACTION * len(row_means):
        return False
    if not np.any(~bright):
        return False
    return float(row_means[bright].mean() - row_means[~bright].mean()) >= GLARE_CONTRAST


def _laplacian_variance(pixels: np.ndarray) -> float:
    if pixels.shape[0] < 3 or pixels.shape[1] < 3:
        return 0.0
    center = pixels[1:-1, 1:-1]
    lap = (
        pixels[:-2, 1:-1]
        + pixels[2:, 1:-1]
        + pixels[1:-1, :-2]
        + pixels[1:-1, 2:]
        - (4 * center)
    )
    return float(lap.var())
