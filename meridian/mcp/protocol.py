"""Minimal, spec-shaped Model Context Protocol server (JSON-RPC 2.0).

Implements the subset the harness needs: initialize, ping, tools/list, tools/call,
resources/list, resources/read. Transport-agnostic: `handle()` takes/returns plain dicts, so the
same server runs in-process, over stdio (newline-delimited JSON) or behind HTTP (POST /mcp/{name}).
"""
from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

PROTOCOL_VERSION = "2025-06-18"

_TYPES = {"string": str, "integer": int, "number": (int, float), "boolean": bool, "array": list, "object": dict}


class McpError(Exception):
    def __init__(self, code: int, message: str):
        super().__init__(message)
        self.code, self.message = code, message


def validate_args(schema: Dict[str, Any], args: Dict[str, Any]) -> Dict[str, Any]:
    props = schema.get("properties", {})
    out = dict(args)
    for req in schema.get("required", []):
        if req not in out:
            raise McpError(-32602, f"missing required argument '{req}'")
    for k, v in list(out.items()):
        if k not in props:
            raise McpError(-32602, f"unknown argument '{k}'")
        spec = props[k]
        t = _TYPES.get(spec.get("type", ""), object)
        if isinstance(v, bool) and spec.get("type") in ("integer", "number"):
            raise McpError(-32602, f"'{k}' must be {spec['type']}")
        if not isinstance(v, t):
            raise McpError(-32602, f"'{k}' must be {spec.get('type')}")
        if "enum" in spec and v not in spec["enum"]:
            raise McpError(-32602, f"'{k}' must be one of {spec['enum']}")
        if isinstance(v, (int, float)):
            if "minimum" in spec and v < spec["minimum"]:
                raise McpError(-32602, f"'{k}' must be >= {spec['minimum']}")
            if "maximum" in spec and v > spec["maximum"]:
                raise McpError(-32602, f"'{k}' must be <= {spec['maximum']}")
    for k, spec in props.items():
        if k not in out and "default" in spec:
            out[k] = spec["default"]
    return out


@dataclass
class Tool:
    name: str
    description: str
    input_schema: Dict[str, Any]
    handler: Callable[[Dict[str, Any]], Any]
    read_only: bool = True
    sensitivity: str = "low"  # low | high  (high => policy requires a human approval path)

    def descriptor(self) -> Dict[str, Any]:
        return {"name": self.name, "description": self.description, "inputSchema": self.input_schema,
                "annotations": {"readOnlyHint": self.read_only, "x-meridian-sensitivity": self.sensitivity}}


@dataclass
class Resource:
    uri: str
    name: str
    description: str
    reader: Callable[[], Any]


@dataclass
class McpServer:
    name: str
    version: str = "1.0.0"
    tools: Dict[str, Tool] = field(default_factory=dict)
    resources: Dict[str, Resource] = field(default_factory=dict)

    def tool(self, name: str, description: str, properties: Dict[str, Any], required: Optional[List[str]] = None,
             read_only: bool = True, sensitivity: str = "low"):
        schema = {"type": "object", "properties": properties, "required": required or []}

        def deco(fn):
            self.tools[name] = Tool(name, description, schema, fn, read_only, sensitivity)
            return fn
        return deco

    def add_resource(self, uri: str, name: str, description: str, reader: Callable[[], Any]) -> None:
        self.resources[uri] = Resource(uri, name, description, reader)

    # ---- JSON-RPC ----------------------------------------------------------------------
    def handle(self, req: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        rid, method, params = req.get("id"), req.get("method"), req.get("params") or {}
        is_notification = "id" not in req
        try:
            result = self._dispatch(method, params)
        except McpError as e:
            return None if is_notification else {"jsonrpc": "2.0", "id": rid, "error": {"code": e.code, "message": e.message}}
        except Exception as e:  # noqa: BLE001 - surfaced as JSON-RPC internal error
            return None if is_notification else {"jsonrpc": "2.0", "id": rid,
                                                 "error": {"code": -32603, "message": f"{type(e).__name__}: {e}"}}
        return None if is_notification else {"jsonrpc": "2.0", "id": rid, "result": result}

    def _dispatch(self, method: Optional[str], p: Dict[str, Any]) -> Any:
        if method == "initialize":
            return {"protocolVersion": PROTOCOL_VERSION,
                    "capabilities": {"tools": {"listChanged": False}, "resources": {"listChanged": False}},
                    "serverInfo": {"name": self.name, "version": self.version}}
        if method in ("notifications/initialized", "notifications/cancelled"):
            return {}
        if method == "ping":
            return {}
        if method == "tools/list":
            return {"tools": [t.descriptor() for t in self.tools.values()]}
        if method == "tools/call":
            tool = self.tools.get(p.get("name", ""))
            if tool is None:
                raise McpError(-32602, f"unknown tool '{p.get('name')}'")
            try:
                args = validate_args(tool.input_schema, p.get("arguments") or {})
                data = tool.handler(args)
            except McpError:
                raise
            except Exception as e:  # tool-level failure => isError result, per MCP convention
                return {"content": [{"type": "text", "text": f"{type(e).__name__}: {e}"}], "isError": True,
                        "structuredContent": {"error": str(e), "error_type": type(e).__name__,
                                              "transient": bool(getattr(e, "transient", False))}}
            return {"content": [{"type": "text", "text": json.dumps(data, default=str)[:4000]}],
                    "structuredContent": data, "isError": False}
        if method == "resources/list":
            return {"resources": [{"uri": r.uri, "name": r.name, "description": r.description,
                                   "mimeType": "application/json"} for r in self.resources.values()]}
        if method == "resources/read":
            r = self.resources.get(p.get("uri", ""))
            if r is None:
                raise McpError(-32602, f"unknown resource '{p.get('uri')}'")
            return {"contents": [{"uri": r.uri, "mimeType": "application/json",
                                  "text": json.dumps(r.reader(), default=str)}]}
        raise McpError(-32601, f"method not found: {method}")

    # ---- stdio transport -----------------------------------------------------------------
    def serve_stdio(self) -> None:
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            try:
                req = json.loads(line)
            except json.JSONDecodeError:
                sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": None,
                                             "error": {"code": -32700, "message": "parse error"}}) + "\n")
                sys.stdout.flush()
                continue
            resp = self.handle(req)
            if resp is not None:
                sys.stdout.write(json.dumps(resp, default=str) + "\n")
                sys.stdout.flush()
