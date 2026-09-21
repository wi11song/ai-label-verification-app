"""Draw 12 flat labels and samples/extra_batch.csv.

These are new artwork. The photos already in samples/ are not part of this set.
Each label is a different spirit, with text this script controls, so a batch
upload can use the PNGs without the fonts.

Expected verdicts once the P2 checks are on:

- harbor_vodka.png — Pass. Vodka. The prefix is heavier than the warning body.
- cane_rum.png — Pass. Rum.
- agave_tequila.png — Pass. Tequila.
- oak_brandy.png — Pass. Brandy.
- desert_mezcal.png — Pass. Mezcal.
- highland_scotch.png — Pass. Scotch whisky, with a country of origin.
- river_cognac.png — Pass. Cognac.
- citrus_liqueur.png — Fail. Liqueur. The prefix is the same weight as the body.
- cedar_sake.png — Pass. Sake, after that class word is located.
- seoul_soju.png — Pass. Soju, after that class word is located.
- dry_vermouth.png — Pass. Vermouth, after that class word is located.
- tilted_vodka.png — Pass. The harbor vodka artwork, rotated a few degrees.
"""

import csv
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "samples" / "extra"
CSV_PATH = ROOT / "samples" / "extra_batch.csv"

PAPER = (236, 228, 210)
INK = (24, 24, 24)
WIDTH = 1500
MARGIN = 80

# The prefix is its own line so its box is not the body. Joined with spaces,
# these lines are the statutory warning.
_WARNING = (
    "GOVERNMENT WARNING:",
    "(1) According to the Surgeon General,",
    "women should not drink",
    "alcoholic beverages during pregnancy",
    "because of the risk of birth defects.",
    "(2) Consumption of alcoholic beverages",
    "impairs your ability to drive a car",
    "or operate machinery, and may cause",
    "health problems.",
)
_FONT = (
    Path("/System/Library/Fonts/Supplemental/Arial.ttf"),
    Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
    Path("/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf"),
)
_BOLD = (
    Path("/System/Library/Fonts/Supplemental/Arial Bold.ttf"),
    Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
    Path("/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"),
)
_COLUMNS = (
    "image",
    "brand_name",
    "class_type",
    "alcohol_content",
    "net_contents",
    "government_warning",
    "bottler",
    "country_of_origin",
)

