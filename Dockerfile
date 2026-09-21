FROM python:3.11-slim

# libGL and glib are required by opencv, which RapidOCR imports.
RUN apt-get update \
 && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /srv
COPY pyproject.toml .
COPY src ./src
RUN pip install --no-cache-dir .

# The build may download the pinned PP-OCRv5 weights. A running container does not.
ENV LABELCHECK_MODEL_DIR=/opt/models \
    ORT_DISABLE_TELEMETRY=1 \
    PYTHONUNBUFFERED=1 \
    OMP_NUM_THREADS=2
RUN python -c "from labelcheck.ocr import download_models, weights_present; download_models(); assert weights_present()"

RUN useradd --create-home appuser \
 && chown -R appuser /opt/models
USER appuser

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/')"
# One process so the model loaded at startup serves every request.
CMD ["python", "-m", "labelcheck"]
