"""Celery application + tasks.

  celery -A meridian.jobs.tasks worker -l info -c 4
  celery -A meridian.jobs.tasks beat   -l info      # periodic cache warm-up
"""
from __future__ import annotations

from celery import Celery
from celery.schedules import crontab

from ..config import get_settings
from ..harness.core import TransientError
from .runner import execute_run

_s = get_settings()
app = Celery("meridian", broker=_s.redis_url, backend=_s.redis_url)
app.conf.update(
    task_acks_late=True,                 # a crashed worker's task is redelivered...
    worker_prefetch_multiplier=1,        # ...and long analyses don't starve short ones
    task_time_limit=180, task_soft_time_limit=150,
    task_track_started=True, result_expires=3600,
    broker_connection_retry_on_startup=True,
    beat_schedule={"warm-universe-cache": {"task": "meridian.warm_cache", "schedule": crontab(minute="*/5")}},
)


@app.task(name="meridian.run_analysis", bind=True, autoretry_for=(TransientError,), retry_backoff=2,
          retry_backoff_max=30, retry_jitter=True, max_retries=3)
def run_analysis(self, run_id: str) -> str:
    execute_run(run_id)          # progress + results are persisted in the shared Store, not just the result backend
    return run_id


@app.task(name="meridian.warm_cache")
def warm_cache() -> int:
    from ..services import get_services
    svc = get_services()
    n = 0
    for sym in svc.settings.universe:
        svc.provider.history(sym, 400)
        n += 1
    return n
