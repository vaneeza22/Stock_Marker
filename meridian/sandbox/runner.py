"""Sandbox child process. Self-contained on purpose: started as `python -I runner.py`, so it cannot
import the `meridian` package (and neither can user code).

Protocol (newline-delimited JSON on private dup'd fds; fd 0/1 are re-pointed at /dev/null):
  parent -> child  {"init": {...}}                      first line
  child  -> parent {"t":"call","id":1,"tool":"market_history","args":{}}
  child  -> parent {"t":"batch","id":2,"tool":"...","args_list":[...]}
  parent -> child  {"t":"result","id":1,"ok":true,"data":...}
  child  -> parent {"t":"emit","kind":"chart|table|metrics|note|signal|result","data":...}
  child  -> parent {"t":"done","ok":true,"stdout":"..."} | {"t":"done","ok":false,"error":{...}}
"""
import builtins
import json
import os
import sys
import traceback

PROTO_OUT = os.fdopen(os.dup(1), "w", buffering=1)
PROTO_IN = os.fdopen(os.dup(0), "r")
_dn = os.open(os.devnull, os.O_RDWR)
os.dup2(_dn, 0)
os.dup2(_dn, 1)

ALLOWED = {"math", "statistics", "json", "datetime", "collections", "itertools", "functools", "re", "decimal",
           "fractions", "random", "numpy", "pandas", "typing", "dataclasses"}
MAX_EMIT_BYTES = 3_000_000
_emitted = 0


def send(obj):
    PROTO_OUT.write(json.dumps(obj, default=_default, allow_nan=False) + "\n")
    PROTO_OUT.flush()


def _default(o):
    try:
        import numpy as np
        if isinstance(o, np.generic):
            return o.item()
        if isinstance(o, np.ndarray):
            return o.tolist()
    except Exception:
        pass
    try:
        import pandas as pd
        if isinstance(o, pd.Series):
            return o.tolist()
        if isinstance(o, pd.DataFrame):
            return o.to_dict("records")
        if isinstance(o, pd.Timestamp):
            return o.isoformat()
    except Exception:
        pass
    return str(o)


def _clean(o):
    """Replace NaN/inf (invalid JSON) with None, recursively, after numpy/pandas conversion."""
    import math
    o = json.loads(json.dumps(o, default=_default, allow_nan=True))

    def walk(x):
        if isinstance(x, float) and (math.isnan(x) or math.isinf(x)):
            return None
        if isinstance(x, list):
            return [walk(i) for i in x]
        if isinstance(x, dict):
            return {k: walk(v) for k, v in x.items()}
        return x
    return walk(o)


def read_msg():
    line = PROTO_IN.readline()
    if not line:
        os._exit(3)
    return json.loads(line)


def apply_limits(lim):
    try:
        import resource
        cpu = int(lim.get("cpu_s", 20))
        resource.setrlimit(resource.RLIMIT_CPU, (cpu, cpu + 1))
        mem = int(lim.get("mem_mb", 2048)) * 1024 * 1024
        resource.setrlimit(resource.RLIMIT_AS, (mem, mem))
        resource.setrlimit(resource.RLIMIT_FSIZE, (0, 0))      # cannot write files
        resource.setrlimit(resource.RLIMIT_NOFILE, (64, 64))
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        try:
            resource.setrlimit(resource.RLIMIT_NPROC, (32, 32))
        except Exception:
            pass
    except ImportError:  # non-POSIX: wall-clock timeout in the parent still applies
        pass


def block_network():
    import socket

    def _no(*a, **k):
        raise PermissionError("network access is disabled in the sandbox")
    socket.socket = _no
    socket.create_connection = _no
    socket.getaddrinfo = _no
    socket.gethostbyname = _no


class _Stdout:
    def __init__(self):
        self.parts, self.n = [], 0

    def write(self, s):
        if self.n < 20000:
            self.parts.append(s)
            self.n += len(s)
        return len(s)

    def flush(self):
        pass


