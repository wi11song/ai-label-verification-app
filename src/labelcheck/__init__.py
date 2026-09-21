"""Local alcohol-label checks. Comparison, line assignment, image quality, and OCR live here."""

from labelcheck.compare import compare_label
from labelcheck.models import (
    Application,
    ExtractedField,
    ExtractedLabel,
    FieldStatus,
    LabelVerdict,
    OverallStatus,
)
from labelcheck.parse import OcrLine, parse_lines
from labelcheck.quality import ImageCheck, check_image
from labelcheck.verify import Verification, verify_label

__all__ = [
    "Application",
    "ExtractedField",
    "ExtractedLabel",
    "FieldStatus",
    "ImageCheck",
    "LabelVerdict",
    "OcrLine",
    "OverallStatus",
    "Verification",
    "check_image",
    "compare_label",
    "parse_lines",
    "verify_label",
]