# Twelve labels. bold_prefix False is the same-weight warning. tilt is degrees.
_LABELS = (
    {
        "image": "harbor_vodka.png",
        "brand_name": "HARBOR LIGHT",
        "class_type": "Vodka",
        "alcohol_content": "40%",
        "net_contents": "750 mL",
        "alcohol_line": "40% Alc./Vol. (80 Proof)",
    },
    {
        "image": "cane_rum.png",
        "brand_name": "CANE COPPER",
        "class_type": "Rum",
        "alcohol_content": "40%",
        "net_contents": "1 L",
        "alcohol_line": "40% Alc./Vol. (80 Proof)",
    },
    {
        "image": "agave_tequila.png",
        "brand_name": "AGAVE ROAD",
        "class_type": "Blanco Tequila",
        "alcohol_content": "40%",
        "net_contents": "750 mL",
        "alcohol_line": "40% Alc./Vol. (80 Proof)",
    },
    {
        "image": "oak_brandy.png",
        "brand_name": "OAK BARREL",
        "class_type": "Brandy",
        "alcohol_content": "40%",
        "net_contents": "750 mL",
        "alcohol_line": "40% Alc./Vol. (80 Proof)",
    },
    {
        "image": "desert_mezcal.png",
        "brand_name": "DESERT SMOKE",
        "class_type": "Mezcal",
        "alcohol_content": "42%",
        "net_contents": "750 mL",
        "alcohol_line": "42% Alc./Vol. (84 Proof)",
    },
    {
        "image": "highland_scotch.png",
        "brand_name": "HIGHLAND GATE",
        "class_type": "Scotch Whisky",
        "alcohol_content": "43%",
        "net_contents": "750 mL",
        "alcohol_line": "43% Alc./Vol.",
        "bottler": "Imported by Highland Gate, New York, NY",
        "country_of_origin": "Product of Scotland",
    },
    {
        "image": "river_cognac.png",
        "brand_name": "RIVER HOUSE",
        "class_type": "Cognac",
        "alcohol_content": "40%",
        "net_contents": "750 mL",
        "alcohol_line": "40% Alc./Vol. (80 Proof)",
    },
    {
        "image": "citrus_liqueur.png",
        "brand_name": "CITRUS HOUSE",
        "class_type": "Liqueur",
        "alcohol_content": "20%",
        "net_contents": "750 mL",
        "alcohol_line": "20% Alc./Vol.",
        "bold_prefix": False,
    },
    {
        "image": "cedar_sake.png",
        "brand_name": "CEDAR HOUSE",
        "class_type": "Junmai Sake",
        "alcohol_content": "15%",
        "net_contents": "720 mL",
        "alcohol_line": "15% Alc./Vol.",
    },
    {
        "image": "seoul_soju.png",
        "brand_name": "SEOUL LIGHT",
        "class_type": "Soju",
        "alcohol_content": "16%",
        "net_contents": "375 mL",
        "alcohol_line": "16% Alc./Vol.",
    },
    {
        "image": "dry_vermouth.png",
        "brand_name": "DRY HOUSE",
        "class_type": "Dry Vermouth",
        "alcohol_content": "18%",
        "net_contents": "750 mL",
        "alcohol_line": "18% Alc./Vol.",
    },
    {
        "image": "tilted_vodka.png",
        "brand_name": "HARBOR LIGHT",
        "class_type": "Vodka",
        "alcohol_content": "40%",
        "net_contents": "750 mL",
        "alcohol_line": "40% Alc./Vol. (80 Proof)",
        "tilt": 3,
    },
)


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    rows = []
    for spec in _LABELS:
        image = _draw(spec)
        if spec.get("tilt"):
            image = image.rotate(spec["tilt"], resample=Image.Resampling.BICUBIC, expand=True, fillcolor=PAPER)
        image.save(OUT_DIR / spec["image"], format="PNG")
        rows.append(
            {
                "image": spec["image"],
                "brand_name": spec["brand_name"],
                "class_type": spec["class_type"],
                "alcohol_content": spec["alcohol_content"],
                "net_contents": spec["net_contents"],
                "government_warning": "",
                "bottler": spec.get("bottler", ""),
                "country_of_origin": spec.get("country_of_origin", ""),
            }
        )
    with CSV_PATH.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


def _draw(spec: dict) -> Image.Image:
    brand = _font(_BOLD, 78)
    body = _font(_FONT, 46)
    prefix = _font(_BOLD, 58) if spec.get("bold_prefix", True) else body
    rows = [("brand", spec["brand_name"], brand)]
    rows.append(("body", spec["class_type"], body))
    rows.append(("body", spec["alcohol_line"], body))
    rows.append(("body", spec["net_contents"], body))
    if spec.get("country_of_origin"):
        rows.append(("body", spec["country_of_origin"], body))
    if spec.get("bottler"):
        rows.append(("body", spec["bottler"], body))
    rows.append(("prefix", _WARNING[0], prefix))
    for line in _WARNING[1:]:
        rows.append(("body", line, body))

    step = {"brand": 130, "prefix": 110, "body": 100}
    # A gap and a rule keep the warning block from being read differently on each label.
    warning_gap = 70
    height = 100 + warning_gap + sum(step[kind] for kind, _text, _font_face in rows) + 40
    image = Image.new("RGB", (WIDTH, height), PAPER)
    draw = ImageDraw.Draw(image)
    draw.rectangle((24, 24, WIDTH - 25, height - 25), outline=INK, width=8)
    top = 70
    for kind, text, font in rows:
        if kind == "prefix":
            top += warning_gap
            draw.line((MARGIN, top - 36, WIDTH - MARGIN, top - 36), fill=INK, width=4)
            words = text.split()
            cursor = MARGIN
            for word in words:
                draw.text((cursor, top), word, fill=INK, font=font)
                if font is not body:
                    draw.text((cursor + 1, top), word, fill=INK, font=font)
                cursor += int(font.getlength(word)) + 36
            top += step[kind]
            continue
        draw.text((MARGIN, top), text, fill=INK, font=font)
        top += step[kind]
    return image


def _font(candidates: tuple[Path, ...], size: int) -> ImageFont.FreeTypeFont:
    for path in candidates:
        if path.is_file():
            return ImageFont.truetype(str(path), size=size)
    raise FileNotFoundError("No TrueType font was found for the extra labels.")


if __name__ == "__main__":
    main()
