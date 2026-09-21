"""Assign OCR lines to label fields.

Lines are claimed in the order from the system design. A claimed line is removed
from the pool so the brand step cannot swallow the warning or the measurements.
"""

import re
from dataclasses import dataclass

from labelcheck.models import ExtractedField, ExtractedLabel
from labelcheck.normalize import collapse_whitespace
from labelcheck.thresholds import BRAND_HEIGHT_RATIO

_PERCENT = re.compile(r"(\d+(?:\.\d+)?)\s*%")
_PROOF = re.compile(r"(\d+(?:\.\d+)?)\s*-?\s*proof\b", re.IGNORECASE)
_VOLUME = re.compile(r"(\d+(?:\.\d+)?)\s*(fl\.?\s*oz|ml|l|oz)\b", re.IGNORECASE)
_ORIGIN = re.compile(r"\b(product of|produced in|made in|imported from)\b", re.IGNORECASE)
_BOTTLER = re.compile(
    r"\b(produced and bottled by|bottled by|distilled by|produced by|imported by)\b",
    re.IGNORECASE,
)
_CLASS_WORD = re.compile(
    r"\b(bourbons?|whisk(?:ey|ies|ys?)|vodkas?|gins?|rums?|tequilas?|brand(?:y|ies)|"
    r"wines?|beers?|ales?|lagers?|stouts?|porters?|ryes?|mezcals?|cognacs?|liqueurs?|ciders?)\b",
    re.IGNORECASE,
)

_NOTES = {
    "alcohol_content": "More than one line could be the alcohol content. A person should check this.",
    "net_contents": "More than one line could be the net contents. A person should check this.",
    "country_of_origin": "More than one line could be the country of origin. A person should check this.",
    "bottler": "More than one line could be the bottler. A person should check this.",
    "class_type": "More than one line could be the class/type. A person should check this.",
    "government_warning": "More than one government warning was found. A person should check this.",
    "brand_name": "Two lines could be the brand name. A person should check this.",
}


@dataclass(frozen=True)
class OcrLine:
    text: str
    confidence: float
    height: float = 0
    top: float = 0


def parse_lines(lines: list[OcrLine]) -> ExtractedLabel:
    pool = [line for line in lines if line.text and line.text.strip()]
    extracted = ExtractedLabel()

    warning, pool = _claim_warning(pool)
    warning_note = None
    if any(_is_warning(line.text) for line in pool):
        warning_note = _NOTES["government_warning"]
        pool = [line for line in pool if not _is_warning(line.text)]
    if warning:
        extracted.government_warning = _as_field(warning, warning_note)

    extracted.alcohol_content, pool = _claim_matches(pool, _is_alcohol, "alcohol_content")
    extracted.net_contents, pool = _claim_matches(pool, _is_volume, "net_contents")
    extracted.country_of_origin, pool = _claim_matches(pool, _is_origin, "country_of_origin")
    extracted.bottler, pool = _claim_matches(pool, _is_bottler, "bottler")
    extracted.class_type, pool = _claim_matches(pool, _is_class, "class_type")
    extracted.brand_name = _claim_brand(pool)
    return extracted


def _claim_warning(pool: list[OcrLine]) -> tuple[list[OcrLine], list[OcrLine]]:
    start = next((index for index, line in enumerate(pool) if _is_warning(line.text)), None)
    if start is None:
        return [], pool
    taken = [pool[start]]
    joined = pool[start].text
    end = start
    if not _warning_complete(joined):
        for index in range(start + 1, len(pool)):
            candidate = pool[index]
            if _is_non_warning_anchor(candidate.text):
                break
            taken.append(candidate)
            end = index
            joined = f"{joined} {candidate.text}"
            if _warning_complete(joined):
                break
    remaining = [line for index, line in enumerate(pool) if index < start or index > end]
    return taken, remaining


def _claim_matches(pool: list[OcrLine], predicate, note_key: str) -> tuple[ExtractedField, list[OcrLine]]:
    matched = [line for line in pool if predicate(line.text)]
    if not matched:
        return ExtractedField(), pool
    note = _NOTES[note_key] if len(matched) > 1 else None
    remaining = [line for line in pool if not predicate(line.text)]
    return _as_field(matched[:1], note), remaining


def _claim_brand(pool: list[OcrLine]) -> ExtractedField:
    if not pool:
        return ExtractedField()
    ranked = sorted(enumerate(pool), key=lambda item: (-item[1].height, item[1].top, item[0]))
    chosen = ranked[0][1]
    ambiguous = len(ranked) > 1 and ranked[1][1].height >= chosen.height * BRAND_HEIGHT_RATIO
    note = _NOTES["brand_name"] if ambiguous else None
    return _as_field([chosen], note)


def _as_field(lines: list[OcrLine], note: str | None) -> ExtractedField:
    return ExtractedField(
        text="\n".join(line.text.strip() for line in lines),
        confidence=min(line.confidence for line in lines),
        assignment_note=note,
    )


def _is_warning(text: str) -> bool:
    return "government warning" in text.casefold()


def _warning_complete(text: str) -> bool:
    folded = collapse_whitespace(text).casefold()
    return "(2)" in folded and "health problems" in folded


def _is_alcohol(text: str) -> bool:
    return _PERCENT.search(text) is not None or _PROOF.search(text) is not None


def _is_volume(text: str) -> bool:
    return _VOLUME.search(text) is not None


def _is_origin(text: str) -> bool:
    return _ORIGIN.search(text) is not None


def _is_bottler(text: str) -> bool:
    return _BOTTLER.search(text) is not None


def _is_class(text: str) -> bool:
    return _CLASS_WORD.search(text) is not None


def _is_non_warning_anchor(text: str) -> bool:
    return (
        _is_alcohol(text)
        or _is_volume(text)
        or _is_origin(text)
        or _is_bottler(text)
        or _is_class(text)
    )
