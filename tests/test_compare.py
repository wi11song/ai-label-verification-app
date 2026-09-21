"""Comparison rules from FR-8 through FR-14. These tests do not run OCR."""

from labelcheck.compare import compare_label
from labelcheck.decide import UNREADABLE_IMAGE_SUMMARY
from labelcheck.models import FieldStatus, OverallStatus
from labelcheck.statute import STATUTORY_WARNING

from fixtures import bourbon_application, bourbon_extracted, field


def _item(verdict, name):
    return next(item for item in verdict.fields if item.name == name)


def test_bourbon_sample_passes():
    verdict = compare_label(bourbon_application(), bourbon_extracted())

    assert verdict.overall is OverallStatus.PASS
    assert verdict.summary == "All checked fields match."
    assert {item.status for item in verdict.fields} == {FieldStatus.MATCH}
    warning = _item(verdict, "government_warning")
    assert warning.emphasis == "not_checked"
    assert warning.reason == "Warning text matches. Bold was not checked."


def test_result_lists_application_extracted_status_and_reason():
    payload = compare_label(bourbon_application(), bourbon_extracted()).to_dict()

    assert payload["overall"] == "pass"
    brand = next(item for item in payload["fields"] if item["name"] == "brand_name")
    assert set(brand) == {"name", "application", "extracted", "status", "confidence", "reason"}


def test_brand_ignores_case_apostrophe_style_and_trademark():
    verdict = compare_label(
        bourbon_application(brand_name="Stone's Throw"),
        bourbon_extracted(brand_name=field("STONE’S THROW®")),
    )

    brand = _item(verdict, "brand_name")
    assert brand.status is FieldStatus.MATCH
    assert brand.reason == "Same name after ignoring case."


def test_missing_apostrophe_is_needs_review_not_a_match():
    verdict = compare_label(
        bourbon_application(brand_name="Stone's Throw"),
        bourbon_extracted(brand_name=field("Stones Throw")),
    )

    assert _item(verdict, "brand_name").status is FieldStatus.NEEDS_REVIEW
    assert verdict.overall is OverallStatus.NEEDS_REVIEW
    assert verdict.summary == "Brand name needs a person to check it. The other fields match."


def test_different_brand_wording_fails_only_when_the_read_is_confident():
    confident = compare_label(
        bourbon_application(brand_name="Stone's Throw"),
        bourbon_extracted(brand_name=field("River's Edge", 0.95)),
    )
    uncertain = compare_label(
        bourbon_application(brand_name="Stone's Throw"),
        bourbon_extracted(brand_name=field("River's Edge", 0.70)),
    )

    assert _item(confident, "brand_name").status is FieldStatus.MISMATCH
    assert confident.overall is OverallStatus.FAIL
    assert confident.summary == "Brand name does not match."
    assert _item(uncertain, "brand_name").status is FieldStatus.NEEDS_REVIEW
    assert uncertain.overall is OverallStatus.NEEDS_REVIEW


def test_low_confidence_text_is_unreadable_even_when_it_matches():
    verdict = compare_label(
        bourbon_application(),
        bourbon_extracted(brand_name=field("OLD TOM DISTILLERY", 0.59)),
    )

    assert _item(verdict, "brand_name").status is FieldStatus.UNREADABLE
    assert verdict.overall is OverallStatus.NEEDS_REVIEW


def test_confidence_boundaries():
    match_at_medium = compare_label(
        bourbon_application(),
        bourbon_extracted(brand_name=field("OLD TOM DISTILLERY", 0.60)),
    )
    mismatch_at_high = compare_label(
        bourbon_application(brand_name="Stone's Throw"),
        bourbon_extracted(brand_name=field("River's Edge", 0.85)),
    )
    review_just_below_high = compare_label(
        bourbon_application(brand_name="Stone's Throw"),
        bourbon_extracted(brand_name=field("River's Edge", 0.849)),
    )

    assert _item(match_at_medium, "brand_name").status is FieldStatus.MATCH
    assert _item(mismatch_at_high, "brand_name").status is FieldStatus.MISMATCH
    assert _item(review_just_below_high, "brand_name").status is FieldStatus.NEEDS_REVIEW


def test_one_character_class_slip_is_review_not_a_fail():
    verdict = compare_label(
        bourbon_application(),
        bourbon_extracted(class_type=field("Kentucky Straight Bourbon Whisky")),
    )

    assert _item(verdict, "class_type").status is FieldStatus.NEEDS_REVIEW
    assert verdict.overall is OverallStatus.NEEDS_REVIEW


def test_alcohol_matches_percent_and_proof():
    percent = compare_label(bourbon_application(alcohol_content="45%"), bourbon_extracted())
    proof = compare_label(bourbon_application(alcohol_content="90 proof"), bourbon_extracted())

    assert _item(percent, "alcohol_content").status is FieldStatus.MATCH
    assert _item(proof, "alcohol_content").reason == (
        "The alcohol content matches after converting proof to percent (proof is twice the percent)."
    )


def test_confident_alcohol_mismatch_fails_and_uncertain_mismatch_does_not():
    confident = compare_label(
        bourbon_application(alcohol_content="40%"),
        bourbon_extracted(),
    )
    uncertain = compare_label(
        bourbon_application(alcohol_content="40%"),
        bourbon_extracted(alcohol_content=field("45% Alc./Vol. (90 Proof)", 0.70)),
    )

    assert _item(confident, "alcohol_content").status is FieldStatus.MISMATCH
    assert confident.overall is OverallStatus.FAIL
    assert _item(uncertain, "alcohol_content").status is FieldStatus.NEEDS_REVIEW
    assert uncertain.overall is OverallStatus.NEEDS_REVIEW


