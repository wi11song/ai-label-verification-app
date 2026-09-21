"""One label: quality gate, then OCR, then the comparison rules.

OCR does not run when the file is unusable or the photo cannot be read.
"""

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from io import BytesIO

from PIL import Image, ImageOps

from labelcheck.compare import compare_label
from labelcheck.models import Application, LabelVerdict
from labelcheck.ocr import read_lines
from labelcheck.parse import OcrLine, parse_lines
from labelcheck.quality import UNSUPPORTED_IMAGE, check_image

logger = logging.getLogger("labelcheck")

MISSING_APPLICATION = (
    "Brand, class, alcohol content, and net contents are required before verification."
)
CHECK_FAILED = "Verification could not finish. Try again."
CHECK_TIMEOUT = "Verification took too long. Try again, or use a smaller image."
_REQUIRED = ("brand_name", "class_type", "alcohol_content", "net_contents")


@dataclass
class Verification:
    verdict: LabelVerdict | None = None
    error: str | None = None
    transcript: list[str] = field(default_factory=list)
    seconds: float = 0.0


def verify_label(
    data: bytes,
    application: Application,
    *,
    reader: Callable[[Image.Image], list[OcrLine]] | None = None,
) -> Verification:
    started = time.perf_counter()
    ocr_seconds = 0.0
    check = check_image(data)
    if check.error:
        result = Verification(error=check.error)
    elif not check.readable:
        result = Verification(
            verdict=compare_label(
                application,
                image_readable=False,
                image_note=check.note,
            )
        )
    elif not _has_required_fields(application):
        result = Verification(error=MISSING_APPLICATION)
    else:
        try:
            image = _upright(data)
        except (OSError, ValueError):
            result = Verification(error=UNSUPPORTED_IMAGE)
        else:
            ocr_started = time.perf_counter()
            lines = (reader or read_lines)(image)
            ocr_seconds = time.perf_counter() - ocr_started
            result = Verification(
                verdict=compare_label(application, parse_lines(lines)),
                transcript=[line.text for line in lines],
            )
    result.seconds = time.perf_counter() - started
    overall = "error" if result.error else result.verdict.overall.value
    logger.info(
        "verify overall=%s seconds=%.3f ocr_seconds=%.3f",
        overall,
        result.seconds,
        ocr_seconds,
    )
    return result


def _has_required_fields(application: Application) -> bool:
    return all(getattr(application, name).strip() for name in _REQUIRED)


def _upright(data: bytes) -> Image.Image:
    with Image.open(BytesIO(data)) as image:
        image.load()
        oriented = ImageOps.exif_transpose(image) or image
        return oriented.convert("RGB")
