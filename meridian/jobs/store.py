"""SQLite persistence shared by the API process and Celery workers: runs, events, approvals,
paper holdings and conversation contexts. (Swap for RDS/Postgres on AWS - same interface.)"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager
from typing import Any, Dict, List, Optional

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs(id TEXT PRIMARY KEY, session_id TEXT, user TEXT, role TEXT, prompt TEXT,
  status TEXT, stage TEXT, progress REAL, attempt INTEGER DEFAULT 0, created REAL, updated REAL,
  result_json TEXT, error TEXT);
CREATE TABLE IF NOT EXISTS events(run_id TEXT, seq INTEGER, ts REAL, type TEXT, label TEXT, data_json TEXT,
  PRIMARY KEY(run_id, seq));
CREATE TABLE IF NOT EXISTS approvals(id TEXT PRIMARY KEY, run_id TEXT, symbol TEXT, side TEXT, qty REAL,
  price REAL, rationale TEXT, status TEXT, requested_by TEXT, decided_by TEXT, created REAL, decided_at REAL,
  execution_json TEXT);
CREATE TABLE IF NOT EXISTS holdings(symbol TEXT PRIMARY KEY, qty REAL, avg_cost REAL);
CREATE TABLE IF NOT EXISTS sessions(id TEXT PRIMARY KEY, context_json TEXT, updated REAL);
"""


