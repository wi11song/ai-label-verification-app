"""Compare application values to extracted label fields.

Rules follow SOFTWARE_REQUIREMENTS.md FR-8 through FR-14 and the system design.
Bold on the government warning is checked when OCR kept a prefix box and a body box.
"""

import re
from collections.abc import Callable

from labelcheck.decide import decide
from labelcheck.models import (
    FIELD_LABELS,
    OPTIONAL_FIELDS,
    REQUIRED_FIELDS,
    Application,
    ExtractedField,
    ExtractedLabel,
    FieldResult,
    FieldStatus,
    LabelVerdict,
)
from labelcheck.normalize import (
    collapse_whitespace,
    is_near_miss,
    normalize_bottler,
    normalize_brand,
    normalize_origin,
    normalize_wording,
)
from labelcheck.statute import STATUTORY_WARNING
from labelcheck.thresholds import (
    ABV_TOLERANCE_POINTS,
    HIGH_CONFIDENCE,
    LOW_CONFIDENCE,
    ML_PER_FL_OZ,
    VOLUME_TOLERANCE_RATIO,
)

_PERCENT = re.compile(r"(\d+(?:\.\d+)?)\s*%")
_PROOF = re.compile(r"(\d+(?:\.\d+)?)\s*-?\s*proof\b", re.IGNORECASE)
_VOLUME = re.compile(
    r"(\d+(?:\.\d+)?)\s*(fl\.?\s*oz|ml|l|oz)\b",
    re.IGNORECASE,
)

WARNING_MATCH_REASON = "Warning text matches. Bold was not checked."
WARNING_EMPHASIS_MATCH_REASON = (
    "Warning text matches, and “GOVERNMENT WARNING:” is heavier than the rest of the warning."
)
WARNING_EMPHASIS_MISMATCH_REASON = (
    "The warning text matches, but “GOVERNMENT WARNING:” is not heavier than the rest of the warning."
)
WARNING_EMPHASIS_UNCLEAR_REASON = (
    "The warning text matches, but bold type on “GOVERNMENT WARNING:” could not be judged."
)
WARNING_MISMATCH_REASON = (
    "The warning must start with GOVERNMENT WARNING: in all caps, "
    "and the remaining text must match exactly."
)
WARNING_APPLICATION_MISMATCH_REASON = "The label warning does not match the application."
WARNING_REVIEW_REASON = (
    "The warning does not look exact, and the read is uncertain. A person should check it."
)


def compare_label(
    application: Application,
    extracted: ExtractedLabel | None = None,
    *,
    image_readable: bool = True,
    image_note: str | None = None,
) -> LabelVerdict:
    extracted = extracted or ExtractedLabel()
    fields = [_compare_named(name, application, extracted) for name in REQUIRED_FIELDS]
    for name in OPTIONAL_FIELDS:
        result = _compare_named(name, application, extracted)
        if result is not None:
            fields.append(result)
    return decide(fields, image_readable=image_readable, image_note=image_note)


def _compare_named(name: str, application: Application, extracted: ExtractedLabel) -> FieldResult | None:
    comparators: dict[str, Callable[[str, ExtractedField], FieldResult | None]] = {
        "brand_name": lambda app, ext: _compare_text(
            "brand_name", app, ext, normalize_brand, "Same name after ignoring case."
        ),
        "class_type": lambda app, ext: _compare_text(
            "class_type",
            app,
            ext,
            normalize_wording,
            "Same wording after ignoring case and punctuation.",
        ),
        "alcohol_content": _compare_alcohol,
        "net_contents": _compare_volume,
        "government_warning": _compare_warning,
        "bottler": lambda app, ext: _compare_text(
            "bottler",
            app,
            ext,
            normalize_bottler,
            "Same bottler after ignoring case and punctuation.",
            required=False,
        ),
        "country_of_origin": lambda app, ext: _compare_text(
            "country_of_origin",
            app,
            ext,
            normalize_origin,
            "Same origin after ignoring case and punctuation.",
            required=False,
        ),
    }
    application_value = getattr(application, name)
    if name == "government_warning" and not application_value.strip():
        application_value = STATUTORY_WARNING
    return comparators[name](application_value, getattr(extracted, name))


