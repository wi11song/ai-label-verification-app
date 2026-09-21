"""Image quality gate. Synthetic photos only, so no OCR model is involved."""

from io import BytesIO

from PIL import Image, ImageDraw, ImageFilter

from labelcheck.compare import compare_label
from labelcheck.models import FieldStatus, OverallStatus
from labelcheck.quality import (
    IMAGE_TOO_LARGE,
    IMAGE_TOO_SMALL,
    IMAGE_WASHED_OUT,
    UNREADABLE_IMAGE_SUMMARY,
    UNSUPPORTED_IMAGE,
    check_image,
)
from labelcheck.thresholds import MAX_IMAGE_BYTES

from fixtures import bourbon_application, bourbon_extracted


def _png(image: Image.Image) -> bytes:
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def _jpeg(image: Image.Image, orientation: int | None = None) -> bytes:
    buffer = BytesIO()
    exif = Image.Exif()
    if orientation is not None:
        exif[0x0112] = orientation
    image.save(buffer, format="JPEG", quality=95, exif=exif.tobytes())
    return buffer.getvalue()


def _sharp(width: int = 800, height: int = 800) -> Image.Image:
    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)
    for position in range(0, max(width, height), 8):
        draw.line((position, 0, position, height), fill="black", width=2)
        draw.line((0, position, width, position), fill="black", width=2)
    return image


def test_a_sharp_photo_can_be_read():
    check = check_image(_png(_sharp()))

    assert check.readable
    assert check.note is None
    assert check.error is None
    assert check.width == 800
    assert check.height == 800


def test_jpeg_and_tiff_are_accepted():
    assert check_image(_jpeg(_sharp())).readable
    buffer = BytesIO()
    _sharp().save(buffer, format="TIFF")
    assert check_image(buffer.getvalue()).readable


def test_a_small_photo_asks_for_a_larger_one():
    check = check_image(_png(_sharp(400, 700)))

    assert not check.readable
    assert check.error is None
    assert check.note == IMAGE_TOO_SMALL


def _bars() -> Image.Image:
    image = Image.new("RGB", (800, 800), "white")
    draw = ImageDraw.Draw(image)
    for start in range(0, 800, 40):
        draw.rectangle((start, 0, start + 16, 800), fill="black")
    return image


def test_a_blurred_photo_is_needs_review_and_not_a_label_failure():
    blurred = _bars().filter(ImageFilter.GaussianBlur(radius=4))
    check = check_image(_png(blurred))
    verdict = compare_label(
        bourbon_application(),
        bourbon_extracted(),
        image_readable=check.readable,
        image_note=check.note,
    )

    assert check.note == UNREADABLE_IMAGE_SUMMARY
    assert verdict.overall is OverallStatus.NEEDS_REVIEW
    assert verdict.summary == UNREADABLE_IMAGE_SUMMARY
    assert {item.status for item in verdict.fields} == {FieldStatus.UNREADABLE}


def test_a_blank_photo_is_washed_out_rather_than_blurry():
    check = check_image(_png(Image.new("RGB", (800, 800), "white")))

    assert check.note == IMAGE_WASHED_OUT
    assert check.error is None


def test_a_glare_band_is_washed_out():
    image = _sharp()
    ImageDraw.Draw(image).rectangle((0, 250, 800, 520), fill="white")
    check = check_image(_png(image))

    assert check.note == IMAGE_WASHED_OUT


def test_orientation_is_applied_before_measuring():
    # Tag 6 stores a 900x400 image that should display as 400x900.
    check = check_image(_jpeg(_sharp(900, 400), orientation=6))

    assert check.width == 400
    assert check.height == 900
    assert check.note == IMAGE_TOO_SMALL


def test_corrupt_and_unsupported_files_are_errors():
    assert check_image(b"this is not a picture").error == UNSUPPORTED_IMAGE
    gif = BytesIO()
    _sharp().save(gif, format="GIF")
    assert check_image(gif.getvalue()).error == UNSUPPORTED_IMAGE
    assert check_image(b"x" * (MAX_IMAGE_BYTES + 1)).error == IMAGE_TOO_LARGE
