"""OCR lines become fields, then the comparison rules run. No OCR model."""

from labelcheck.compare import compare_label
from labelcheck.models import FieldStatus, OverallStatus
from labelcheck.parse import parse_lines
from labelcheck.statute import STATUTORY_WARNING

from fixtures import WRAPPED_WARNING, bourbon_application, bourbon_lines, line


def _item(verdict, name):
    return next(item for item in verdict.fields if item.name == name)


def test_bourbon_lines_parse_and_pass():
    extracted = parse_lines(bourbon_lines())
    verdict = compare_label(bourbon_application(), extracted)

    assert extracted.brand_name.text == "OLD TOM DISTILLERY"
    assert extracted.class_type.text == "Kentucky Straight Bourbon Whiskey"
    assert extracted.alcohol_content.text == "45% Alc./Vol. (90 Proof)"
    assert extracted.net_contents.text == "750 mL"
    assert extracted.government_warning.text == STATUTORY_WARNING
    assert verdict.overall is OverallStatus.PASS


def test_wrapped_warning_is_joined_and_not_used_as_the_brand():
    lines = [
        line("OLD TOM DISTILLERY", height=48, top=10),
        line("Kentucky Straight Bourbon Whiskey", height=22, top=70),
        line("45% Alc./Vol. (90 Proof)"),
        line("750 mL"),
        *[line(text, height=12, top=200 + index) for index, text in enumerate(WRAPPED_WARNING)],
    ]
    extracted = parse_lines(lines)
    verdict = compare_label(bourbon_application(), extracted)

    assert extracted.brand_name.text == "OLD TOM DISTILLERY"
    assert _item(verdict, "government_warning").status is FieldStatus.MATCH
    assert verdict.overall is OverallStatus.PASS


def test_brand_line_matches_after_case_normalization():
    lines = bourbon_lines()
    lines = [line("STONE'S THROW", height=48, top=10) if item.text == "OLD TOM DISTILLERY" else item for item in lines]
    verdict = compare_label(bourbon_application(brand_name="Stone's Throw"), parse_lines(lines))

    assert _item(verdict, "brand_name").status is FieldStatus.MATCH
    assert verdict.overall is OverallStatus.PASS


def test_a_second_tall_line_makes_the_brand_need_review():
    lines = bourbon_lines() + [line("DISTILLED 2020", height=44, top=50)]
    verdict = compare_label(bourbon_application(), parse_lines(lines))

    brand = _item(verdict, "brand_name")
    assert brand.status is FieldStatus.NEEDS_REVIEW
    assert brand.extracted == "OLD TOM DISTILLERY"
    assert verdict.overall is OverallStatus.NEEDS_REVIEW


def test_a_clearly_shorter_line_does_not_compete_with_the_brand():
    lines = bourbon_lines() + [line("EST. 1920", height=12, top=180)]
    verdict = compare_label(bourbon_application(), parse_lines(lines))

    assert _item(verdict, "brand_name").status is FieldStatus.MATCH
    assert verdict.overall is OverallStatus.PASS


def test_two_alcohol_lines_need_review_instead_of_a_silent_choice():
    lines = bourbon_lines() + [line("40% Alc./Vol.")]
    verdict = compare_label(bourbon_application(), parse_lines(lines))

    alcohol = _item(verdict, "alcohol_content")
    assert alcohol.status is FieldStatus.NEEDS_REVIEW
    assert alcohol.extracted == "45% Alc./Vol. (90 Proof)"
    assert verdict.overall is OverallStatus.NEEDS_REVIEW


def test_missing_alcohol_line_is_unreadable_and_not_a_match():
    lines = [item for item in bourbon_lines() if "%" not in item.text]
    verdict = compare_label(bourbon_application(), parse_lines(lines))

    assert _item(verdict, "alcohol_content").status is FieldStatus.UNREADABLE
    assert verdict.overall is OverallStatus.NEEDS_REVIEW


def test_bottler_and_origin_lines_are_assigned():
    lines = bourbon_lines() + [
        line("Bottled by Old Tom Distillery, Frankfort, KY"),
        line("Product of Scotland"),
    ]
    verdict = compare_label(
        bourbon_application(
            bottler="Old Tom Distillery, Frankfort, KY",
            country_of_origin="Scotland",
        ),
        parse_lines(lines),
    )

    assert _item(verdict, "bottler").status is FieldStatus.MATCH
    assert _item(verdict, "country_of_origin").status is FieldStatus.MATCH
    assert verdict.overall is OverallStatus.PASS


def test_title_case_warning_line_is_still_captured_and_fails():
    title_case = STATUTORY_WARNING.replace("GOVERNMENT WARNING:", "Government Warning:", 1)
    lines = [line(title_case) if item.text == STATUTORY_WARNING else item for item in bourbon_lines()]
    verdict = compare_label(bourbon_application(), parse_lines(lines))

    warning = _item(verdict, "government_warning")
    assert warning.extracted.startswith("Government Warning:")
    assert warning.status is FieldStatus.MISMATCH
    assert verdict.overall is OverallStatus.FAIL
