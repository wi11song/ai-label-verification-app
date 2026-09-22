"""One page: upload a label, enter the application, press Verify, read the result there."""

import base64
import logging
import os
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FuturesTimeoutError
from pathlib import Path

from starlette.applications import Starlette
from starlette.formparsers import MultiPartException
from starlette.requests import Request
from starlette.responses import FileResponse, Response
from starlette.routing import Route
from starlette.templating import Jinja2Templates

from labelcheck.batch import CHOOSE_ZIP, BatchError, BatchStore, read_zip
from labelcheck.models import FIELD_LABELS, Application
from labelcheck.quality import IMAGE_TOO_LARGE
from labelcheck.thresholds import BATCH_JOB_SECONDS, BATCH_ZIP_BYTES, MAX_IMAGE_BYTES, SINGLE_LABEL_TIMEOUT
from labelcheck.verify import CHECK_FAILED, CHECK_TIMEOUT, Verification, verify_label

logger = logging.getLogger("labelcheck")

CHOOSE_PHOTO = "Choose a label photo, then press Verify."
BOLD_NOTE = "Bold type on “GOVERNMENT WARNING:” was not checked by this prototype."
_EMPHASIS_NOTES = {
    "match": "“GOVERNMENT WARNING:” is heavier than the rest of the warning.",
    "mismatch": "“GOVERNMENT WARNING:” is not heavier than the rest of the warning.",
    "inconclusive": "Bold type on “GOVERNMENT WARNING:” could not be judged. A person should check it.",
}
BATCH_UPLOAD_TOO_LARGE = "This upload is too large. A photo must be under 10 MB, and a zip under 200 MB."

STATUS_TEXT = {
    "pass": "Pass",
    "fail": "Fail",
    "needs_review": "Needs review",
    "match": "Match",
    "mismatch": "Does not match",
    "unreadable": "Unreadable",
    "queued": "Queued",
    "running": "Running",
    "error": "Error",
}


def bold_note_for(result: Verification | None) -> str:
    """The blanket sentence stays only when the bold check did not run."""
    warning = None
    if result is not None and result.verdict is not None:
        warning = next((item for item in result.verdict.fields if item.name == "government_warning"), None)
    if warning is None or warning.emphasis not in _EMPHASIS_NOTES:
        return BOLD_NOTE
    return _EMPHASIS_NOTES[warning.emphasis]


FIELDS = (
    {
        "name": "brand_name",
        "label": "Brand name",
        "required": True,
        "multiline": False,
        "placeholder": "OLD TOM DISTILLERY",
        "hint": "",
    },
    {
        "name": "class_type",
        "label": "Class / type",
        "required": True,
        "multiline": False,
        "placeholder": "Kentucky Straight Bourbon Whiskey",
        "hint": "",
    },
    {
        "name": "alcohol_content",
        "label": "Alcohol content",
        "required": True,
        "multiline": False,
        "placeholder": "45% Alc./Vol. (90 Proof)",
        "hint": "",
    },
    {
        "name": "net_contents",
        "label": "Net contents",
        "required": True,
        "multiline": False,
        "placeholder": "750 mL",
        "hint": "",
    },
    {
        "name": "government_warning",
        "label": "Government warning",
        "required": False,
        "multiline": True,
        "placeholder": "",
        "hint": "Leave blank to check against the standard legal wording.",
    },
    {
        "name": "bottler",
        "label": "Bottler / producer name and address",
        "required": False,
        "multiline": True,
        "placeholder": "",
        "hint": "",
    },
    {
        "name": "country_of_origin",
        "label": "Country of origin (imports)",
        "required": False,
        "multiline": False,
        "placeholder": "",
        "hint": "",
    },
)

