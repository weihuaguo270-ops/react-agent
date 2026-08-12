"""Liveness / readiness helpers for the thin HTTP server."""
from __future__ import annotations

import os
from typing import Any


def package_version() -> str:
    try:
        from importlib.metadata import version

        return version("react-agent")
    except Exception:
        return "0.7.0"


def _default_app() -> str:
    return (
        os.environ.get("REACT_AGENT_DEFAULT_APP")
        or os.environ.get("REACT_AGENT_APP")
        or "docs_troubleshoot"
    ).strip()


def liveness_payload(*, request_id: str) -> dict[str, Any]:
    return {
        "status": "ok",
        "version": package_version(),
        "default_app": _default_app(),
        "request_id": request_id,
    }


def readiness_check() -> tuple[bool, dict[str, Any]]:
    """检查 Sandbox 后端和默认应用依赖。"""
    from react_agent.harness import SANDBOX

    app = _default_app()
    sandbox_status = SANDBOX.status()
    if SANDBOX.required:
        ready, error = SANDBOX.verify_runtime()
        sandbox_status = SANDBOX.status()
        if not ready:
            return False, {
                "app": app,
                "reason": "sandbox_unavailable",
                "error": str(error or "")[:200],
                "sandbox": sandbox_status,
            }
    if app != "docs_troubleshoot":
        return True, {
            "app": app,
            "reason": "non_docs_app_skipped",
            "sandbox": sandbox_status,
        }

    try:
        from react_agent.apps.docs_troubleshoot.index import get_index

        idx = get_index()
        n = len(getattr(idx, "chunks", []) or [])
        if n <= 0:
            return False, {
                "app": app,
                "chunks": 0,
                "reason": "empty_index",
                "sandbox": sandbox_status,
            }
        return True, {
            "app": app,
            "chunks": n,
            "rag_mode": os.environ.get("REACT_AGENT_RAG_MODE", ""),
            "sandbox": sandbox_status,
        }
    except Exception as exc:
        return False, {
            "app": app,
            "reason": "index_error",
            "error": str(exc)[:200],
            "sandbox": sandbox_status,
        }


def readiness_payload(*, request_id: str) -> tuple[int, dict[str, Any]]:
    ok, details = readiness_check()
    payload: dict[str, Any] = {
        "status": "ready" if ok else "not_ready",
        "version": package_version(),
        "request_id": request_id,
        **details,
    }
    return (200 if ok else 503), payload
