"""Field and label verdicts shared by the checker and, later, the API."""

from dataclasses import dataclass, field
from enum import Enum


class FieldStatus(str, Enum):
    MATCH = "match"
    MISMATCH = "mismatch"
    UNREADABLE = "unreadable"
    NEEDS_REVIEW = "needs_review"


class OverallStatus(str, Enum):
    PASS = "pass"
    FAIL = "fail"
    NEEDS_REVIEW = "needs_review"


FIELD_LABELS = {
    "brand_name": "Brand name",
    "class_type": "Class/type",
    "alcohol_content": "Alcohol content",
    "net_contents": "Net contents",
    "government_warning": "Government warning",
    "bottler": "Bottler",
    "country_of_origin": "Country of origin",
}

REQUIRED_FIELDS = (
    "brand_name",
    "class_type",
    "alcohol_content",
    "net_contents",
    "government_warning",
)

OPTIONAL_FIELDS = (
    "bottler",
    "country_of_origin",
)


@dataclass
class Application:
    brand_name: str
    class_type: str
    alcohol_content: str
    net_contents: str
    government_warning: str = ""
    bottler: str = ""
    country_of_origin: str = ""


@dataclass
class ExtractedField:
    text: str = ""
    confidence: float | None = None
    # Set when two OCR lines could fill this field. Comparison then stays Needs review.
    assignment_note: str | None = None
    # Warning only: match, mismatch, or inconclusive. None means bold was not checked.
    emphasis: str | None = None


@dataclass
class ExtractedLabel:
    brand_name: ExtractedField = field(default_factory=ExtractedField)
    class_type: ExtractedField = field(default_factory=ExtractedField)
    alcohol_content: ExtractedField = field(default_factory=ExtractedField)
    net_contents: ExtractedField = field(default_factory=ExtractedField)
    government_warning: ExtractedField = field(default_factory=ExtractedField)
    bottler: ExtractedField = field(default_factory=ExtractedField)
    country_of_origin: ExtractedField = field(default_factory=ExtractedField)


@dataclass
class FieldResult:
    name: str
    application: str
    extracted: str
    status: FieldStatus
    confidence: float | None
    reason: str
    emphasis: str | None = None


@dataclass
class LabelVerdict:
    overall: OverallStatus
    summary: str
    fields: list[FieldResult]

    def to_dict(self) -> dict:
        fields = []
        for item in self.fields:
            payload = {
                "name": item.name,
                "application": item.application,
                "extracted": item.extracted,
                "status": item.status.value,
                "confidence": item.confidence,
                "reason": item.reason,
            }
            if item.emphasis is not None:
                payload["emphasis"] = item.emphasis
            fields.append(payload)
        return {
            "overall": self.overall.value,
            "summary": self.summary,
            "fields": fields,
        }