# Known sample photos. Choosing one fills the application and attaches that photo.
EXAMPLES = (
    {
        "label": "Bourbon (should pass)",
        "image": "bourbon.png",
        "brand_name": "OLD TOM DISTILLERY",
        "class_type": "Kentucky Straight Bourbon Whiskey",
        "alcohol_content": "45%",
        "net_contents": "750 mL",
        "government_warning": "",
        "bottler": "Bottled by Old Tom Distillery, Bardstown, KY",
        "country_of_origin": "",
    },
    {
        "label": "STONE'S THROW vs Stone's Throw",
        "image": "stones_throw.png",
        "brand_name": "Stone's Throw",
        "class_type": "Straight Rye Whisky",
        "alcohol_content": "50% Alc./Vol. (100 Proof)",
        "net_contents": "750 mL",
        "government_warning": "",
        "bottler": "Bottled by Stone's Throw Spirits, Frankfort, KY",
        "country_of_origin": "",
    },
    {
        "label": "Missing apostrophe",
        "image": "stones_throw_no_apostrophe.png",
        "brand_name": "Stone's Throw",
        "class_type": "Straight Rye Whisky",
        "alcohol_content": "50% Alc./Vol. (100 Proof)",
        "net_contents": "750 mL",
        "government_warning": "",
        "bottler": "Bottled by Stone's Throw Spirits, Frankfort, KY",
        "country_of_origin": "",
    },
    {
        "label": "Title-case warning",
        "image": "title_case_warning.png",
        "brand_name": "OLD TOM DISTILLERY",
        "class_type": "Kentucky Straight Bourbon Whiskey",
        "alcohol_content": "45% Alc./Vol. (90 Proof)",
        "net_contents": "750 mL",
        "government_warning": "",
        "bottler": "Bottled by Old Tom Distillery, Bardstown, KY",
        "country_of_origin": "",
    },
    {
        "label": "Wrong alcohol %",
        "image": "wrong_abv.png",
        "brand_name": "OLD TOM DISTILLERY",
        "class_type": "Kentucky Straight Bourbon Whiskey",
        "alcohol_content": "45%",
        "net_contents": "750 mL",
        "government_warning": "",
        "bottler": "Bottled by Old Tom Distillery, Bardstown, KY",
        "country_of_origin": "",
    },
    {
        "label": "Blurry photo",
        "image": "blurry.png",
        "brand_name": "OLD TOM DISTILLERY",
        "class_type": "Kentucky Straight Bourbon Whiskey",
        "alcohol_content": "45% Alc./Vol. (90 Proof)",
        "net_contents": "750 mL",
        "government_warning": "",
        "bottler": "Bottled by Old Tom Distillery, Bardstown, KY",
        "country_of_origin": "",
    },
    {
        "label": "Imported gin (1 L vs 1000 mL)",
        "image": "imported_gin.png",
        "brand_name": "HARBOUR LIGHT",
        "class_type": "London Dry Gin",
        "alcohol_content": "47% Alc./Vol.",
        "net_contents": "1 L",
        "government_warning": "",
        "bottler": "Imported by Harbour Light Imports, Seattle, WA",
        "country_of_origin": "Product of England",
    },
)
_EXAMPLE_IMAGES = {item["image"] for item in EXAMPLES}

BATCH_SAMPLE_ZIP = "zip_batch.zip"

# Known batch zip. Choosing it fills the zip field and starts the check.
BATCH_EXAMPLES = (
    {
        "label": "Extra spirits zip (12 labels)",
        "zip": BATCH_SAMPLE_ZIP,
        "hint": "Loads the sample zip and starts the batch.",
    },
)
_SAMPLE_FILES = _EXAMPLE_IMAGES | {item["zip"] for item in BATCH_EXAMPLES} | {BATCH_SAMPLE_ZIP}

_TEMPLATES = Jinja2Templates(directory=str(Path(__file__).resolve().parent / "templates"))
_NO_STORE = {"Cache-Control": "no-store"}