class Tools:
    """`tools.market_history(symbol='AAPL', days=90)` -> parent -> policy -> MCP -> result."""

    def __init__(self, names):
        self._names = set(names)
        self._id = 0

    def _rpc(self, msg):
        self._id += 1
        msg["id"] = self._id
        send(msg)
        r = read_msg()
        if not r.get("ok"):
            raise RuntimeError(r.get("error", "tool failed"))
        return r["data"]

    def __getattr__(self, name):
        if name.startswith("_") or name not in self._names:
            raise AttributeError(f"unknown tool '{name}'. Available: {sorted(self._names)}")

        def call(**kw):
            return self._rpc({"t": "call", "tool": name, "args": kw})
        call.__name__ = name
        return call

    def map(self, name, args_list):
        """Programmatic fan-out: one round-trip, the harness runs the calls concurrently."""
        if name not in self._names:
            raise AttributeError(f"unknown tool '{name}'")
        return self._rpc({"t": "batch", "tool": name, "args_list": list(args_list)})


def emit(kind, data):
    global _emitted
    data = _clean(data)
    _emitted += len(json.dumps(data))
    if _emitted > MAX_EMIT_BYTES:
        raise RuntimeError("output too large")
    send({"t": "emit", "kind": kind, "data": data})


def build_namespace(tool_names):
    import numpy as np
    import pandas as pd

    real_import = builtins.__import__

    def safe_import(name, globals=None, locals=None, fromlist=(), level=0):
        if level or name.split(".")[0] not in ALLOWED:
            raise ImportError(f"import of '{name}' is not allowed in the sandbox")
        return real_import(name, globals, locals, fromlist, level)

    bad = {"open", "exec", "eval", "compile", "input", "breakpoint", "help", "exit", "quit", "globals",
           "locals", "vars", "getattr", "setattr", "delattr", "memoryview", "__import__"}
    safe_builtins = {k: v for k, v in vars(builtins).items() if k not in bad}
    safe_builtins["__import__"] = safe_import
    safe_builtins["getattr"] = lambda o, n, *d: (_ for _ in ()).throw(PermissionError("getattr is disabled"))

    def chart(kind, title, **spec):
        emit("chart", {"kind": kind, "title": title, **spec})

    def table(title, columns, rows, note=""):
        emit("table", {"title": title, "columns": list(columns), "rows": [list(r) for r in rows], "note": note})

    def metrics(items):
        emit("metrics", list(items))

    def note(text):
        emit("note", {"text": str(text)})

    def signal(symbol, **facts):
        emit("signal", {"symbol": symbol, **facts})

    def result(obj):
        emit("result", obj)

    ns = {"__builtins__": safe_builtins, "__name__": "analysis", "np": np, "pd": pd,
          "tools": Tools(tool_names), "chart": chart, "table": table, "metrics": metrics, "note": note,
          "signal": signal, "result": result}
    return ns


def user_frames(exc_tb, code_lines):
    out = []
    for fs in traceback.extract_tb(exc_tb):
        if fs.filename == "<analysis>":
            src = code_lines[fs.lineno - 1].strip() if 0 < fs.lineno <= len(code_lines) else ""
            out.append(f"line {fs.lineno}: {src}")
    return out


def main():
    init = read_msg()["init"]
    code = init["code"]
    lim = init.get("limits", {})
    ns = build_namespace(init["tools"])      # import numpy/pandas BEFORE limits and the network block
    apply_limits(lim)
    block_network()
    out = _Stdout()
    sys.stdout = out
    sys.stderr = out
    try:
        exec(compile(code, "<analysis>", "exec"), ns)
        send({"t": "done", "ok": True, "stdout": "".join(out.parts)})
    except BaseException as e:  # noqa: BLE001
        frames = user_frames(e.__traceback__, code.splitlines())
        send({"t": "done", "ok": False, "stdout": "".join(out.parts),
              "error": {"type": type(e).__name__, "message": str(e)[:500], "frames": frames[-4:]}})


if __name__ == "__main__":
    main()
