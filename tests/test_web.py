"""The single-label page. The reader is a stand-in, so these tests do not load the OCR model."""

import time
from io import BytesIO

from PIL import Image, ImageDraw, ImageFilter
from starlette.testclient import TestClient

from labelcheck.parse import OcrLine
from labelcheck.quality import IMAGE_TOO_LARGE, UNREADABLE_IMAGE_SUMMARY, UNSUPPORTED_IMAGE
from labelcheck.thresholds import MAX_IMAGE_BYTES
from labelcheck.web import CHECK_FAILED, CHECK_TIMEOUT, CHOOSE_PHOTO, create_app

from fixtures import bourbon_application, bourbon_lines


def _png(image: Image.Image) -> bytes:
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def _sharp() -> Image.Image:
    image = Image.new("RGB", (800, 800), "white")
    draw = ImageDraw.Draw(image)
    for position in range(0, 800, 8):
        draw.line((position, 0, position, 800), fill="black", width=2)
        draw.line((0, position, 800, position), fill="black", width=2)
    return image


def _bars() -> Image.Image:
    image = Image.new("RGB", (800, 800), "white")
    draw = ImageDraw.Draw(image)
    for start in range(0, 800, 40):
        draw.rectangle((start, 0, start + 16, 800), fill="black")
    return image


def _form(**overrides: str) -> dict[str, str]:
    application = bourbon_application()
    values = {
        "brand_name": application.brand_name,
        "class_type": application.class_type,
        "alcohol_content": application.alcohol_content,
        "net_contents": application.net_contents,
        "government_warning": "",
        "bottler": "",
        "country_of_origin": "",
    }
    values.update(overrides)
    return values


def _post(client: TestClient, image: bytes | None, **fields: str):
    data = _form(**fields)
    if image is None:
        return client.post("/verify", data=data)
    return client.post("/verify", data=data, files={"image": ("label.png", image, "image/png")})


def test_the_page_is_one_form_with_labeled_fields():
    response = TestClient(create_app()).get("/")

    assert response.status_code == 200
    assert "Alcohol Label Check" in response.text
    assert "Check a label" in response.text
    assert 'action="/verify"' in response.text
    for label in ("Brand name", "Class / type", "Alcohol content", "Net contents", "Government warning"):
        assert label in response.text
    assert response.text.count(">Verify<") == 1
    assert "<h2>Pass</h2>" not in response.text
    assert response.headers["cache-control"] == "no-store"


def test_a_missing_photo_asks_for_one_and_keeps_the_application():
    response = _post(TestClient(create_app()), None, brand_name="Stone's Throw")

    assert response.status_code == 200
    assert CHOOSE_PHOTO in response.text
    assert "Stone&#39;s Throw" in response.text or "Stone's Throw" in response.text
    assert "Nothing was saved." in response.text


def test_a_bad_file_is_an_error_and_does_not_read():
    def reader(_image):
        raise AssertionError("OCR should not run")

    response = _post(TestClient(create_app(reader=reader)), b"this is not a picture")

    assert UNSUPPORTED_IMAGE in response.text
    assert "<h2>Fail</h2>" not in response.text


def test_a_blurry_photo_is_needs_review_and_does_not_read():
    def reader(_image):
        raise AssertionError("OCR should not run")

    blurred = _bars().filter(ImageFilter.GaussianBlur(radius=4))
    response = _post(TestClient(create_app(reader=reader)), _png(blurred))

    assert "<h2>Needs review</h2>" in response.text
    assert UNREADABLE_IMAGE_SUMMARY in response.text
    assert ">Unreadable<" in response.text
    assert "<h2>Fail</h2>" not in response.text


def test_missing_application_fields_are_explained():
    def reader(_image):
        raise AssertionError("OCR should not run")

    response = _post(TestClient(create_app(reader=reader)), _png(_sharp()), brand_name="  ")

    assert "required before verification" in response.text


def test_a_readable_label_shows_the_verdict_on_the_same_page():
    client = TestClient(create_app(reader=lambda _image: bourbon_lines()))
    response = _post(client, _png(_sharp()))

    assert "<h2>Pass</h2>" in response.text
    assert "All checked fields match." in response.text
    assert ">Match<" in response.text
    assert "OLD TOM DISTILLERY" in response.text
    assert "What the reader saw on the label" in response.text
    assert "Bold type" in response.text
    assert "Nothing was saved." in response.text
    assert "Checked in" in response.text


def test_a_bold_check_replaces_the_not_checked_note():
    def reader(_image):
        lines = bourbon_lines()
        warning = lines[-1]
        lines[-1] = OcrLine(
            warning.text,
            warning.confidence,
            warning.height,
            warning.top,
            emphasis="match",
        )
        return lines

    response = _post(TestClient(create_app(reader=reader)), _png(_sharp()))

    assert "<h2>Pass</h2>" in response.text
    assert "heavier than the rest of the warning" in response.text
    assert "was not checked" not in response.text


def test_label_text_is_escaped():
    def reader(_image):
        lines = list(bourbon_lines())
        lines.append(OcrLine("<script>bad</script>", 0.99, height=10, top=400))
        return lines

    response = _post(
        TestClient(create_app(reader=reader)),
        _png(_sharp()),
        brand_name="<b>Brand</b>",
    )

    assert "<script>bad</script>" not in response.text
    assert "&lt;script&gt;bad&lt;/script&gt;" in response.text
    assert "<b>Brand</b>" not in response.text
    assert "&lt;b&gt;Brand&lt;/b&gt;" in response.text


def test_an_oversized_photo_is_rejected():
    huge = b"x" * (MAX_IMAGE_BYTES + 1)
    response = _post(TestClient(create_app()), huge)

    assert IMAGE_TOO_LARGE in response.text


def test_a_slow_check_times_out():
    def reader(_image):
        time.sleep(0.4)
        return bourbon_lines()

    response = _post(TestClient(create_app(reader=reader, timeout=0.05)), _png(_sharp()))

    assert CHECK_TIMEOUT in response.text


def test_a_reader_error_is_plain_language():
    def reader(_image):
        raise RuntimeError("model exploded")

    response = _post(TestClient(create_app(reader=reader)), _png(_sharp()))

    assert response.status_code == 200
    assert CHECK_FAILED in response.text
    assert "model exploded" not in response.text
