.PHONY: dev test lint up worker smoke
dev:    ; MERIDIAN_PROVIDER=synthetic uvicorn meridian.api.app:app --reload --port 8000
test:   ; pytest
lint:   ; ruff check .
up:     ; docker compose up --build
worker: ; celery -A meridian.jobs.tasks worker -l info -c 4
smoke:  ; python scripts/smoke_celery.py
