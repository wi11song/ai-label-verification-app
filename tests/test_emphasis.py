"""Stroke comparison for the warning prefix. No OCR model."""

from PIL import Image, ImageDraw

from labelcheck.emphasis import compare_crops


def test_a_heavier_prefix_matches():
    assert compare_crops(_stripes(8), _stripes(2)) == "match"


def test_the_same_stroke_weight_mismatches():
    assert compare_crops(_stripes(3), _stripes(3)) == "mismatch"


def test_a_tiny_crop_is_inconclusive():
    tiny = Image.new("L", (4, 4), 255)
    assert compare_crops(tiny, _stripes(3)) == "inconclusive"


def test_a_faint_crop_is_inconclusive():
    faint = Image.new("L", (80, 40), 200)
    draw = ImageDraw.Draw(faint)
    draw.rectangle((8, 16, 72, 22), fill=185)
    assert compare_crops(faint, _stripes(3)) == "inconclusive"


def _stripes(thickness: int) -> Image.Image:
    image = Image.new("L", (180, 48), 255)
    draw = ImageDraw.Draw(image)
    top = 6
    while top < 42:
        draw.line((8, top, 172, top), fill=0, width=thickness)
        top += 16
    return image
