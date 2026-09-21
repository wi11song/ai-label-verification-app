"""In-memory batch jobs. One bad row does not stop the rest.

Images and application rows live only until the job expires.
"""

import csv
import io
import logging
import secrets
import threading
import time
import zipfile
from concurrent.futures import Future, ThreadPoolExecutor, wait, FIRST_COMPLETED
from dataclasses import dataclass, field
from pathlib import PurePosixPath

from labelcheck.models import Application
from labelcheck.thresholds import (
    BATCH_JOB_SECONDS,
    BATCH_MAX_ITEMS,
    BATCH_ZIP_BYTES,
    MAX_IMAGE_BYTES,
    SINGLE_LABEL_TIMEOUT,
)
from labelcheck.quality import IMAGE_TOO_LARGE
from labelcheck.verify import CHECK_FAILED, CHECK_TIMEOUT, MISSING_APPLICATION, Verification, verify_label

logger = logging.getLogger("labelcheck")

QUEUED = "queued"
RUNNING = "running"
ERROR = "error"

_REQUIRED_COLUMNS = ("image", "brand_name", "class_type", "alcohol_content", "net_contents")
_OPTIONAL_COLUMNS = ("government_warning", "bottler", "country_of_origin")
_IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".tif", ".tiff"}
_REQUIRED_FIELDS = ("brand_name", "class_type", "alcohol_content", "net_contents")

CSV_COLUMNS = (
    "The CSV needs columns named image, brand_name, class_type, alcohol_content, and net_contents."
)
TOO_MANY = f"A batch can include at most {BATCH_MAX_ITEMS} labels."
EMPTY_CSV = "The CSV has no labels to check."
NOT_UTF8 = "This CSV is not UTF-8 text."
NO_HEADER = "This CSV has no header row."
ZIP_TOO_LARGE = "This zip is too large. Use a file under 200 MB."
ZIP_UNSAFE = "This zip contains an unsafe file path."
ZIP_UNREADABLE = "This zip could not be read."
ZIP_NEEDS_CSV = "The zip needs one CSV of application rows."
ZIP_ONE_CSV = "The zip should contain one CSV of application rows."
FILE_TOO_LARGE = "A file in this zip is too large."
CHOOSE_INPUT = "Choose a CSV and the label photos, or one zip that contains both."
BOTH_INPUTS = "Choose a zip, or a CSV with photos, not both."
DUPLICATE_NAME = "Two photos use the same file name. Use one name per photo."


class BatchError(Exception):
    """The upload cannot start. The message is safe to show."""


@dataclass
class BatchItem:
    index: int
    image_name: str
    brand: str
    state: str
    summary: str
    application: Application | None = None
    result: Verification | None = None


@dataclass
class BatchJob:
    id: str
    created: float
    items: list[BatchItem]
    images: dict[str, bytes] = field(default_factory=dict)
    done: bool = False
    lock: threading.Lock = field(default_factory=threading.Lock)


def build_items(csv_bytes: bytes, images: dict[str, bytes]) -> list[BatchItem]:
    """Turn a CSV and uploaded photos into rows. Does not read the photos."""
    items = []
    for index, row in enumerate(_rows(csv_bytes)):
        image_name = row.get("image", "").strip()
        brand = row.get("brand_name", "").strip()
        if not image_name:
            items.append(BatchItem(index, "", brand, ERROR, "This row has no image file name."))
            continue
        application = _application(row)
        if _missing_required(application):
            items.append(BatchItem(index, image_name, brand, ERROR, MISSING_APPLICATION, application))
            continue
        photo = images.get(image_name)
        if photo is None:
            items.append(
                BatchItem(
                    index,
                    image_name,
                    brand,
                    ERROR,
                    f"No photo named {image_name} was included.",
                    application,
                )
            )
            continue
        if len(photo) > MAX_IMAGE_BYTES:
            items.append(BatchItem(index, image_name, brand, ERROR, IMAGE_TOO_LARGE, application))
            continue
        items.append(BatchItem(index, image_name, brand, QUEUED, "Waiting.", application))
    return items