def test_label_percent_and_proof_that_disagree_need_review():
    verdict = compare_label(
        bourbon_application(),
        bourbon_extracted(alcohol_content=field("45% Alc./Vol. (80 Proof)")),
    )

    assert _item(verdict, "alcohol_content").status is FieldStatus.NEEDS_REVIEW
    assert verdict.overall is OverallStatus.NEEDS_REVIEW


def test_unparseable_alcohol_is_unreadable():
    verdict = compare_label(
        bourbon_application(),
        bourbon_extracted(alcohol_content=field("see bottle")),
    )

    assert _item(verdict, "alcohol_content").status is FieldStatus.UNREADABLE
    assert verdict.summary == "Alcohol content could not be read. The other fields match."


def test_net_contents_units_match_and_a_real_difference_fails():
    liters = compare_label(bourbon_application(net_contents="0.75 L"), bourbon_extracted())
    ounces = compare_label(bourbon_application(net_contents="25.4 fl oz"), bourbon_extracted())
    different = compare_label(bourbon_application(net_contents="1 L"), bourbon_extracted())

    assert _item(liters, "net_contents").status is FieldStatus.MATCH
    assert _item(ounces, "net_contents").status is FieldStatus.MATCH
    assert _item(different, "net_contents").status is FieldStatus.MISMATCH
    assert different.overall is OverallStatus.FAIL


def test_title_case_warning_fails_when_confident_and_is_review_when_not():
    title_case = STATUTORY_WARNING.replace("GOVERNMENT WARNING:", "Government Warning:", 1)
    confident = compare_label(
        bourbon_application(),
        bourbon_extracted(government_warning=field(title_case, 0.95)),
    )
    uncertain = compare_label(
        bourbon_application(),
        bourbon_extracted(government_warning=field(title_case, 0.70)),
    )

    assert _item(confident, "government_warning").status is FieldStatus.MISMATCH
    assert confident.overall is OverallStatus.FAIL
    assert _item(uncertain, "government_warning").status is FieldStatus.NEEDS_REVIEW
    assert uncertain.overall is OverallStatus.NEEDS_REVIEW


def test_wrapped_warning_matches_and_reworded_warning_fails():
    wrapped = (
        "GOVERNMENT WARNING: (1) According to the Surgeon General,\n"
        "women should not drink alcoholic beverages during pregnancy "
        "because of the risk of birth defects. (2) Consumption of\n"
        "alcoholic beverages impairs your ability to drive a car or "
        "operate machinery, and may cause health problems."
    )
    reworded = STATUTORY_WARNING.replace("birth defects", "birth defect")
    matched = compare_label(
        bourbon_application(),
        bourbon_extracted(government_warning=field(wrapped)),
    )
    failed = compare_label(
        bourbon_application(),
        bourbon_extracted(government_warning=field(reworded)),
    )

    assert _item(matched, "government_warning").status is FieldStatus.MATCH
    assert matched.overall is OverallStatus.PASS
    assert _item(failed, "government_warning").status is FieldStatus.MISMATCH


def test_label_that_matches_a_nonstatutory_application_warning_still_fails():
    custom = "GOVERNMENT WARNING: Drink responsibly."
    verdict = compare_label(
        bourbon_application(government_warning=custom),
        bourbon_extracted(government_warning=field(custom)),
    )

    assert _item(verdict, "government_warning").status is FieldStatus.MISMATCH
    assert verdict.overall is OverallStatus.FAIL


def test_confident_mismatch_outranks_an_unreadable_field():
    verdict = compare_label(
        bourbon_application(brand_name="Stone's Throw"),
        bourbon_extracted(
            brand_name=field("River's Edge"),
            alcohol_content=field(""),
        ),
    )

    assert verdict.overall is OverallStatus.FAIL
    assert _item(verdict, "brand_name").status is FieldStatus.MISMATCH
    assert _item(verdict, "alcohol_content").status is FieldStatus.UNREADABLE


def test_unreadable_image_is_needs_review_and_marks_no_field_as_a_match():
    verdict = compare_label(bourbon_application(), bourbon_extracted(), image_readable=False)

    assert verdict.overall is OverallStatus.NEEDS_REVIEW
    assert verdict.summary == UNREADABLE_IMAGE_SUMMARY
    assert {item.status for item in verdict.fields} == {FieldStatus.UNREADABLE}
    assert all(item.extracted == "" for item in verdict.fields)


def test_optional_bottler_and_origin_are_skipped_when_absent_and_compared_when_present():
    absent = compare_label(bourbon_application(), bourbon_extracted())
    present = compare_label(
        bourbon_application(
            bottler="Old Tom Distillery, Frankfort, KY",
            country_of_origin="Scotland",
        ),
        bourbon_extracted(
            bottler=field("Bottled by Old Tom Distillery, Frankfort, KY"),
            country_of_origin=field("Product of Scotland"),
        ),
    )

    assert all(item.name not in {"bottler", "country_of_origin"} for item in absent.fields)
    assert absent.overall is OverallStatus.PASS
    assert _item(present, "bottler").status is FieldStatus.MATCH
    assert _item(present, "country_of_origin").status is FieldStatus.MATCH
    assert present.overall is OverallStatus.PASS
