"""Parent side of the sandbox: spawn, enforce wall-clock, bridge tool calls through a handler.

Backends
  local   subprocess with rlimits + network block (dev / CI; documented as NOT a hard boundary)
  docker  `docker run --network none --read-only --cap-drop ALL ...` (what we deploy on AWS Fargate/ECS)
"""
from __future__ import annotations

import json
import os
import queue
import signal
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

RUNNER = str(Path(__file__).with_name("runner.py"))
ToolHandler = Callable[[str, Dict[str, Any]], Any]


@dataclass
class SandboxResult:
    ok: bool
    emits: List[Dict[str, Any]] = field(default_factory=list)
    stdout: str = ""
    error: Optional[Dict[str, Any]] = None
    duration_s: float = 0.0
    tool_calls: int = 0
    killed: Optional[str] = None

    def error_text(self) -> str:
        if not self.error:
            return ""
        e = self.error
        frames = "\n".join(e.get("frames", []))
        return f"{e.get('type')}: {e.get('message')}\n{frames}".strip()


class Sandbox:
    def __init__(self, backend: str = "local", timeout_s: float = 25, mem_mb: int = 2048,
                 image: str = "meridian-sandbox:latest"):
        self.backend, self.timeout_s, self.mem_mb, self.image = backend, timeout_s, mem_mb, image
        self._pool = ThreadPoolExecutor(max_workers=8)

    def _cmd(self) -> List[str]:
        if self.backend == "docker":
            return ["docker", "run", "--rm", "-i", "--network", "none", "--read-only",
                    "--tmpfs", "/tmp:rw,size=16m", "--memory", f"{self.mem_mb}m", "--cpus", "1",
                    "--pids-limit", "64", "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
                    "-u", "65534:65534", self.image, "python", "-I", "/sandbox/runner.py"]
        return [sys.executable, "-I", RUNNER]

    def run(self, code: str, tool_names: List[str], handler: ToolHandler) -> SandboxResult:
        t0 = time.time()
        env = {"PATH": os.environ.get("PATH", ""), "OPENBLAS_NUM_THREADS": "1", "OMP_NUM_THREADS": "1",
               "MKL_NUM_THREADS": "1", "HOME": "/nonexistent", "LANG": "C.UTF-8", "PYTHONIOENCODING": "utf-8"}
        if os.name == "nt":  # Windows needs these for the interpreter to start
            for k in ("SYSTEMROOT", "TEMP", "TMP", "PATHEXT"):
                if k in os.environ:
                    env[k] = os.environ[k]
        import tempfile
        with tempfile.TemporaryDirectory(prefix="mer-sbx-") as cwd:
            proc = subprocess.Popen(self._cmd(), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                    stderr=subprocess.DEVNULL, text=True, bufsize=1, cwd=cwd, env=env,
                                    start_new_session=True)
            q: "queue.Queue[Optional[str]]" = queue.Queue()

            def reader():
                for line in proc.stdout:
                    q.put(line)
                q.put(None)
            threading.Thread(target=reader, daemon=True).start()

            def send(o):
                try:
                    proc.stdin.write(json.dumps(o, default=str) + "\n")
                    proc.stdin.flush()
                except (BrokenPipeError, ValueError):
                    pass

            res = SandboxResult(ok=False)
            send({"init": {"code": code, "tools": tool_names,
                           "limits": {"cpu_s": int(self.timeout_s), "mem_mb": self.mem_mb}}})
            deadline = t0 + self.timeout_s
            try:
                while True:
                    remaining = deadline - time.time()
                    if remaining <= 0:
                        res.killed = f"wall-clock timeout ({self.timeout_s:.0f}s)"
                        res.error = {"type": "TimeoutError", "message": res.killed, "frames": []}
                        break
                    try:
                        line = q.get(timeout=min(remaining, 0.5))
                    except queue.Empty:
                        continue
                    if line is None:
                        if not res.error and res.ok is False and not any(m.get("kind") for m in []):
                            res.error = res.error or {"type": "SandboxCrash", "frames": [],
                                                      "message": f"sandbox exited unexpectedly (rc={proc.poll()}); "
                                                                 "likely memory/CPU limit"}
                        break
                    try:
                        msg = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    t = msg.get("t")
                    if t == "emit":
                        res.emits.append({"kind": msg["kind"], "data": msg["data"]})
                    elif t in ("call", "batch"):
                        ts = time.time()
                        send(self._serve(msg, handler, res))
                        deadline += time.time() - ts  # tool latency does not eat the compute budget
                    elif t == "done":
                        res.ok = bool(msg.get("ok"))
                        res.stdout = msg.get("stdout", "")
                        res.error = msg.get("error")
                        break
            finally:
                try:
                    if hasattr(os, "killpg"):
                        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
                    else:
                        proc.kill()
                except (ProcessLookupError, PermissionError, OSError):
                    pass
                proc.wait()
        res.duration_s = round(time.time() - t0, 3)
        return res

    def _serve(self, msg: Dict[str, Any], handler: ToolHandler, res: SandboxResult) -> Dict[str, Any]:
        tool = msg["tool"]
        try:
            if msg["t"] == "call":
                res.tool_calls += 1
                return {"t": "result", "id": msg["id"], "ok": True, "data": handler(tool, msg["args"])}
            arg_list = msg["args_list"][:40]
            res.tool_calls += len(arg_list)
            futs = [self._pool.submit(handler, tool, a) for a in arg_list]
            return {"t": "result", "id": msg["id"], "ok": True, "data": [f.result() for f in futs]}
        except Exception as e:  # noqa: BLE001 - surfaced to user code as RuntimeError
            return {"t": "result", "id": msg["id"], "ok": False, "error": f"{type(e).__name__}: {e}"}
