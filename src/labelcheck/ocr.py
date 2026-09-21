"""Read label text with RapidOCR on ONNX Runtime.

This is the only module that imports the OCR runtime. Weights are loaded from
disk. A verify call does not download them.

Text-line angle classification is off. Phone rotation comes from EXIF. A line
that is still upside down stays low-confidence, so it is not treated as a match.
"""

import hashlib
import os
import threading
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
    result = (engine or get_engine())(prepared)
    return _to_lines(result)


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


def _to_lines(result: object) -> list[OcrLine]:
    boxes = getattr(result, "boxes", None)
    texts = getattr(result, "txts", None)
    scores = getattr(result, "scores", None)
    if boxes is None or texts is None or scores is None:
        return []
    measured: list[tuple[float, float, float, str, float]] = []
    for box, text, score in zip(boxes, texts, scores):
        cleaned = str(text).strip()
        if not cleaned:
            continue
        points = np.asarray(box, dtype=float).reshape(-1, 2)
        top = float(points[:, 1].min())
        left = float(points[:, 0].min())
        height = float(points[:, 1].max() - top)
        measured.append((top, left, height, cleaned, float(score)))
    measured.sort(key=lambda item: (item[0], item[1]))
    return [
        OcrLine(text=text, confidence=score, height=height, top=top)
        for top, _left, height, text, score in measured
    ]


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
