"""Job execution shared by the thread backend and Celery workers: progress tracking, retries, saved results."""
from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict

from ..harness.context import ContextManager
from ..harness.core import RunRequest, TransientError
from ..services import get_services

PROGRESS = {"request.received": .05, "policy.request": .10, "context.built": .15, "plan.created": .30,
            "code.rejected": .32, "sandbox.start": .40, "sandbox.done": .85, "plan.repair": .35,
            "debate.done": .92, "context.updated": .97, "run.completed": 1.0}
_pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="meridian-job")


def execute_run(run_id: str) -> None:
    """Runs one analysis. Raises TransientError for retryable failures; everything else is recorded on the run."""
    svc = get_services()
    run = svc.store.get_run(run_id, with_events=False)
    if run is None or run["status"] in ("completed", "denied"):
        return  # idempotent under at-least-once delivery
    st = svc.store
    prog = {"v": 0.05, "tool_calls": 0}

    def on_event(type_: str, label: str, data: Dict[str, Any]) -> None:
        if type_ == "tool.call":
            prog["tool_calls"] += 1
            prog["v"] = min(0.80, max(prog["v"], 0.40 + 0.02 * prog["tool_calls"]))
        else:
            prog["v"] = max(prog["v"], PROGRESS.get(type_, prog["v"]))
        st.add_event(run_id, type_, label, {k: v for k, v in data.items() if k != "code" or type_ == "plan.created"})
        st.update_run(run_id, stage=label, progress=round(prog["v"], 2), status="running")

    sess = st.load_session(run["session_id"])
    ctx = ContextManager.from_dict(sess) if sess else svc.harness.new_context()
    try:
        out = svc.harness.run(RunRequest(run["prompt"], run["role"], run["user"], run_id, run["session_id"]), ctx, on_event)
    except TransientError as e:
        st.add_event(run_id, "job.retry", "Transient failure - will retry", {"error": str(e)[:300]})
        st.update_run(run_id, status="retrying", stage="retrying after transient failure", attempt=run["attempt"] + 1)
        raise
    except Exception as e:  # noqa: BLE001 - never leave a run hanging
        st.add_event(run_id, "run.failed", f"{type(e).__name__}: {e}"[:200], {})
        st.update_run(run_id, status="failed", stage="failed", progress=1.0, error=f"{type(e).__name__}: {e}"[:500])
        return
    st.save_session(run["session_id"], ctx.to_dict())
    st.update_run(run_id, status=out["status"], stage=out["status"], progress=1.0, result=out,
                  error=out.get("error"))


def execute_with_retries(run_id: str, max_retries: int = 3, base_delay: float = 1.0) -> None:
    for attempt in range(max_retries + 1):
        try:
            execute_run(run_id)
            return
        except TransientError:
            if attempt == max_retries:
                get_services().store.update_run(run_id, status="failed", stage="failed", progress=1.0,
                                                error="transient failure persisted after retries")
                return
            time.sleep(base_delay * 2 ** attempt)


def submit(run_id: str) -> str:
    """Dispatch to Celery (production) or an in-process thread pool (dev). Returns the backend used."""
    svc = get_services()
    if svc.settings.job_backend == "celery":
        from .tasks import run_analysis
        run_analysis.delay(run_id)
        svc.store.add_event(run_id, "job.queued", "Queued on Celery (Redis)", {})
        return "celery"
    _pool.submit(execute_with_retries, run_id)
    svc.store.add_event(run_id, "job.queued", "Queued on in-process worker pool", {})
    return "thread"