def _compare_text(
    name: str,
    application: str,
    extracted: ExtractedField,
    normalizer: Callable[[str], str],
    match_reason: str,
    *,
    required: bool = True,
) -> FieldResult | None:
    label = FIELD_LABELS[name]
    app_text = application.strip()
    ext_text = extracted.text.strip()
    normalized_extracted = normalizer(ext_text) if ext_text else ""
    band = _band(extracted.confidence)

    if not app_text and not normalized_extracted:
        if required:
            return _result(
                name,
                application,
                extracted,
                FieldStatus.NEEDS_REVIEW,
                f"Enter {label.lower()} on the application before verifying.",
            )
        return None

    if not normalized_extracted or band in {"none", "low"}:
        return _result(
            name,
            application,
            extracted,
            FieldStatus.UNREADABLE,
            f"{label} could not be read on this label.",
        )

    if extracted.assignment_note:
        return _result(name, application, extracted, FieldStatus.NEEDS_REVIEW, extracted.assignment_note)

    if not app_text:
        return _result(
            name,
            application,
            extracted,
            FieldStatus.NEEDS_REVIEW,
            f"The label shows a {label.lower()}, but the application left it blank.",
        )

    left = normalizer(app_text)
    right = normalized_extracted
    if left == right:
        return _result(name, application, extracted, FieldStatus.MATCH, match_reason)
    if is_near_miss(left, right) or band == "medium":
        reason = (
            "Close, but the wording is not the same. A person should check this."
            if is_near_miss(left, right)
            else "The wording may not match, and the read is uncertain. A person should check this."
        )
        return _result(name, application, extracted, FieldStatus.NEEDS_REVIEW, reason)
    return _result(name, application, extracted, FieldStatus.MISMATCH, "The wording does not match.")


def _compare_alcohol(application: str, extracted: ExtractedField) -> FieldResult:
    return _compare_measured(
        "alcohol_content",
        application,
        extracted,
        _parse_alcohol,
        "The alcohol content matches.",
        "The alcohol content does not match.",
        "The alcohol content may not match, and the read is uncertain. A person should check this.",
        "Alcohol content could not be read on this label.",
        "The label shows a percent and a proof that do not agree. A person should check this.",
        "The application shows a percent and a proof that do not agree.",
        _alcohol_match_reason,
    )


def _compare_volume(application: str, extracted: ExtractedField) -> FieldResult:
    return _compare_measured(
        "net_contents",
        application,
        extracted,
        _parse_volume,
        "The net contents match.",
        "The net contents do not match.",
        "The net contents may not match, and the read is uncertain. A person should check this.",
        "Net contents could not be read on this label.",
        "The label shows volumes that do not agree. A person should check this.",
        "The application shows volumes that do not agree.",
        lambda _app, _ext: "The net contents match.",
    )


