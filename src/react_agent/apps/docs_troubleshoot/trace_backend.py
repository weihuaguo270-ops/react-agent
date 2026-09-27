"""Trace backend: mock fixtures or MCP trace server."""
from __future__ import annotations

import json
import os
import re
import sys
from functools import lru_cache
from pathlib import Path
from typing import Any

_REPO = Path(__file__).resolve().parents[4]
_TRACES = _REPO / "fixtures" / "docs_troubleshoot" / "traces"
_MCP_SERVER = _REPO / "fixtures" / "docs_troubleshoot" / "mcp_trace_server.py"

# trace_id 会被拼进文件路径，且取值来自工具调用/HTTP 请求体。此前无任何校验，
# ``../../x`` 或 Windows 绝对路径（盘符）都能读到任意 *.json 并把内容回传给模型。
# 白名单 + 解析后包含校验双重约束。
_TRACE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


def _safe_trace_id(trace_id: str) -> str | None:
    """校验 trace_id 并确保解析后仍位于 traces 目录内。"""
    tid = (trace_id or "").strip()
    if not tid or not _TRACE_ID_RE.fullmatch(tid):
        return None
    if tid in {".", ".."}:
        return None
    try:
        candidate = (_TRACES / f"{tid}.json").resolve()
        root = _TRACES.resolve()
    except OSError:
        return None
    if candidate != root and root not in candidate.parents:
        return None
    return tid


def _backend_mode() -> str:
    return os.environ.get("REACT_AGENT_TRACE_BACKEND", "mock").strip().lower()


def _load_fixture(trace_id: str) -> dict[str, Any]:
    safe = _safe_trace_id(trace_id)
    if safe is None:
        return {"ok": False, "error": "invalid_trace_id", "trace_id": str(trace_id)[:64]}
    fp = _TRACES / f"{safe}.json"
    if not fp.is_file():
        return {"ok": False, "error": "trace_not_found", "trace_id": safe}
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
    safe = _safe_trace_id(trace_id)
    if safe is None:
        return {
            "ok": False,
            "error": "invalid_trace_id",
            "trace_id": str(trace_id or "")[:64],
        }
    if _backend_mode() == "mcp":
        return _fetch_via_mcp(safe)
    return _load_fixture(safe)


def search_logs_via_backend(trace_id: str, *, limit: int = 10) -> dict[str, Any]:
    safe = _safe_trace_id(trace_id)
    if safe is None:
        return {"ok": False, "error": "invalid_trace_id", "trace_id": str(trace_id or "")[:64]}
    if _backend_mode() == "mcp":
        try:
            client = _mcp_client()
            raw = client.call_tool("search_logs", {"trace_id": safe, "limit": limit})
            return json.loads(raw or "{}")
        except Exception as e:
            return {"ok": False, "error": str(e)[:200]}
    data = _load_fixture(safe)
    if not data.get("ok"):
        return data
    logs = list(data.get("logs") or [])[:limit]
    return {"ok": True, "trace_id": safe, "logs": logs, "count": len(logs)}


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
