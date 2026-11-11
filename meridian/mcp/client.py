"""MCP client + registry. The harness never imports tool code - it only talks MCP."""
from __future__ import annotations

import itertools
import json
import subprocess
import sys
import threading
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from ..config import Settings
from .protocol import McpServer


class ToolError(RuntimeError):
    def __init__(self, msg: str, transient: bool = False):
        super().__init__(msg)
        self.transient = transient


class InProcessTransport:
    def __init__(self, server: McpServer):
        self.server = server

    def request(self, msg: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        return self.server.handle(json.loads(json.dumps(msg)))

    def close(self) -> None:
        pass


class StdioTransport:
    """Spawns `python -m meridian.mcp.stdio <server>` and speaks newline-delimited JSON-RPC."""

    def __init__(self, server_name: str, env: Optional[Dict[str, str]] = None):
        import os
        self.proc = subprocess.Popen([sys.executable, "-m", "meridian.mcp.stdio", server_name],
                                     stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, bufsize=1,
                                     env={**os.environ, **(env or {})})
        self._lock = threading.Lock()

    def request(self, msg: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        with self._lock:
            self.proc.stdin.write(json.dumps(msg) + "\n")
            self.proc.stdin.flush()
            if "id" not in msg:
                return None
            line = self.proc.stdout.readline()
            if not line:
                raise ToolError("mcp stdio server closed", transient=True)
            return json.loads(line)

    def close(self) -> None:
        try:
            self.proc.stdin.close()
            self.proc.wait(timeout=3)
        except Exception:  # noqa: BLE001
            self.proc.kill()


class HttpTransport:
    def __init__(self, url: str):
        import httpx
        self.url, self.c = url, httpx.Client(timeout=30)

    def request(self, msg):
        r = self.c.post(self.url, json=msg)
        r.raise_for_status()
        return r.json() if r.content else None

    def close(self):
        self.c.close()


class McpClient:
    def __init__(self, name: str, transport):
        self.name, self.t, self._ids = name, transport, itertools.count(1)
        self.info: Dict[str, Any] = {}

    def _rpc(self, method: str, params: Optional[Dict[str, Any]] = None) -> Any:
        resp = self.t.request({"jsonrpc": "2.0", "id": next(self._ids), "method": method, "params": params or {}})
        if resp is None:
            raise ToolError(f"{self.name}: no response")
        if "error" in resp:
            raise ToolError(f"{self.name}.{method}: {resp['error']['message']}")
        return resp["result"]

    def initialize(self) -> Dict[str, Any]:
        self.info = self._rpc("initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                                             "clientInfo": {"name": "meridian-harness", "version": "1.0"}})
        self.t.request({"jsonrpc": "2.0", "method": "notifications/initialized"})
        return self.info

    def list_tools(self) -> List[Dict[str, Any]]:
        return self._rpc("tools/list")["tools"]

    def call(self, tool: str, args: Dict[str, Any]) -> Any:
        res = self._rpc("tools/call", {"name": tool, "arguments": args})
        if res.get("isError"):
            sc = res.get("structuredContent") or {}
            raise ToolError(sc.get("error") or res["content"][0]["text"], transient=bool(sc.get("transient")))
        return res["structuredContent"]

    def read_resource(self, uri: str) -> Any:
        res = self._rpc("resources/read", {"uri": uri})
        return json.loads(res["contents"][0]["text"])


@dataclass
class ToolInfo:
    full: str          # "market.history"
    py_name: str       # "market_history" - the name exposed to sandbox code
    server: str
    name: str
    description: str
    schema: Dict[str, Any]
    read_only: bool
    sensitivity: str


class McpRegistry:
    """Discovers tools from every connected MCP server and routes calls."""

    def __init__(self):
        self.clients: Dict[str, McpClient] = {}
        self.tools: Dict[str, ToolInfo] = {}

    def connect(self, name: str, transport) -> None:
        c = McpClient(name, transport)
        c.initialize()
        self.clients[name] = c
        for t in c.list_tools():
            ann = t.get("annotations", {})
            full = f"{name}.{t['name']}"
            self.tools[full] = ToolInfo(full, f"{name}_{t['name']}", name, t["name"], t["description"],
                                        t["inputSchema"], ann.get("readOnlyHint", True),
                                        ann.get("x-meridian-sensitivity", "low"))

    def by_py_name(self, py: str) -> Optional[ToolInfo]:
        return next((t for t in self.tools.values() if t.py_name == py), None)

    def call(self, full: str, args: Dict[str, Any]) -> Any:
        info = self.tools.get(full)
        if info is None:
            raise ToolError(f"unknown tool {full}")
        return self.clients[info.server].call(info.name, args)

    def catalog(self) -> List[Dict[str, Any]]:
        return [{"tool": t.full, "python": f"tools.{t.py_name}", "description": t.description,
                 "args": {k: v.get("type") for k, v in t.schema.get("properties", {}).items()},
                 "required": t.schema.get("required", []), "read_only": t.read_only, "sensitivity": t.sensitivity}
                for t in self.tools.values()]

    def close(self) -> None:
        for c in self.clients.values():
            c.t.close()


def build_registry(settings: Settings) -> McpRegistry:
    from .servers import SERVER_NAMES, build_server
    reg = McpRegistry()
    for name in SERVER_NAMES:
        if settings.mcp_transport == "stdio":
            reg.connect(name, StdioTransport(name))
        else:
            reg.connect(name, InProcessTransport(build_server(name, settings)))
    return reg
