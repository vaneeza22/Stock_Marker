"""CI/ops smoke test: submit analyses to a RUNNING Celery worker and assert they complete."""
import sys
import time

from meridian.jobs.runner import submit
from meridian.services import get_services

PROMPTS = ["Analyze AMD", "Screen the tech universe for RSI below 45", "Compare NVDA vs AMD"]


def main() -> int:
    svc = get_services()
    ids = [svc.store.create_run(p, "ci", "analyst") for p in PROMPTS]
    for rid in ids:
        assert submit(rid) == "celery", "set MERIDIAN_JOBS=celery"
    deadline = time.time() + 90
    while time.time() < deadline:
        runs = [svc.store.get_run(i, with_events=False) for i in ids]
        if all(r["status"] in ("completed", "failed", "denied") for r in runs):
            break
        time.sleep(0.5)
    for r in runs:
        print(r["id"], r["status"], r["progress"])
    ok, _, n = svc.audit.verify()
    print("audit chain ok:", ok, "records:", n)
    return 0 if ok and all(r["status"] == "completed" for r in runs) else 1


if __name__ == "__main__":
    sys.exit(main())