def read_zip(data: bytes) -> tuple[bytes, dict[str, bytes]]:
    """Return the CSV and image files from a zip. Rejects unsafe paths before reading them."""
    if len(data) > BATCH_ZIP_BYTES:
        raise BatchError(ZIP_TOO_LARGE)
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise BatchError(ZIP_UNREADABLE) from exc
    csv_bytes = None
    images: dict[str, bytes] = {}
    with archive:
        for info in archive.infolist():
            if info.is_dir():
                continue
            _reject_unsafe(info.filename)
            name = PurePosixPath(info.filename.replace("\\", "/")).name
            if not name or name.startswith(".") or name == ".DS_Store":
                continue
            suffix = PurePosixPath(name).suffix.lower()
            if suffix == ".csv":
                if csv_bytes is not None:
                    raise BatchError(ZIP_ONE_CSV)
                csv_bytes = _read_member(archive, info, BATCH_ZIP_BYTES)
                continue
            if suffix not in _IMAGE_SUFFIXES:
                continue
            if name in images:
                raise BatchError(DUPLICATE_NAME)
            if info.file_size > MAX_IMAGE_BYTES:
                raise BatchError(FILE_TOO_LARGE)
            images[name] = _read_member(archive, info, MAX_IMAGE_BYTES)
    if csv_bytes is None:
        raise BatchError(ZIP_NEEDS_CSV)
    return csv_bytes, images


class BatchStore:
    """Holds jobs in this process and runs at most two checks at a time."""

    def __init__(
        self,
        executor: ThreadPoolExecutor,
        *,
        reader=None,
        timeout: float = SINGLE_LABEL_TIMEOUT,
        lifetime: float = BATCH_JOB_SECONDS,
    ) -> None:
        self._executor = executor
        self._reader = reader
        self._timeout = timeout
        self._lifetime = lifetime
        self._jobs: dict[str, BatchJob] = {}
        self._lock = threading.Lock()

    def create(self, csv_bytes: bytes, images: dict[str, bytes]) -> BatchJob:
        self.purge()
        items = build_items(csv_bytes, images)
        needed = {item.image_name for item in items if item.state == QUEUED}
        job = BatchJob(
            id=secrets.token_urlsafe(16),
            created=time.monotonic(),
            items=items,
            images={name: images[name] for name in needed},
        )
        with self._lock:
            self._jobs[job.id] = job
        threading.Thread(target=self._drive, args=(job,), name=f"batch-{job.id[:8]}", daemon=True).start()
        logger.info("batch start items=%s", len(items))
        return job

    def get(self, job_id: str) -> BatchJob | None:
        self.purge()
        with self._lock:
            return self._jobs.get(job_id)

    def counts(self, job: BatchJob) -> dict[str, int]:
        with job.lock:
            return _counts(job)

    def snapshot(self, job: BatchJob) -> dict:
        with job.lock:
            counts = _counts(job)
            items = [
                {
                    "index": item.index,
                    "image": item.image_name,
                    "brand": item.brand,
                    "state": item.state,
                    "summary": item.summary,
                }
                for item in job.items
            ]
            done = job.done
        return {"done": done, "counts": counts, **{"items": items}}

    def purge(self) -> None:
        now = time.monotonic()
        with self._lock:
            expired = [job_id for job_id, job in self._jobs.items() if now - job.created >= self._lifetime]
            for job_id in expired:
                job = self._jobs.pop(job_id)
                with job.lock:
                    job.images.clear()
                    for item in job.items:
                        item.result = None
                    job.items.clear()

    def _drive(self, job: BatchJob) -> None:
        in_flight: dict[Future, tuple[BatchItem, float]] = {}
        pending = [item for item in list(job.items) if item.state == QUEUED]
        try:
            while pending or in_flight:
                if self._expired(job):
                    return
                while pending and len(in_flight) < 2:
                    item = pending.pop(0)
                    self._mark(job, item, state=RUNNING, summary="Checking this label.")
                    kwargs = {"reader": self._reader} if self._reader is not None else {}
                    photo = job.images.get(item.image_name, b"")
                    future = self._executor.submit(verify_label, photo, item.application, **kwargs)
                    in_flight[future] = (item, time.monotonic())
                if not in_flight:
                    break
                done, _ = wait(set(in_flight), timeout=0.05, return_when=FIRST_COMPLETED)
                now = time.monotonic()
                for future in list(in_flight):
                    item, started = in_flight[future]
                    if future in done:
                        in_flight.pop(future)
                        self._finish(job, item, future)
                    elif now - started >= self._timeout:
                        in_flight.pop(future)
                        future.add_done_callback(_retrieve)
                        logger.info("batch item state=error")
                        result = Verification(error=CHECK_TIMEOUT, seconds=self._timeout)
                        self._mark(job, item, state=ERROR, summary=CHECK_TIMEOUT, result=result)
        except Exception:
            logger.error("batch failed")
            for item in job.items:
                if item.state in {QUEUED, RUNNING}:
                    result = Verification(error=CHECK_FAILED)
                    self._mark(job, item, state=ERROR, summary=CHECK_FAILED, result=result)
        with job.lock:
            job.images.clear()
            job.done = True
        logger.info("batch done items=%s", len(job.items))

    def _finish(self, job: BatchJob, item: BatchItem, future: Future) -> None:
        try:
            result = future.result()
        except Exception:
            logger.error("batch item failed")
            result = Verification(error=CHECK_FAILED)
        if result.error:
            self._mark(job, item, state=ERROR, summary=result.error, result=result)
            return
        assert result.verdict is not None
        self._mark(
            job,
            item,
            state=result.verdict.overall.value,
            summary=result.verdict.summary,
            result=result,
        )

    def _mark(self, job: BatchJob, item: BatchItem, **changes) -> None:
        with job.lock:
            for name, value in changes.items():
                setattr(item, name, value)

    def _expired(self, job: BatchJob) -> bool:
        with self._lock:
            return job.id not in self._jobs


