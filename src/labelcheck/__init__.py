"""Local alcohol-label checks. Comparison rules live here; OCR comes in later."""

from labelcheck.compare import compare_label
from labelcheck.models import (
    Application,
    ExtractedField,
    ExtractedLabel,
    FieldStatus,
    LabelVerdict,
    OverallStatus,
)

__all__ = [
    "Application",
    "ExtractedField",
    "ExtractedLabel",
    "FieldStatus",
    "LabelVerdict",
    "OverallStatus",
    "compare_label",
]