def create_app(
    *,
    reader=None,
    timeout: float = SINGLE_LABEL_TIMEOUT,
    batch_lifetime: float = BATCH_JOB_SECONDS,
) -> Starlette:
    executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="labelcheck")
    store = BatchStore(executor, reader=reader, timeout=timeout, lifetime=batch_lifetime)

    async def home(request: Request) -> Response:
        return _render(request, _blank_form(), None)

    async def sample_photo(request: Request) -> Response:
        name = request.path_params["name"]
        path = _sample_path(name)
        if path is None:
            return Response("That example photo is not available.", status_code=404, headers=_NO_STORE)
        if path.suffix.lower() == ".zip":
            return FileResponse(
                path,
                filename=name,
                media_type="application/zip",
                headers=_NO_STORE,
            )
        return FileResponse(path, headers=_NO_STORE)

    async def check(request: Request) -> Response:
        try:
            form = await request.form(max_files=1, max_fields=20, max_part_size=MAX_IMAGE_BYTES)
        except MultiPartException:
            return _render(request, _blank_form(), Verification(error=IMAGE_TOO_LARGE))
        values = _form_values(form)
        upload = form.get("image")
        if upload is None or not getattr(upload, "filename", None):
            return _render(request, values, Verification(error=CHOOSE_PHOTO))
        try:
            data = await upload.read()
        finally:
            await upload.close()
        result = _run_check(data, _application(values), reader=reader, timeout=timeout, executor=executor)
        result.image_name = Path(upload.filename).name
        result.image_data = data
        return _render(request, values, result)

    async def batch_form(request: Request) -> Response:
        return _render_batch(request, error=None, job=None)

    async def batch_start(request: Request) -> Response:
        try:
            form = await request.form(max_files=1, max_fields=5, max_part_size=BATCH_ZIP_BYTES)
        except MultiPartException:
            return _render_batch(request, error=BATCH_UPLOAD_TOO_LARGE, job=None)
        try:
            csv_bytes, images = await _batch_inputs(form)
            job = store.create(csv_bytes, images)
        except BatchError as exc:
            return _render_batch(request, error=str(exc), job=None)
        return Response(status_code=303, headers={"Location": f"/batch/{job.id}", **_NO_STORE})

    async def batch_progress(request: Request) -> Response:
        job = store.get(request.path_params["job_id"])
        if job is None:
            return _render_batch(request, error=None, job=None, missing=True)
        return _render_batch(request, error=None, job=job)

    async def batch_status(request: Request) -> Response:
        from starlette.responses import JSONResponse

        job = store.get(request.path_params["job_id"])
        if job is None:
            return JSONResponse({"error": "This batch is no longer available."}, status_code=404, headers=_NO_STORE)
        return JSONResponse(store.snapshot(job), headers=_NO_STORE)

    async def batch_item(request: Request) -> Response:
        job = store.get(request.path_params["job_id"])
        index = request.path_params["index"]
        if job is None or not isinstance(index, int) or index < 0 or index >= len(job.items):
            return _render_batch(request, error=None, job=None, missing=True)
        with job.lock:
            item = job.items[index]
            has_photo = bool(item.image_name and item.image_name in job.images)
        return _TEMPLATES.TemplateResponse(
            request,
            "batch_item.html",
            {
                "page": "batch",
                "job": job,
                "item": item,
                "has_photo": has_photo,
                "labels": FIELD_LABELS,
                "status_text": STATUS_TEXT,
                "bold_note": bold_note_for(item.result),
                "saved_note": f"Results from this batch are deleted after {BATCH_JOB_SECONDS // 60} minutes.",
            },
            headers=_NO_STORE,
        )

    async def batch_item_image(request: Request) -> Response:
        job = store.get(request.path_params["job_id"])
        index = request.path_params["index"]
        if job is None or not isinstance(index, int) or index < 0 or index >= len(job.items):
            return Response("That photo is no longer available.", status_code=404, headers=_NO_STORE)
        with job.lock:
            item = job.items[index]
            data = job.images.get(item.image_name)
        if not data:
            return Response("That photo is no longer available.", status_code=404, headers=_NO_STORE)
        return Response(data, media_type=_image_type(item.image_name), headers=_NO_STORE)

    app = Starlette(
        routes=[
            Route("/", home, methods=["GET"]),
            Route("/verify", check, methods=["POST"]),
            Route("/samples/{name}", sample_photo, methods=["GET"]),
            Route("/batch", batch_form, methods=["GET"]),
            Route("/batch", batch_start, methods=["POST"]),
            Route("/batch/{job_id}", batch_progress, methods=["GET"]),
            Route("/batch/{job_id}/status", batch_status, methods=["GET"]),
            Route("/batch/{job_id}/items/{index:int}", batch_item, methods=["GET"]),
            Route("/batch/{job_id}/items/{index:int}/image", batch_item_image, methods=["GET"]),
        ]
    )
    app.state.batches = store
    return app


