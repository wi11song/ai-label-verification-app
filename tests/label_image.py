"""A flat bourbon label drawn for the OCR integration test.

Lines are short and widely spaced so the detector returns one box per line.
Joined with spaces, the warning lines are the statutory text.
"""

from io import BytesIO
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

_LINES = (
    "Kentucky Straight Bourbon Whiskey",
    "45% Alc./Vol. (90 Proof)",
    "750 mL",
    "GOVERNMENT WARNING: (1) According to the",
    "Surgeon General, women should not drink",
    "alcoholic beverages during pregnancy",
    "because of the risk of birth defects.",
    "(2) Consumption of alcoholic beverages",
    "impairs your ability to drive a car or",
    "operate machinery, and may cause",
    "health problems.",
)
_FONT_CANDIDATES = (
    Path("/System/Library/Fonts/Supplemental/Arial.ttf"),
    Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
    Path("/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf"),
)
_BOLD_CANDIDATES = (
    Path("/System/Library/Fonts/Supplemental/Arial Bold.ttf"),
    Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
    Path("/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"),
)


def font_ready() -> bool:
    return any(path.is_file() for path in _BOLD_CANDIDATES)


def bourbon_png() -> bytes:
    image = _draw()
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def _draw() -> Image.Image:
    image = Image.new("RGB", (1500, 1600), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, 1499, 1599), outline="black", width=16)
    bold = _font(_BOLD_CANDIDATES, 64)
    body = _font(_BOLD_CANDIDATES, 48)
    draw.rectangle((40, 40, 1460, 180), fill="black")
    draw.text((70, 58), "OLD TOM DISTILLERY", fill="white", font=bold)
    top = 220
    for line in _LINES:
        draw.text((70, top), line, fill="black", font=body)
        top += 115
    return image


def _font(candidates: tuple[Path, ...], size: int) -> ImageFont.FreeTypeFont:
    for path in candidates:
        if path.is_file():
            return ImageFont.truetype(str(path), size=size)
    raise FileNotFoundError("No TrueType font was found for the bourbon fixture.")
