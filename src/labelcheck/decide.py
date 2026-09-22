"""Turn per-field statuses into Pass, Fail, or Needs review."""

from labelcheck.models import (
    FIELD_LABELS,
    REQUIRED_FIELDS,
    FieldResult,
    FieldStatus,
    LabelVerdict,
    OverallStatus,
)
from labelcheck.quality import UNREADABLE_IMAGE_SUMMARY

UNREADABLE_IMAGE_FIELD_REASON = "Not read because the image is unusable."


def decide(
    fields: list[FieldResult],
    *,
    image_readable: bool = True,
    image_note: str | None = None,
) -> LabelVerdict:
    """A confident mismatch outranks an unreadable field. An unusable image outranks both."""
    if not image_readable:
        note = image_note or UNREADABLE_IMAGE_SUMMARY
        return LabelVerdict(
            overall=OverallStatus.NEEDS_REVIEW,
            summary=note,
            fields=[_unreadable_field(item) for item in fields],
        )
    if any(item.status is FieldStatus.MISMATCH for item in fields):
        return LabelVerdict(OverallStatus.FAIL, _fail_summary(fields), fields)
    if any(item.status in {FieldStatus.UNREADABLE, FieldStatus.NEEDS_REVIEW} for item in fields):
        return LabelVerdict(OverallStatus.NEEDS_REVIEW, _review_summary(fields), fields)
    return LabelVerdict(OverallStatus.PASS, _pass_summary(fields), fields)


def _unreadable_field(item: FieldResult) -> FieldResult:
    return FieldResult(
        name=item.name,
        application=item.application,
        extracted="",
        status=FieldStatus.UNREADABLE,
        confidence=None,
        reason=UNREADABLE_IMAGE_FIELD_REASON,
        emphasis=item.emphasis,
    )


def _pass_summary(fields: list[FieldResult]) -> str:
    required = [item for item in fields if item.name in REQUIRED_FIELDS]
    matched = sum(1 for item in required if item.status is FieldStatus.MATCH)
    total = len(required)
    return f"{matched} of {total} required fields match."


def _fail_summary(fields: list[FieldResult]) -> str:
    labels = _labels(fields, FieldStatus.MISMATCH)
    if len(labels) == 1:
        return f"{labels[0]} does not match."
    return f"{_join(labels)} do not match."


def _review_summary(fields: list[FieldResult]) -> str:
    unreadable = _labels(fields, FieldStatus.UNREADABLE)
    uncertain = _labels(fields, FieldStatus.NEEDS_REVIEW)
    others_match = all(
        item.status is FieldStatus.MATCH
        for item in fields
        if item.status not in {FieldStatus.UNREADABLE, FieldStatus.NEEDS_REVIEW}
    )
    if unreadable and not uncertain:
        if len(unreadable) == 1 and others_match:
            return f"{unreadable[0]} could not be read. The other fields match."
        return f"{_join(unreadable)} could not be read."
    if uncertain and not unreadable:
        if len(uncertain) == 1 and others_match:
            return f"{uncertain[0]} needs a person to check it. The other fields match."
        return f"{_join(uncertain)} need a person to check them."
    return "A person should check this label. Some fields could not be read or are uncertain."


def _labels(fields: list[FieldResult], status: FieldStatus) -> list[str]:
    return [FIELD_LABELS[item.name] for item in fields if item.status is status]


def _join(labels: list[str]) -> str:
    if len(labels) == 1:
        return labels[0]
    if len(labels) == 2:
        return f"{labels[0]} and {labels[1]}"
    return ", ".join(labels[:-1]) + f", and {labels[-1]}"