def _retrieve(future: Future) -> None:
    future.exception()


def _counts(job: BatchJob) -> dict[str, int]:
    counts = {"pass": 0, "fail": 0, "needs_review": 0, "error": 0, "queued": 0, "running": 0}
    for item in job.items:
        counts[item.state] = counts.get(item.state, 0) + 1
    finished = counts["pass"] + counts["fail"] + counts["needs_review"] + counts["error"]
    return {"total": len(job.items), "finished": finished, **counts}


def _rows(csv_bytes: bytes) -> list[dict[str, str]]:
    try:
        text = csv_bytes.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise BatchError(NOT_UTF8) from exc
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        raise BatchError(NO_HEADER)
    header = {(name or "").strip() for name in reader.fieldnames}
    if any(name not in header for name in _REQUIRED_COLUMNS):
        raise BatchError(CSV_COLUMNS)
    rows = []
    for raw in reader:
        if raw is None or all(not (value or "").strip() for value in raw.values()):
            continue
        rows.append({(key or "").strip(): (value or "").strip() for key, value in raw.items()})
        if len(rows) > BATCH_MAX_ITEMS:
            raise BatchError(TOO_MANY)
    if not rows:
        raise BatchError(EMPTY_CSV)
    return rows


def _application(row: dict[str, str]) -> Application:
    values = {name: row.get(name, "") for name in (*_REQUIRED_FIELDS, *_OPTIONAL_COLUMNS)}
    return Application(**values)


def _missing_required(application: Application) -> bool:
    return any(not getattr(application, name).strip() for name in _REQUIRED_FIELDS)


def _reject_unsafe(filename: str) -> None:
    parts = PurePosixPath(filename.replace("\\", "/")).parts
    if filename.startswith("/") or filename.startswith("\\") or ".." in parts:
        raise BatchError(ZIP_UNSAFE)


def _read_member(archive: zipfile.ZipFile, info: zipfile.ZipInfo, limit: int) -> bytes:
    chunks = []
    total = 0
    with archive.open(info) as handle:
        while True:
            block = handle.read(1024 * 1024)
            if not block:
                break
            total += len(block)
            if total > limit:
                raise BatchError(FILE_TOO_LARGE)
            chunks.append(block)
    return b"".join(chunks)
