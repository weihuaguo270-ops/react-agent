#!/usr/bin/env python3
"""Minimal stdio MCP server for trace/log fixtures (docs_troubleshoot eval)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

_TRACES = Path(__file__).resolve().parent / "traces"


def _load_trace(trace_id: str) -> dict:
    fp = _TRACES / f"{trace_id}.json"
    if not fp.is_file():
        return {"ok": False, "error": "trace_not_found", "trace_id": trace_id}
    data = json.loads(fp.read_text(encoding="utf-8"))
    data["ok"] = True
    return data


def _tool_get_trace(args: dict) -> str:
    tid = str(args.get("trace_id") or "").strip()
    return json.dumps(_load_trace(tid), ensure_ascii=False)


def _tool_search_logs(args: dict) -> str:
    tid = str(args.get("trace_id") or "").strip()
    data = _load_trace(tid)
    if not data.get("ok"):
        return json.dumps(data, ensure_ascii=False)
    logs = list(data.get("logs") or [])
    limit = int(args.get("limit") or 10)
    return json.dumps(
        {"ok": True, "trace_id": tid, "logs": logs[:limit], "count": len(logs)},
        ensure_ascii=False,
    )


_TOOLS = {
    "get_trace": {
        "description": "Fetch distributed trace by trace_id from trace store.",
        "inputSchema": {
            "type": "object",
            "properties": {"trace_id": {"type": "string"}},
            "required": ["trace_id"],
        },
        "handler": _tool_get_trace,
    },
    "search_logs": {
        "description": "Search log lines for a trace_id.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "trace_id": {"type": "string"},
                "limit": {"type": "integer"},
            },
            "required": ["trace_id"],
        },
        "handler": _tool_search_logs,
    },
}


def _respond(req_id, result=None, error=None) -> None:
    body: dict = {"jsonrpc": "2.0", "id": req_id}
    if error is not None:
        body["error"] = error
    else:
        body["result"] = result
    sys.stdout.write(json.dumps(body) + "\n")
    sys.stdout.flush()


def _handle(req: dict) -> None:
    req_id = req.get("id")
    method = req.get("method") or ""
    params = req.get("params") or {}

    if method == "initialize":
        _respond(
            req_id,
            {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "docs-troubleshoot-trace", "version": "0.1.0"},
            },
        )
        return

    if method == "notifications/initialized":
        return

    if method == "tools/list":
        tools = [
            {
                "name": name,
                "description": spec["description"],
                "inputSchema": spec["inputSchema"],
            }
            for name, spec in _TOOLS.items()
        ]
        _respond(req_id, {"tools": tools})
        return

    if method == "tools/call":
        name = (params.get("name") or "").strip()
        arguments = params.get("arguments") or {}
        spec = _TOOLS.get(name)
        if not spec:
            _respond(req_id, error={"code": -32601, "message": f"Unknown tool: {name}"})
            return
        text = spec["handler"](arguments)
        _respond(req_id, {"content": [{"type": "text", "text": text}]})
        return

    if req_id is not None:
        _respond(req_id, error={"code": -32601, "message": f"Unknown method: {method}"})


def main() -> None:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError:
            continue
        _handle(req)


if __name__ == "__main__":
    main()