def _compare_measured(
    name: str,
    application: str,
    extracted: ExtractedField,
    parse: Callable[[str], tuple[str, object]],
    match_reason: str,
    mismatch_reason: str,
    review_reason: str,
    unreadable_reason: str,
    label_ambiguous_reason: str,
    application_ambiguous_reason: str,
    match_reason_for: Callable[[object, object], str],
) -> FieldResult:
    band = _band(extracted.confidence)
    ext_text = extracted.text.strip()
    if not ext_text or band in {"none", "low"}:
        return _result(name, application, extracted, FieldStatus.UNREADABLE, unreadable_reason)

    ext_status, ext_value = parse(ext_text)
    if ext_status == "ambiguous":
        return _result(name, application, extracted, FieldStatus.NEEDS_REVIEW, label_ambiguous_reason)
    if ext_status != "ok":
        return _result(name, application, extracted, FieldStatus.UNREADABLE, unreadable_reason)
    if extracted.assignment_note:
        return _result(name, application, extracted, FieldStatus.NEEDS_REVIEW, extracted.assignment_note)

    if not application.strip():
        return _result(
            name,
            application,
            extracted,
            FieldStatus.NEEDS_REVIEW,
            f"Enter {FIELD_LABELS[name].lower()} on the application before verifying.",
        )

    app_status, app_value = parse(application)
    if app_status == "ambiguous":
        return _result(
            name, application, extracted, FieldStatus.NEEDS_REVIEW, application_ambiguous_reason
        )
    if app_status != "ok":
        return _result(
            name,
            application,
            extracted,
            FieldStatus.NEEDS_REVIEW,
            f"{FIELD_LABELS[name]} on the application is not a number this check understands.",
        )

    if _measurements_match(name, app_value, ext_value):
        return _result(
            name,
            application,
            extracted,
            FieldStatus.MATCH,
            match_reason_for(app_value, ext_value) if name == "alcohol_content" else match_reason,
        )
    if band == "high":
        return _result(name, application, extracted, FieldStatus.MISMATCH, mismatch_reason)
    return _result(name, application, extracted, FieldStatus.NEEDS_REVIEW, review_reason)


def _compare_warning(application: str, extracted: ExtractedField) -> FieldResult:
    shown_application = application.strip() or STATUTORY_WARNING
    band = _band(extracted.confidence)
    ext_text = extracted.text.strip()
    if not ext_text or band in {"none", "low"}:
        return _result(
            "government_warning",
            shown_application,
            extracted,
            FieldStatus.UNREADABLE,
            "The government warning could not be read on this label.",
            emphasis="not_checked",
        )
    if extracted.assignment_note:
        return _result(
            "government_warning",
            shown_application,
            extracted,
            FieldStatus.NEEDS_REVIEW,
            extracted.assignment_note,
            emphasis="not_checked",
        )

    label_ok = collapse_whitespace(ext_text) == STATUTORY_WARNING
    application_ok = collapse_whitespace(ext_text) == collapse_whitespace(shown_application)
    recorded = _recorded_emphasis(ext_text, extracted.emphasis)
    if label_ok and application_ok:
        return _matched_warning(shown_application, extracted, recorded)
    if band == "medium":
        return _result(
            "government_warning",
            shown_application,
            extracted,
            FieldStatus.NEEDS_REVIEW,
            WARNING_REVIEW_REASON,
            emphasis=recorded,
        )
    reason = WARNING_MISMATCH_REASON if not label_ok else WARNING_APPLICATION_MISMATCH_REASON
    return _result(
        "government_warning",
        shown_application,
        extracted,
        FieldStatus.MISMATCH,
        reason,
        emphasis=recorded,
    )


def _matched_warning(application: str, extracted: ExtractedField, recorded: str) -> FieldResult:
    if recorded == "mismatch":
        return _result(
            "government_warning",
            application,
            extracted,
            FieldStatus.MISMATCH,
            WARNING_EMPHASIS_MISMATCH_REASON,
            emphasis="mismatch",
        )
    if recorded == "inconclusive":
        return _result(
            "government_warning",
            application,
            extracted,
            FieldStatus.NEEDS_REVIEW,
            WARNING_EMPHASIS_UNCLEAR_REASON,
            emphasis="inconclusive",
        )
    if recorded == "match":
        return _result(
            "government_warning",
            application,
            extracted,
            FieldStatus.MATCH,
            WARNING_EMPHASIS_MATCH_REASON,
            emphasis="match",
        )
    return _result(
        "government_warning",
        application,
        extracted,
        FieldStatus.MATCH,
        WARNING_MATCH_REASON,
        emphasis="not_checked",
    )