def _render(request: Request, values: dict[str, str], result: Verification | None) -> Response:
    return _TEMPLATES.TemplateResponse(
        request,
        "check.html",
        {
            "page": "single",
            "fields": FIELDS,
            "values": values,
            "result": result,
            "label_image_src": _label_image_src(result),
            "labels": FIELD_LABELS,
            "status_text": STATUS_TEXT,
            "bold_note": bold_note_for(result),
            "examples": EXAMPLES,
        },
        headers=_NO_STORE,
    )


def _label_image_src(result: Verification | None) -> str | None:
    if result is None or not result.image_data:
        return None
    mime = _image_type(result.image_name or "label.png")
    encoded = base64.b64encode(result.image_data).decode("ascii")
    return f"data:{mime};base64,{encoded}"


def _sample_path(name: str) -> Path | None:
    if name not in _SAMPLE_FILES or Path(name).name != name:
        return None
    override = os.environ.get("LABELCHECK_SAMPLE_DIR")
    directory = Path(override) if override else Path(__file__).resolve().parents[2] / "samples"
    path = directory / name
    if not path.is_file():
        return None
    return path


def _render_batch(request: Request, *, error: str | None, job, missing: bool = False) -> Response:
    counts = request.app.state.batches.counts(job) if job is not None else None
    status = 404 if missing else 200
    return _TEMPLATES.TemplateResponse(
        request,
        "batch.html",
        {
            "page": "batch",
            "error": error,
            "job": job,
            "counts": counts,
            "missing": missing,
            "status_text": STATUS_TEXT,
            "keep_minutes": BATCH_JOB_SECONDS // 60,
            "batch_examples": BATCH_EXAMPLES,
            "sample_zip": BATCH_SAMPLE_ZIP,
        },
        status_code=status,
        headers=_NO_STORE,
    )


async def _batch_inputs(form) -> tuple[bytes, dict[str, bytes]]:
    zip_upload = _named_upload(form.get("zip"))
    if zip_upload is None:
        raise BatchError(CHOOSE_ZIP)
    try:
        data = await zip_upload.read()
    finally:
        await zip_upload.close()
    return read_zip(data)


def _named_upload(upload):
    if upload is None or not getattr(upload, "filename", None):
        return None
    return upload


def _image_type(name: str) -> str:
    suffix = Path(name).suffix.lower()
    if suffix in {".jpg", ".jpeg"}:
        return "image/jpeg"
    if suffix == ".webp":
        return "image/webp"
    if suffix in {".tif", ".tiff"}:
        return "image/tiff"
    return "image/png"


def _run_check(data: bytes, application: Application, *, reader, timeout: float, executor) -> Verification:
    kwargs = {"reader": reader} if reader is not None else {}
    future = executor.submit(verify_label, data, application, **kwargs)
    try:
        return future.result(timeout=timeout)
    except FuturesTimeoutError:
        logger.info("verify overall=error seconds=%.3f ocr_seconds=0.000", timeout)
        return Verification(error=CHECK_TIMEOUT, seconds=timeout)
    except Exception:
        logger.error("verify failed")
        return Verification(error=CHECK_FAILED)


def _blank_form() -> dict[str, str]:
    return {item["name"]: "" for item in FIELDS}


def _form_values(form) -> dict[str, str]:
    values = _blank_form()
    for name in values:
        raw = form.get(name)
        if isinstance(raw, str):
            values[name] = raw
    return values


def _application(values: dict[str, str]) -> Application:
    return Application(**values)


app = create_app()


def main() -> None:
    import os

    import uvicorn

    from PIL import Image

    from labelcheck.ocr import get_engine

    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(message)s"))
    logger.setLevel(logging.INFO)
    logger.addHandler(handler)
    logger.propagate = False
    reader = get_engine()
    # First inference pays for runtime setup. Do it before the port opens.
    reader(Image.new("RGB", (600, 200), "white"), use_det=True, use_cls=False, use_rec=True)
    logger.info("OCR models loaded")
    port = int(os.environ.get("PORT", "8000"))
    uvicorn.run(app, host="0.0.0.0", port=port)
