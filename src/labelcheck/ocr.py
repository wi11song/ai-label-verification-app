"""Read label text with RapidOCR on ONNX Runtime.

This is the only module that imports the OCR runtime. Weights are loaded from
disk. A verify call does not download them.

Text-line angle classification is off. Phone rotation comes from EXIF. A line
that is still upside down stays low-confidence, so it is not treated as a match.
"""

import hashlib
import os
import threading
import unicodedata
import urllib.request
from dataclasses import dataclass
from pathlib import Path

os.environ["ORT_DISABLE_TELEMETRY"] = "1"

import numpy as np
import onnxruntime
from PIL import Image, ImageOps
from rapidocr import EngineType, ModelType, OCRVersion, RapidOCR

onnxruntime.disable_telemetry_events()

from labelcheck.parse import OcrLine
from labelcheck.thresholds import OCR_LONG_EDGE

# PP-OCRv5 mobile, RapidOCR ONNX build v3.9.2. Checksums are the published SHA-256.
_DET_NAME = "ch_PP-OCRv5_det_mobile.onnx"
_REC_NAME = "ch_PP-OCRv5_rec_mobile.onnx"
_DET_URL = (
    "https://www.modelscope.cn/models/RapidAI/RapidOCR/resolve/v3.9.2/"
    "onnx/PP-OCRv5/det/ch_PP-OCRv5_det_mobile.onnx"
)
_REC_URL = (
    "https://www.modelscope.cn/models/RapidAI/RapidOCR/resolve/v3.9.2/"
    "onnx/PP-OCRv5/rec/ch_PP-OCRv5_rec_mobile.onnx"
)
_DET_SHA256 = "4d97c44a20d30a81aad087d6a396b08f786c4635742afc391f6621f5c6ae78ae"
_REC_SHA256 = "5825fc7ebf84ae7a412be049820b4d86d77620f204a041697b0494669b1742c5"
# Drop only very weak noise. Lines under the comparison cutoff still come back
# so a low-confidence read stays Unreadable instead of disappearing.
_TEXT_SCORE = 0.3

_engine: RapidOCR | None = None
_engine_lock = threading.Lock()


@dataclass(frozen=True)
class _ModelFile:
    name: str
    url: str
    sha256: str


_MODELS = (
    _ModelFile(_DET_NAME, _DET_URL, _DET_SHA256),
    _ModelFile(_REC_NAME, _REC_URL, _REC_SHA256),
)


def model_dir() -> Path:
    override = os.environ.get("LABELCHECK_MODEL_DIR")
    if override:
        return Path(override)
    return Path(__file__).resolve().parents[2] / "models"


def weights_present(directory: Path | None = None) -> bool:
    directory = directory or model_dir()
    return all((directory / item.name).is_file() for item in _MODELS)


def download_models(directory: Path | None = None) -> Path:
    """Fetch the pinned weights. Not used by a verify call."""
    directory = directory or model_dir()
    directory.mkdir(parents=True, exist_ok=True)
    for item in _MODELS:
        destination = directory / item.name
        if destination.is_file() and _sha256(destination) == item.sha256:
            continue
        _download(item.url, destination)
        digest = _sha256(destination)
        if digest != item.sha256:
            destination.unlink(missing_ok=True)
            raise RuntimeError(f"{item.name} checksum did not match the pinned PP-OCRv5 file.")
    return directory


def read_lines(image: Image.Image, engine: RapidOCR | None = None) -> list[OcrLine]:
    """Return text lines in reading order. The long edge is capped first."""
    prepared = _scaled(image)
    if engine is None:
        reader = get_engine()
        # Flags are sticky on the engine, so a later line re-read must not
        # leave detection turned off for the next label.
        detected = reader(prepared, use_det=True, use_cls=False, use_rec=True)
        return _to_lines(detected, image=prepared, reader=reader)
    return _to_lines(engine(prepared))


def get_engine() -> RapidOCR:
    global _engine
    if _engine is None:
        with _engine_lock:
            if _engine is None:
                _engine = _build_engine(model_dir())
    return _engine


def _build_engine(directory: Path) -> RapidOCR:
    det = directory / _DET_NAME
    rec = directory / _REC_NAME
    missing = [path.name for path in (det, rec) if not path.is_file()]
    if missing:
        names = f"{_DET_NAME} and {_REC_NAME}"
        raise FileNotFoundError(
            f"OCR models are not on disk. Expected {names} in {directory}."
        )
    return RapidOCR(
        params={
            "Global.use_cls": False,
            "Global.log_level": "error",
            "Global.text_score": _TEXT_SCORE,
            "Global.max_side_len": OCR_LONG_EDGE,
            "Det.engine_type": EngineType.ONNXRUNTIME,
            "Det.model_type": ModelType.MOBILE,
            "Det.ocr_version": OCRVersion.PPOCRV5,
            "Det.model_path": str(det),
            "Rec.engine_type": EngineType.ONNXRUNTIME,
            "Rec.model_type": ModelType.MOBILE,
            "Rec.ocr_version": OCRVersion.PPOCRV5,
            "Rec.model_path": str(rec),
            # A CPU limit does not change the count this process sees. Two threads
            # matches the 2 vCPU box and avoids oversubscribing that limit.
            "EngineConfig.onnxruntime.intra_op_num_threads": 2,
            "EngineConfig.onnxruntime.inter_op_num_threads": 1,
        }
    )