def _recorded_emphasis(text: str, measured: str | None) -> str:
    """A lowercased prefix is inconclusive, so emphasis alone does not fail the label."""
    if measured not in {"match", "mismatch", "inconclusive"}:
        return "not_checked"
    if not collapse_whitespace(text).startswith("GOVERNMENT WARNING:"):
        return "inconclusive"
    return measured


def _result(
    name: str,
    application: str,
    extracted: ExtractedField,
    status: FieldStatus,
    reason: str,
    *,
    emphasis: str | None = None,
) -> FieldResult:
    return FieldResult(
        name=name,
        application=application,
        extracted=extracted.text,
        status=status,
        confidence=extracted.confidence,
        reason=reason,
        emphasis=emphasis,
    )


def _band(confidence: float | None) -> str:
    if confidence is None:
        return "none"
    if confidence >= HIGH_CONFIDENCE:
        return "high"
    if confidence >= LOW_CONFIDENCE:
        return "medium"
    return "low"


def _measurements_match(name: str, application: object, extracted: object) -> bool:
    if name == "alcohol_content":
        return abs(application.abv - extracted.abv) <= ABV_TOLERANCE_POINTS  # type: ignore[attr-defined]
    return _volumes_close(application.milliliters, extracted.milliliters)  # type: ignore[attr-defined]


class _Alcohol:
    def __init__(self, abv: float, used_proof: bool) -> None:
        self.abv = abv
        self.used_proof = used_proof


class _Volume:
    def __init__(self, milliliters: float) -> None:
        self.milliliters = milliliters


def _parse_alcohol(value: str) -> tuple[str, _Alcohol | None]:
    percents = [float(item) for item in _PERCENT.findall(value)]
    proofs = [float(item) for item in _PROOF.findall(value)]
    if len(percents) > 1 and not _numbers_close(percents):
        return "ambiguous", None
    if len(proofs) > 1 and not _numbers_close(proofs):
        return "ambiguous", None
    percent = percents[0] if percents else None
    proof = proofs[0] if proofs else None
    if percent is None and proof is None:
        return "unparseable", None
    if percent is not None and proof is not None:
        if abs(percent - proof / 2) > ABV_TOLERANCE_POINTS:
            return "ambiguous", None
        return "ok", _Alcohol(percent, used_proof=False)
    if percent is not None:
        return "ok", _Alcohol(percent, used_proof=False)
    return "ok", _Alcohol(proof / 2, used_proof=True)  # type: ignore[operator]


def _parse_volume(value: str) -> tuple[str, _Volume | None]:
    readings = []
    for amount, unit in _VOLUME.findall(value):
        readings.append(_to_milliliters(float(amount), unit))
    if not readings:
        return "unparseable", None
    if any(not _volumes_close(readings[0], item) for item in readings[1:]):
        return "ambiguous", None
    return "ok", _Volume(readings[0])


def _to_milliliters(amount: float, unit: str) -> float:
    normalized = re.sub(r"[\s.]", "", unit.lower())
    if normalized == "ml":
        return amount
    if normalized == "l":
        return amount * 1000
    if normalized in {"floz", "oz"}:
        return amount * ML_PER_FL_OZ
    raise ValueError(f"Unsupported volume unit: {unit}")


def _alcohol_match_reason(application: object, extracted: object) -> str:
    if application.used_proof != extracted.used_proof:  # type: ignore[attr-defined]
        return "The alcohol content matches after converting proof to percent (proof is twice the percent)."
    return "The alcohol content matches."


def _numbers_close(values: list[float]) -> bool:
    return all(abs(values[0] - item) <= ABV_TOLERANCE_POINTS for item in values[1:])


def _volumes_close(left: float, right: float) -> bool:
    baseline = max(abs(left), abs(right), 1)
    return abs(left - right) / baseline <= VOLUME_TOLERANCE_RATIO
