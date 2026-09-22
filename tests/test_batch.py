"""Batch jobs. The reader is a stand-in, so these tests do not load the OCR model."""

import io
import time
import zipfile
from io import BytesIO

from PIL import Image, ImageDraw
from starlette.testclient import TestClient

from labelcheck.batch import ZIP_UNSAFE, BatchError, build_items, read_zip
from labelcheck.thresholds import BATCH_MAX_ITEMS, BATCH_ZIP_BYTES
from labelcheck.verify import CHECK_TIMEOUT, MISSING_APPLICATION
from labelcheck.web import create_app

from fixtures import bourbon_lines


def _png() -> bytes:
    image = Image.new("RGB", (800, 800), "white")
    draw = ImageDraw.Draw(image)
    for position in range(0, 800, 8):
        draw.line((position, 0, position, 800), fill="black", width=2)
        draw.line((0, position, 800, position), fill="black", width=2)
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def _csv(*rows: str) -> bytes:
    header = "image,brand_name,class_type,alcohol_content,net_contents,government_warning,bottler,country_of_origin\n"
    return (header + "\n".join(rows) + "\n").encode()


def _zip(csv_bytes: bytes, photos: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("rows.csv", csv_bytes)
        for name, data in photos.items():
            archive.writestr(name, data)
    return buffer.getvalue()


def _wait(app, job_id: str):
    deadline = time.time() + 2
    while time.time() < deadline:
        job = app.state.batches.get(job_id)
        if job is not None and job.done:
            return job
        time.sleep(0.01)
    raise AssertionError("batch did not finish")


def _start(client: TestClient, packed: bytes):
    return client.post(
        "/batch",
        files={"zip": ("labels.zip", packed, "application/zip")},
        follow_redirects=False,
    )


def test_the_batch_form_offers_a_zip_example():
    response = TestClient(create_app()).get("/batch")

    assert response.status_code == 200
    assert "Try an example" in response.text
    assert "Extra spirits zip (12 labels)" in response.text
    assert "zip_batch.zip" in response.text


def test_the_batch_example_zip_is_served():
    client = TestClient(create_app())

    sample = client.get("/samples/zip_batch.zip")
    missing = client.get("/samples/not-a-batch.zip")

    assert sample.status_code == 200
    assert sample.headers["content-type"] in {"application/zip", "application/octet-stream"}
    assert sample.content[:2] == b"PK"
    assert missing.status_code == 404


def test_one_bad_row_does_not_stop_the_rest():
    calls = []

    def reader(_image):
        calls.append(1)
        return bourbon_lines()

    app = create_app(reader=reader)
    photo = _png()
    csv_bytes = _csv(
        "bourbon.png,OLD TOM DISTILLERY,Kentucky Straight Bourbon Whiskey,45%,750 mL,,,",
        "other.png,NOT A BRAND,Kentucky Straight Bourbon Whiskey,45%,750 mL,,,",
        "bad.png,OLD TOM DISTILLERY,Kentucky Straight Bourbon Whiskey,45%,750 mL,,,",
        "missing.png,OLD TOM DISTILLERY,Kentucky Straight Bourbon Whiskey,45%,750 mL,,,",
    )
    response = _start(
        TestClient(app),
        _zip(
            csv_bytes,
            {
                "bourbon.png": photo,
                "other.png": photo,
                "bad.png": b"this is not a picture",
            },
        ),
    )

    assert response.status_code == 303
    job_id = response.headers["location"].rsplit("/", 1)[-1]
    job = _wait(app, job_id)
    states = [item.state for item in job.items]

    assert states == ["pass", "fail", "error", "error"]
    assert calls == [1, 1]
    assert "No photo named missing.png" in job.items[3].summary

    page = TestClient(app).get(f"/batch/{job_id}")
    assert page.status_code == 200
    assert "Batch finished" in page.text
    assert ">Pass<" in page.text
    assert ">Fail<" in page.text
    assert ">Error<" in page.text
    detail = TestClient(app).get(f"/batch/{job_id}/items/1")
    assert "<h2>Label does not match</h2>" in detail.text
    assert "Application says" in detail.text
    assert "Required fields" in detail.text
    assert "NOT A BRAND" in detail.text
    assert f'/batch/{job_id}/items/1/image' in detail.text
    assert 'alt="Label photo other.png"' in detail.text
    photo = TestClient(app).get(f"/batch/{job_id}/items/1/image")
    assert photo.status_code == 200
    assert photo.headers["content-type"] == "image/png"
    assert photo.content.startswith(b"\x89PNG")
    missing_photo = TestClient(app).get(f"/batch/{job_id}/items/3/image")
    assert missing_photo.status_code == 404


def test_a_missing_application_field_does_not_read():
    def reader(_image):
        raise AssertionError("OCR should not run")

    app = create_app(reader=reader)
    csv_bytes = _csv("bourbon.png,,Kentucky Straight Bourbon Whiskey,45%,750 mL,,,")
    response = _start(TestClient(app), _zip(csv_bytes, {"bourbon.png": _png()}))
    job = _wait(app, response.headers["location"].rsplit("/", 1)[-1])

    assert job.items[0].state == "error"
    assert job.items[0].summary == MISSING_APPLICATION


def test_a_slow_row_times_out_and_the_next_row_still_runs():
    started = []

    def reader(_image):
        started.append(time.monotonic())
        time.sleep(0.4)
        return bourbon_lines()

    app = create_app(reader=reader, timeout=0.05)
    csv_bytes = _csv(
        "one.png,OLD TOM DISTILLERY,Kentucky Straight Bourbon Whiskey,45%,750 mL,,,",
        "two.png,OLD TOM DISTILLERY,Kentucky Straight Bourbon Whiskey,45%,750 mL,,,",
    )
    photo = _png()
    response = _start(TestClient(app), _zip(csv_bytes, {"one.png": photo, "two.png": photo}))
    job = _wait(app, response.headers["location"].rsplit("/", 1)[-1])

    assert [item.summary for item in job.items] == [CHECK_TIMEOUT, CHECK_TIMEOUT]
    assert len(started) == 2


def test_status_reports_counts():
    app = create_app(reader=lambda _image: bourbon_lines())
    csv_bytes = _csv("bourbon.png,OLD TOM DISTILLERY,Kentucky Straight Bourbon Whiskey,45%,750 mL,,,")
    response = _start(TestClient(app), _zip(csv_bytes, {"bourbon.png": _png()}))
    job_id = response.headers["location"].rsplit("/", 1)[-1]
    _wait(app, job_id)

    status = TestClient(app).get(f"/batch/{job_id}/status")

    assert status.status_code == 200
    assert status.json()["done"] is True
    assert status.json()["counts"]["pass"] == 1
    assert status.headers["cache-control"] == "no-store"


def test_an_expired_job_is_deleted():
    app = create_app(reader=lambda _image: bourbon_lines(), batch_lifetime=0)
    csv_bytes = _csv("bourbon.png,OLD TOM DISTILLERY,Kentucky Straight Bourbon Whiskey,45%,750 mL,,,")
    response = _start(TestClient(app), _zip(csv_bytes, {"bourbon.png": _png()}))
    job_id = response.headers["location"].rsplit("/", 1)[-1]

    page = TestClient(app).get(f"/batch/{job_id}")

    assert page.status_code == 404
    assert "no longer available" in page.text


def test_the_batch_form_names_the_controls():
    response = TestClient(create_app()).get("/batch")

    assert response.status_code == 200
    assert "Check many labels" in response.text
    assert 'name="zip"' in response.text
    assert 'name="csv"' not in response.text
    assert 'name="images"' not in response.text
    assert "What goes in the zip" in response.text
    assert "Download example zip" in response.text
    assert 'href="/samples/zip_batch.zip"' in response.text
    assert ">Start batch<" in response.text


def test_a_missing_zip_asks_for_one():
    response = TestClient(create_app()).post("/batch", data={}, follow_redirects=False)

    assert response.status_code == 200
    assert "Choose a zip file that contains one CSV and the label photos." in response.text


def test_more_than_300_rows_is_rejected():
    row = "bourbon.png,OLD TOM DISTILLERY,Kentucky Straight Bourbon Whiskey,45%,750 mL,,,"
    rows = "\n".join([row] * (BATCH_MAX_ITEMS + 1))
    try:
        build_items(_csv(rows), {})
    except BatchError as exc:
        assert "300" in str(exc)
    else:
        raise AssertionError("expected the cap to reject the CSV")


def test_a_zip_with_a_parent_path_is_rejected():
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("../secret.csv", "image,brand_name\n")
    try:
        read_zip(buffer.getvalue())
    except BatchError as exc:
        assert str(exc) == ZIP_UNSAFE
    else:
        raise AssertionError("expected the zip to be rejected")


def test_a_zip_over_the_compressed_limit_is_rejected_before_it_is_opened():
    try:
        read_zip(b"x" * (BATCH_ZIP_BYTES + 1))
    except BatchError as exc:
        assert "200 MB" in str(exc)
    else:
        raise AssertionError("expected the zip to be rejected")


def test_a_zip_of_a_csv_and_photo_runs():
    photo = _png()
    csv_bytes = _csv("bourbon.png,OLD TOM DISTILLERY,Kentucky Straight Bourbon Whiskey,45%,750 mL,,,")
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("nested/demo_batch.csv", csv_bytes)
        archive.writestr("nested/bourbon.png", photo)
    packed = buffer.getvalue()
    app = create_app(reader=lambda _image: bourbon_lines())
    response = _start(TestClient(app), packed)

    assert response.status_code == 303
    job = _wait(app, response.headers["location"].rsplit("/", 1)[-1])
    assert job.items[0].state == "pass"


def test_the_sample_csv_columns_are_accepted():
    sample = (
        __import__("pathlib").Path(__file__).resolve().parents[1] / "samples" / "demo_batch.csv"
    )
    items = build_items(sample.read_bytes(), {})

    assert len(items) == 7
    assert all(item.state == "error" for item in items)
    assert items[0].image_name == "bourbon.png"
    assert items[0].brand == "OLD TOM DISTILLERY"
