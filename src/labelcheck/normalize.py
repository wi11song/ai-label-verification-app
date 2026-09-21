"""Text normalization for non-warning fields.

Brand comparison keeps apostrophes, so a missing apostrophe stays a near miss.
Class, bottler, and origin drop punctuation. The warning does not use this module.
"""

import re
import unicodedata

from labelcheck.thresholds import NEAR_MISS_MAX_DISTANCE, NEAR_MISS_MIN_SIMILARITY

_APOSTROPHES = str.maketrans(
    {
        "\u2018": "'",
        "\u2019": "'",
        "\u201b": "'",
        "\u2032": "'",
        "\u02bc": "'",
        "\u00b4": "'",
        "`": "'",
    }
)

_HYPHENS = str.maketrans(
    {
        "\u2010": "-",
        "\u2011": "-",
        "\u2012": "-",
        "\u2013": "-",
        "\u2014": "-",
        "\u2212": "-",
    }
)

_ZERO_WIDTH = frozenset("\u200b\u200c\u200d\ufeff")

_ORIGIN_PREFIXES = ("product of ", "produced in ", "made in ", "imported from ")
_BOTTLER_PREFIXES = (
    "produced and bottled by ",
    "bottled by ",
    "distilled by ",
    "produced by ",
    "imported by ",
)


def normalize_brand(value: str) -> str:
    text = _fold(value)
    kept = [character for character in text if character.isalnum() or character in {"'", "-", " "}]
    return _collapse("".join(kept))


def normalize_wording(value: str) -> str:
    text = _fold(value)
    kept = [character if character.isalnum() or character.isspace() else " " for character in text]
    return _collapse("".join(kept))


def normalize_origin(value: str) -> str:
    """Drop a leading origin phrase so the country itself is what gets compared."""
    return _strip_prefix(normalize_wording(value), _ORIGIN_PREFIXES)


def normalize_bottler(value: str) -> str:
    """Drop a leading bottler phrase so the name and address are what get compared."""
    return _strip_prefix(normalize_wording(value), _BOTTLER_PREFIXES)


def collapse_whitespace(value: str) -> str:
    """Join wrapped lines. Case and punctuation stay, for the government warning."""
    return _collapse(value.replace("\u00a0", " "))


def is_near_miss(left: str, right: str) -> bool:
    if left == right:
        return False
    distance = levenshtein(left, right)
    if distance <= NEAR_MISS_MAX_DISTANCE:
        return True
    longest = max(len(left), len(right))
    if longest == 0:
        return False
    return (1 - distance / longest) >= NEAR_MISS_MIN_SIMILARITY


def levenshtein(left: str, right: str) -> int:
    if left == right:
        return 0
    if not left:
        return len(right)
    if not right:
        return len(left)
    previous = list(range(len(right) + 1))
    for i, left_char in enumerate(left, start=1):
        current = [i]
        for j, right_char in enumerate(right, start=1):
            insert_cost = current[j - 1] + 1
            delete_cost = previous[j] + 1
            replace_cost = previous[j - 1] + (left_char != right_char)
            current.append(min(insert_cost, delete_cost, replace_cost))
        previous = current
    return previous[-1]


def _fold(value: str) -> str:
    text = unicodedata.normalize("NFKC", value).casefold()
    text = text.translate(_APOSTROPHES).translate(_HYPHENS)
    return "".join(character for character in text if character not in _ZERO_WIDTH)


def _collapse(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _strip_prefix(text: str, prefixes: tuple[str, ...]) -> str:
    for prefix in prefixes:
        if text.startswith(prefix):
            return text[len(prefix) :].strip()
    return text
