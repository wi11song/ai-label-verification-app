"""One page: upload a label, enter the application, press Verify, read the result there."""

import logging
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FuturesTimeoutError
from pathlib import Path

from starlette.applications import Starlette
from starlette.formparsers import MultiPartException
from starlette.requests import Request
from starlette.responses import Response
from starlette.routing import Route
from starlette.templating import Jinja2Templates

from labelcheck.models import FIELD_LABELS, Application
from labelcheck.quality import IMAGE_TOO_LARGE
from labelcheck.thresholds import MAX_IMAGE_BYTES, SINGLE_LABEL_TIMEOUT
from labelcheck.verify import Verification, verify_label

logger = logging.getLogger("labelcheck")

CHOOSE_PHOTO = "Choose a label photo, then press Verify."
CHECK_FAILED = "Verification could not finish. Try again."
CHECK_TIMEOUT = "Verification took too long. Try again, or use a smaller image."
BOLD_NOTE = "Bold type on “GOVERNMENT WARNING:” was not checked by this prototype."

STATUS_TEXT = {
    "pass": "Pass",
    "fail": "Fail",
    "needs_review": "Needs review",
    "match": "Match",
    "mismatch": "Does not match",
    "unreadable": "Unreadable",
}

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
        "hint": "Leave blank to use the standard warning.",
    },
    {
        "name": "bottler",
        "label": "Bottler / producer",
        "required": False,
        "multiline": True,
        "placeholder": "",
        "hint": "Optional.",
    },
    {
        "name": "country_of_origin",
        "label": "Country of origin",
        "required": False,
        "multiline": False,
        "placeholder": "",
        "hint": "Optional. Use this for imports.",
    },
)

_TEMPLATES = Jinja2Templates(directory=str(Path(__file__).resolve().parent / "templates"))
_EXECUTOR = ThreadPoolExecutor(max_workers=2, thread_name_prefix="labelcheck")
_NO_STORE = {"Cache-Control": "no-store"}


def create_app(*, reader=None, timeout: float = SINGLE_LABEL_TIMEOUT) -> Starlette:
    async def home(request: Request) -> Response:
        return _render(request, _blank_form(), None)

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
        result = _run_check(data, _application(values), reader=reader, timeout=timeout)
        return _render(request, values, result)

    return Starlette(
        routes=[
            Route("/", home, methods=["GET"]),
            Route("/verify", check, methods=["POST"]),
        ]
    )


def _render(request: Request, values: dict[str, str], result: Verification | None) -> Response:
    return _TEMPLATES.TemplateResponse(
        request,
        "check.html",
        {
            "fields": FIELDS,
            "values": values,
            "result": result,
            "labels": FIELD_LABELS,
            "status_text": STATUS_TEXT,
            "bold_note": BOLD_NOTE,
        },
        headers=_NO_STORE,
    )


def _run_check(data: bytes, application: Application, *, reader, timeout: float) -> Verification:
    kwargs = {"reader": reader} if reader is not None else {}
    future = _EXECUTOR.submit(verify_label, data, application, **kwargs)
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
