"""Tamper-evident audit trail: append-only JSONL where every record commits to the previous one
(hash chain). `verify()` detects edited, removed or re-ordered records. Safe across processes
(API + Celery workers) via an flock around read-last/append."""
from __future__ import annotations

import hashlib
import json
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

try:  # POSIX: cross-process lock (API + Celery workers). Windows: in-process lock (use the thread job backend).
    import fcntl
except ImportError:  # pragma: no cover
    fcntl = None
_LOCK = threading.Lock()

GENESIS = "0" * 64


def _digest(prev: str, body: Dict[str, Any]) -> str:
    return hashlib.sha256((prev + json.dumps(body, sort_keys=True, separators=(",", ":"), default=str)).encode()).hexdigest()


class AuditLog:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.touch(exist_ok=True)

    def append(self, run_id: str, type_: str, payload: Optional[Dict[str, Any]] = None, actor: str = "harness") -> Dict[str, Any]:
        with _LOCK, open(self.path, "a+b") as f:
            if fcntl:
                fcntl.flock(f, fcntl.LOCK_EX)
            try:
                f.seek(0, 2)
                size = f.tell()
                prev, seq = GENESIS, 0
                if size:
                    f.seek(max(0, size - 65536))
                    last = f.read().splitlines()[-1]
                    rec = json.loads(last)
                    prev, seq = rec["hash"], rec["seq"]
                body = {"seq": seq + 1, "ts": round(time.time(), 3), "run_id": run_id, "actor": actor,
                        "type": type_, "payload": payload or {}}
                rec = {**body, "prev": prev, "hash": _digest(prev, body)}
                f.write((json.dumps(rec, default=str) + "\n").encode())
                f.flush()
            finally:
                if fcntl:
                    fcntl.flock(f, fcntl.LOCK_UN)
        return rec

    def _read(self) -> List[Dict[str, Any]]:
        with open(self.path, "rb") as f:
            return [json.loads(l) for l in f.read().splitlines() if l.strip()]

    def events(self, run_id: str) -> List[Dict[str, Any]]:
        return [r for r in self._read() if r["run_id"] == run_id]

    def verify(self) -> Tuple[bool, Optional[int], int]:
        """-> (ok, first_bad_seq, n_records)"""
        prev, n = GENESIS, 0
        try:
            recs = self._read()
        except json.JSONDecodeError:
            return False, 0, 0
        for r in recs:
            n += 1
            body = {k: r[k] for k in ("seq", "ts", "run_id", "actor", "type", "payload")}
            if r.get("prev") != prev or r.get("hash") != _digest(prev, body) or r["seq"] != n:
                return False, r.get("seq"), len(recs)
            prev = r["hash"]
        return True, None, n