class Store:
    def __init__(self, path):
        self.path = str(path)
        self._lock = threading.Lock()
        with self._conn() as c:
            c.executescript(SCHEMA)
            if c.execute("SELECT COUNT(*) FROM holdings").fetchone()[0] == 0:  # seed demo paper book
                c.executemany("INSERT INTO holdings VALUES(?,?,?)",
                              [("AAPL", 120, 180.0), ("MSFT", 60, 340.0), ("NVDA", 25, 210.0), ("CSCO", 300, 48.0)])

    @contextmanager
    def _conn(self):
        c = sqlite3.connect(self.path, timeout=30)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA journal_mode=WAL")
        try:
            yield c
            c.commit()
        finally:
            c.close()

    # ---- runs -------------------------------------------------------------------------
    def create_run(self, prompt: str, user: str, role: str, session_id: Optional[str] = None) -> str:
        rid = "run_" + uuid.uuid4().hex[:10]
        now = time.time()
        with self._lock, self._conn() as c:
            c.execute("INSERT INTO runs(id,session_id,user,role,prompt,status,stage,progress,created,updated)"
                      " VALUES(?,?,?,?,?,?,?,?,?,?)",
                      (rid, session_id or "s_" + uuid.uuid4().hex[:8], user, role, prompt, "queued", "queued", 0.0, now, now))
        return rid

    def update_run(self, rid: str, **kw) -> None:
        if "result" in kw:
            kw["result_json"] = json.dumps(kw.pop("result"), default=str)
        kw["updated"] = time.time()
        cols = ",".join(f"{k}=?" for k in kw)
        with self._lock, self._conn() as c:
            c.execute(f"UPDATE runs SET {cols} WHERE id=?", (*kw.values(), rid))

    def get_run(self, rid: str, with_events: bool = True) -> Optional[Dict[str, Any]]:
        with self._conn() as c:
            r = c.execute("SELECT * FROM runs WHERE id=?", (rid,)).fetchone()
            if not r:
                return None
            d = dict(r)
            d["result"] = json.loads(d.pop("result_json")) if d.get("result_json") else None
            if with_events:
                d["events"] = self.events(rid)
        return d

    def list_runs(self, limit: int = 20) -> List[Dict[str, Any]]:
        with self._conn() as c:
            rows = c.execute("SELECT id,session_id,prompt,status,stage,progress,created,role FROM runs"
                             " ORDER BY created DESC LIMIT ?", (limit,)).fetchall()
        return [dict(r) for r in rows]

    def add_event(self, rid: str, type_: str, label: str, data: Optional[Dict[str, Any]] = None) -> int:
        with self._lock, self._conn() as c:
            seq = c.execute("SELECT COALESCE(MAX(seq),0)+1 FROM events WHERE run_id=?", (rid,)).fetchone()[0]
            c.execute("INSERT INTO events VALUES(?,?,?,?,?,?)",
                      (rid, seq, time.time(), type_, label, json.dumps(data or {}, default=str)))
        return seq

    def events(self, rid: str, after: int = 0) -> List[Dict[str, Any]]:
        with self._conn() as c:
            rows = c.execute("SELECT * FROM events WHERE run_id=? AND seq>? ORDER BY seq", (rid, after)).fetchall()
        return [{"seq": r["seq"], "ts": r["ts"], "type": r["type"], "label": r["label"],
                 "data": json.loads(r["data_json"])} for r in rows]

    # ---- sessions (context persistence across workers) ---------------------------------
    def save_session(self, sid: str, ctx: Dict[str, Any]) -> None:
        with self._lock, self._conn() as c:
            c.execute("INSERT OR REPLACE INTO sessions VALUES(?,?,?)", (sid, json.dumps(ctx), time.time()))

    def load_session(self, sid: str) -> Optional[Dict[str, Any]]:
        with self._conn() as c:
            r = c.execute("SELECT context_json FROM sessions WHERE id=?", (sid,)).fetchone()
        return json.loads(r["context_json"]) if r else None

    # ---- portfolio & approvals ----------------------------------------------------------
    def holdings(self) -> List[Dict[str, Any]]:
        with self._conn() as c:
            return [dict(r) for r in c.execute("SELECT * FROM holdings ORDER BY symbol")]

    def create_approval(self, run_id: str, symbol: str, side: str, qty: float, price: float,
                        rationale: str, requested_by: str) -> str:
        aid = "apr_" + uuid.uuid4().hex[:8]
        with self._lock, self._conn() as c:
            c.execute("INSERT INTO approvals VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                      (aid, run_id, symbol, side, qty, price, rationale, "pending", requested_by, None,
                       time.time(), None, None))
        return aid

    def list_approvals(self, status: Optional[str] = None) -> List[Dict[str, Any]]:
        with self._conn() as c:
            q = "SELECT * FROM approvals" + (" WHERE status=?" if status else "") + " ORDER BY created DESC"
            rows = c.execute(q, (status,) if status else ()).fetchall()
        return [dict(r) for r in rows]

    def get_approval(self, aid: str) -> Optional[Dict[str, Any]]:
        with self._conn() as c:
            r = c.execute("SELECT * FROM approvals WHERE id=?", (aid,)).fetchone()
        return dict(r) if r else None

    def decide_approval(self, aid: str, decision: str, by: str) -> Dict[str, Any]:
        """Human decision. Approve => paper-fill at the recorded reference price (never a real order)."""
        with self._lock, self._conn() as c:
            a = c.execute("SELECT * FROM approvals WHERE id=?", (aid,)).fetchone()
            if not a:
                raise KeyError(aid)
            if a["status"] != "pending":
                raise ValueError(f"approval already {a['status']}")
            if decision not in ("approved", "rejected"):
                raise ValueError("decision must be approved|rejected")
            exe = None
            if decision == "approved":
                h = c.execute("SELECT * FROM holdings WHERE symbol=?", (a["symbol"],)).fetchone()
                q0, c0 = (h["qty"], h["avg_cost"]) if h else (0.0, 0.0)
                sgn = 1 if a["side"] == "buy" else -1
                q1 = q0 + sgn * a["qty"]
                if q1 < -1e-9:
                    raise ValueError("paper book cannot go short")
                cost1 = ((q0 * c0 + a["qty"] * a["price"]) / q1) if sgn == 1 and q1 > 0 else c0
                if q1 <= 1e-9:
                    c.execute("DELETE FROM holdings WHERE symbol=?", (a["symbol"],))
                else:
                    c.execute("INSERT OR REPLACE INTO holdings VALUES(?,?,?)", (a["symbol"], q1, cost1))
                exe = {"mode": "PAPER", "filled_qty": a["qty"], "fill_price": a["price"], "new_qty": q1}
            c.execute("UPDATE approvals SET status=?, decided_by=?, decided_at=?, execution_json=? WHERE id=?",
                      (decision, by, time.time(), json.dumps(exe) if exe else None, aid))
        return self.get_approval(aid)