def _scaled(image: Image.Image) -> Image.Image:
    upright = ImageOps.exif_transpose(image) or image
    rgb = upright.convert("RGB")
    long_edge = max(rgb.size)
    if long_edge <= OCR_LONG_EDGE:
        return rgb
    scale = OCR_LONG_EDGE / long_edge
    size = (max(1, round(rgb.width * scale)), max(1, round(rgb.height * scale)))
    return rgb.resize(size, Image.Resampling.LANCZOS)


# Words whose centers sit within this fraction of the line height are one line.
_SAME_LINE = 0.55
# An overlap this large means two boxes cut through the same word.
_OVERLAP = 0.2


@dataclass(frozen=True)
class _Word:
    text: str
    score: float
    top: float
    bottom: float
    left: float
    right: float

    @property
    def center(self) -> float:
        return (self.top + self.bottom) / 2

    @property
    def height(self) -> float:
        return self.bottom - self.top


def _to_lines(
    result: object,
    image: Image.Image | None = None,
    reader: RapidOCR | None = None,
) -> list[OcrLine]:
    words = _words(result)
    if not words:
        return []
    lines: list[OcrLine] = []
    for group in _rows(words):
        lines.append(_as_line(group, image, reader))
    lines.sort(key=lambda line: (line.top, line.text))
    return lines


def _words(result: object) -> list[_Word]:
    boxes = getattr(result, "boxes", None)
    texts = getattr(result, "txts", None)
    scores = getattr(result, "scores", None)
    if boxes is None or texts is None or scores is None:
        return []
    words: list[_Word] = []
    for box, text, score in zip(boxes, texts, scores):
        cleaned = unicodedata.normalize("NFKC", str(text)).strip()
        if not cleaned:
            continue
        points = np.asarray(box, dtype=float).reshape(-1, 2)
        words.append(
            _Word(
                text=cleaned,
                score=float(score),
                top=float(points[:, 1].min()),
                bottom=float(points[:, 1].max()),
                left=float(points[:, 0].min()),
                right=float(points[:, 0].max()),
            )
        )
    return words


def _rows(words: list[_Word]) -> list[list[_Word]]:
    ordered = sorted(words, key=lambda word: (word.center, word.left))
    rows: list[list[_Word]] = []
    for word in ordered:
        if not rows:
            rows.append([word])
            continue
        row = rows[-1]
        anchor = sum(item.center for item in row) / len(row)
        height = max(item.height for item in row)
        if word.center - anchor <= max(8.0, _SAME_LINE * height):
            row.append(word)
        else:
            rows.append([word])
    return rows


def _as_line(row: list[_Word], image: Image.Image | None, reader: RapidOCR | None) -> OcrLine:
    ordered = sorted(row, key=lambda word: word.left)
    top = min(word.top for word in ordered)
    height = max(word.bottom for word in ordered) - top
    text, score = _read_row(ordered, image, reader)
    return OcrLine(text=text, confidence=score, height=height, top=top)


def _read_row(
    ordered: list[_Word],
    image: Image.Image | None,
    reader: RapidOCR | None,
) -> tuple[str, float]:
    joined = unicodedata.normalize("NFKC", " ".join(word.text for word in ordered))
    score = min(word.score for word in ordered)
    if image is None or reader is None or not _cuts_a_word(ordered):
        return joined, score
    pad = 4
    left = max(0, int(min(word.left for word in ordered)) - pad)
    top = max(0, int(min(word.top for word in ordered)) - pad)
    right = min(image.width, int(max(word.right for word in ordered)) + pad)
    bottom = min(image.height, int(max(word.bottom for word in ordered)) + pad)
    if right <= left or bottom <= top:
        return joined, score
    recognized = reader(
        image.crop((left, top, right, bottom)),
        use_det=False,
        use_cls=False,
        use_rec=True,
    )
    texts = getattr(recognized, "txts", None) or ()
    scores = getattr(recognized, "scores", None) or ()
    reread = unicodedata.normalize("NFKC", " ".join(str(text).strip() for text in texts if str(text).strip()))
    if not reread:
        return joined, score
    return reread, float(min(scores)) if scores else score


def _cuts_a_word(ordered: list[_Word]) -> bool:
    for previous, following in zip(ordered, ordered[1:]):
        overlap = min(previous.right, following.right) - max(previous.left, following.left)
        if overlap <= 2:
            continue
        smaller = min(previous.right - previous.left, following.right - following.left)
        if smaller > 0 and overlap / smaller >= _OVERLAP:
            return True
    return False


def _download(url: str, destination: Path) -> None:
    request = urllib.request.Request(url, headers={"User-Agent": "labelcheck"})
    with urllib.request.urlopen(request, timeout=120) as response:
        destination.write_bytes(response.read())


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
