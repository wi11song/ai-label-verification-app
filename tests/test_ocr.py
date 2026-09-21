"""OCR line conversion. The real model is covered separately, and only when weights are on disk."""

from pathlib import Path

import pytest
from PIL import Image

from labelcheck.models import OverallStatus
from labelcheck.ocr import get_engine, model_dir, read_lines, weights_present
from labelcheck.thresholds import OCR_LONG_EDGE
from labelcheck.verify import verify_label

from fixtures import bourbon_application
from label_image import bourbon_png, font_ready


class _Result:
    def __init__(self, boxes, texts, scores):
        self.boxes = boxes
        self.txts = texts
        self.scores = scores


def test_lines_come_back_in_reading_order():
    def engine(_image):
        return _Result(
            [
                [[0, 50], [80, 50], [80, 70], [0, 70]],
                [[0, 10], [40, 10], [40, 40], [0, 40]],
            ],
            ["bottom", "TOP"],
            [0.91, 0.96],
        )

    lines = read_lines(Image.new("RGB", (100, 100), "white"), engine=engine)

    assert [line.text for line in lines] == ["TOP", "bottom"]
    assert lines[0].top == 10
    assert lines[0].height == 30
    assert lines[0].confidence == 0.96


def test_an_empty_read_returns_no_lines():
    def engine(_image):
        return _Result(None, None, None)

    assert read_lines(Image.new("RGB", (100, 100), "white"), engine=engine) == []


def test_the_long_edge_is_capped_before_reading():
    seen = {}

    def engine(image):
        seen["size"] = image.size
        return _Result(None, None, None)

    read_lines(Image.new("RGB", (3200, 800), "white"), engine=engine)

    assert seen["size"] == (OCR_LONG_EDGE, 400)


def test_missing_weights_are_reported_without_reading(tmp_path, monkeypatch):
    monkeypatch.setenv("LABELCHECK_MODEL_DIR", str(tmp_path))
    monkeypatch.setattr("labelcheck.ocr._engine", None)

    with pytest.raises(FileNotFoundError, match="OCR models are not on disk"):
        read_lines(Image.new("RGB", (100, 100), "white"))


@pytest.mark.skipif(
    not weights_present() or not font_ready(),
    reason="PP-OCRv5 mobile weights or a TrueType font are not available",
)
def test_bourbon_label_passes_within_five_seconds():
    image = bourbon_png()
    get_engine()
    verify_label(image, bourbon_application())
    result = verify_label(image, bourbon_application())

    assert result.error is None
    assert result.seconds < 5, result.seconds
    assert result.verdict.overall is OverallStatus.PASS, (
        result.verdict.summary,
        result.transcript,
    )
    assert result.transcript


def test_model_dir_follows_the_environment(monkeypatch, tmp_path):
    monkeypatch.setenv("LABELCHECK_MODEL_DIR", str(tmp_path))

    assert model_dir() == Path(tmp_path)
