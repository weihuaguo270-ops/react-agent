"""Trace backend: mock fixtures or MCP trace server."""
from __future__ import annotations

import json
import os
import sys
from functools import lru_cache
from pathlib import Path
from typing import Any

_REPO = Path(__file__).resolve().parents[4]
_TRACES = _REPO / "fixtures" / "docs_troubleshoot" / "traces"
_MCP_SERVER = _REPO / "fixtures" / "docs_troubleshoot" / "mcp_trace_server.py"


def _backend_mode() -> str:
    return os.environ.get("REACT_AGENT_TRACE_BACKEND", "mock").strip().lower()


def _load_fixture(trace_id: str) -> dict[str, Any]:
    fp = _TRACES / f"{trace_id}.json"
    if not fp.is_file():
        return {"ok": False, "error": "trace_not_found", "trace_id": trace_id}
    data = json.loads(fp.read_text(encoding="utf-8"))
    data["ok"] = True
    data["backend"] = "mock"
    return data


@lru_cache(maxsize=1)
def _mcp_client():
    from react_agent.mcp_client import MCPClient

    py = sys.executable
    client = MCPClient(py, [str(_MCP_SERVER)])
    client.connect(timeout=10)
    client.discover_tools()
    return client


def _fetch_via_mcp(trace_id: str) -> dict[str, Any]:
    try:
        client = _mcp_client()
        raw = client.call_tool("get_trace", {"trace_id": trace_id})
        data = json.loads(raw or "{}")
        if isinstance(data, dict):
            data["backend"] = "mcp"
        return data
    except Exception as e:
        return {"ok": False, "error": str(e)[:200], "trace_id": trace_id, "backend": "mcp"}


def fetch_trace_bundle(trace_id: str) -> dict[str, Any]:
    """Return trace JSON bundle from mock fixtures or MCP server."""
    tid = (trace_id or "").strip()
    if not tid:
        return {"ok": False, "error": "empty_trace_id"}
    if _backend_mode() == "mcp":
        return _fetch_via_mcp(tid)
    return _load_fixture(tid)


def search_logs_via_backend(trace_id: str, *, limit: int = 10) -> dict[str, Any]:
    """查询配置的日志后端，并返回截断、结构化证据。"""
    tid = (trace_id or "").strip()
    if _backend_mode() == "mcp":
        try:
            client = _mcp_client()
            raw = client.call_tool("search_logs", {"trace_id": tid, "limit": limit})
            return json.loads(raw or "{}")
        except Exception as e:
            return {"ok": False, "error": str(e)[:200]}
    data = _load_fixture(tid)
    if not data.get("ok"):
        return data
    logs = list(data.get("logs") or [])[:limit]
    return {"ok": True, "trace_id": tid, "logs": logs, "count": len(logs)}


def trace_bundle_to_evidence_items(bundle: dict[str, Any]) -> list[dict[str, Any]]:
    """Convert backend bundle to evidence items (trace + optional logs)."""
    from react_agent.apps.docs_troubleshoot.evidence import parse_log_evidence, parse_trace_context

    items: list[dict[str, Any]] = []
    if not bundle.get("ok"):
        return items
    trace_payload = {
        "trace_id": bundle.get("trace_id"),
        "spans": bundle.get("spans") or [],
    }
    items.append(parse_trace_context(json.dumps(trace_payload, ensure_ascii=False)))
    logs = bundle.get("logs") or []
    if logs:
        items.append(
            parse_log_evidence("\n".join(logs), trace_id=str(bundle.get("trace_id") or ""))
        )
    meta = items[0] if items else {}
    if isinstance(meta, dict):
        meta["trace_backend"] = bundle.get("backend", _backend_mode())
    return items
