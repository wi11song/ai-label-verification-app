"""Shared application and OCR-line fixtures. No images and no OCR model."""

from labelcheck.models import Application, ExtractedField, ExtractedLabel
from labelcheck.parse import OcrLine
from labelcheck.statute import STATUTORY_WARNING


def field(text: str, confidence: float | None = 0.95, note: str | None = None) -> ExtractedField:
    return ExtractedField(text=text, confidence=confidence, assignment_note=note)


def bourbon_application(**overrides: str) -> Application:
    values = {
        "brand_name": "OLD TOM DISTILLERY",
        "class_type": "Kentucky Straight Bourbon Whiskey",
        "alcohol_content": "45%",
        "net_contents": "750 mL",
        "government_warning": "",
    }
    values.update(overrides)
    return Application(**values)


def bourbon_extracted(**overrides: ExtractedField) -> ExtractedLabel:
    extracted = ExtractedLabel(
        brand_name=field("OLD TOM DISTILLERY"),
        class_type=field("Kentucky Straight Bourbon Whiskey"),
        alcohol_content=field("45% Alc./Vol. (90 Proof)"),
        net_contents=field("750 mL"),
        government_warning=field(STATUTORY_WARNING),
    )
    for name, value in overrides.items():
        setattr(extracted, name, value)
    return extracted


def line(text: str, confidence: float = 0.95, height: float = 16, top: float = 0) -> OcrLine:
    return OcrLine(text=text, confidence=confidence, height=height, top=top)


def bourbon_lines() -> list[OcrLine]:
    return [
        line("Kentucky Straight Bourbon Whiskey", height=22, top=80),
        line("45% Alc./Vol. (90 Proof)", height=18, top=120),
        line("OLD TOM DISTILLERY", height=48, top=10),
        line("750 mL", height=18, top=160),
        line(STATUTORY_WARNING, height=12, top=210),
    ]


WRAPPED_WARNING = [
    "GOVERNMENT WARNING: (1) According to the Surgeon General,",
    "women should not drink alcoholic beverages during pregnancy",
    "because of the risk of birth defects. (2) Consumption of",
    "alcoholic beverages impairs your ability to drive a car or",
    "operate machinery, and may cause health problems.",
]
