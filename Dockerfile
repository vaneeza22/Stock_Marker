# API / Celery worker image (same image, different command)
FROM python:3.12-slim AS base
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 MERIDIAN_DATA_DIR=/data
WORKDIR /app
COPY pyproject.toml ./
COPY meridian ./meridian
RUN pip install .
COPY web ./web
RUN useradd -u 10001 -m meridian && mkdir /data && chown meridian /data
USER meridian
EXPOSE 8000
CMD ["uvicorn", "meridian.api.app:app", "--host", "0.0.0.0", "--port", "8000"]
