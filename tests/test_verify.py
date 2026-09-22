"""Gate, then OCR, then comparison. These tests use a stand-in reader, not the model."""

import logging
from io import BytesIO

import pytest
from PIL import Image, ImageDraw, ImageFilter

from labelcheck.models import FieldStatus, OverallStatus
from labelcheck.quality import (
    IMAGE_TOO_LARGE,
    UNREADABLE_IMAGE_SUMMARY,
    UNSUPPORTED_IMAGE,
)
from labelcheck.thresholds import MAX_IMAGE_BYTES
from labelcheck.verify import MISSING_APPLICATION, verify_label

from fixtures import bourbon_application, bourbon_lines


def _png(image: Image.Image) -> bytes:
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def _bars() -> Image.Image:
    image = Image.new("RGB", (800, 800), "white")
    draw = ImageDraw.Draw(image)
    for start in range(0, 800, 40):
        draw.rectangle((start, 0, start + 16, 800), fill="black")
    return image


def _sharp(width: int = 800, height: int = 800) -> Image.Image:
    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)
    for position in range(0, max(width, height), 8):
        draw.line((position, 0, position, height), fill="black", width=2)
        draw.line((0, position, width, position), fill="black", width=2)
    return image


def _reader(_image):
    return bourbon_lines()


def test_a_readable_photo_is_parsed_and_compared():
    result = verify_label(_png(_sharp()), bourbon_application(), reader=_reader)

    assert result.error is None
    assert result.verdict.overall is OverallStatus.PASS
    assert result.verdict.summary == "5 of 5 required fields match."
    assert result.transcript[0] == "Kentucky Straight Bourbon Whiskey"
    assert result.seconds >= 0


def test_a_bad_file_does_not_read_the_label():
    def reader(_image):
        raise AssertionError("OCR should not run")

    result = verify_label(b"this is not a picture", bourbon_application(), reader=reader)

    assert result.verdict is None
    assert result.error == UNSUPPORTED_IMAGE
    assert result.transcript == []


def test_an_oversized_file_is_an_error():
    result = verify_label(b"x" * (MAX_IMAGE_BYTES + 1), bourbon_application(), reader=_reader)

    assert result.error == IMAGE_TOO_LARGE
    assert result.verdict is None


def test_a_photo_with_no_text_is_needs_review():
    result = verify_label(_png(_sharp()), bourbon_application(), reader=lambda _image: [])

    assert result.error is None
    assert result.verdict.overall is OverallStatus.NEEDS_REVIEW
    assert {item.status for item in result.verdict.fields} == {FieldStatus.UNREADABLE}


def test_a_blurry_photo_skips_ocr_and_is_not_a_failed_label():
    def reader(_image):
        raise AssertionError("OCR should not run")

    blurred = _bars().filter(ImageFilter.GaussianBlur(radius=4))
    result = verify_label(_png(blurred), bourbon_application(), reader=reader)

    assert result.error is None
    assert result.verdict.overall is OverallStatus.NEEDS_REVIEW
    assert result.verdict.summary == UNREADABLE_IMAGE_SUMMARY
    assert {item.status for item in result.verdict.fields} == {FieldStatus.UNREADABLE}
    assert result.transcript == []


def test_missing_application_fields_skip_ocr():
    def reader(_image):
        raise AssertionError("OCR should not run")

    result = verify_label(
        _png(_sharp()),
        bourbon_application(brand_name="  "),
        reader=reader,
    )

    assert result.verdict is None
    assert result.error == MISSING_APPLICATION


def test_logs_keep_timings_and_leave_out_the_label_text(caplog):
    caplog.set_level(logging.INFO, logger="labelcheck")

    verify_label(_png(_sharp()), bourbon_application(), reader=_reader)

    assert "OLD TOM" not in caplog.text
    assert "seconds=" in caplog.text
    assert "ocr_seconds=" in caplog.text


def test_a_blank_warning_still_uses_the_statutory_text():
    result = verify_label(_png(_sharp()), bourbon_application(), reader=_reader)
    warning = next(item for item in result.verdict.fields if item.name == "government_warning")

    assert warning.status is FieldStatus.MATCH
    assert warning.application.startswith("GOVERNMENT WARNING:")


@pytest.mark.parametrize("name", ["class_type", "alcohol_content", "net_contents"])
def test_each_required_application_field_is_checked(name):
    result = verify_label(
        _png(_sharp()),
        bourbon_application(**{name: ""}),
        reader=_reader,
    )

    assert result.error == MISSING_APPLICATION
