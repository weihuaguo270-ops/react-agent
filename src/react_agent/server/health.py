"""Liveness / readiness helpers for the thin HTTP server."""
from __future__ import annotations

import os
from typing import Any


def package_version() -> str:
    try:
        from importlib.metadata import version

        return version("react-agent")
    except Exception:
        return "0.5.2"


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
    """True when the docs_troubleshoot index is loaded with chunks."""
    app = _default_app()
    if app != "docs_troubleshoot":
        return True, {"app": app, "reason": "non_docs_app_skipped"}

    try:
        from react_agent.apps.docs_troubleshoot.index import get_index

        idx = get_index()
        n = len(getattr(idx, "chunks", []) or [])
        if n <= 0:
            return False, {"app": app, "chunks": 0, "reason": "empty_index"}
        return True, {"app": app, "chunks": n, "rag_mode": os.environ.get("REACT_AGENT_RAG_MODE", "")}
    except Exception as exc:
        return False, {"app": app, "reason": "index_error", "error": str(exc)[:200]}


def readiness_payload(*, request_id: str) -> tuple[int, dict[str, Any]]:
    ok, details = readiness_check()
    payload: dict[str, Any] = {
        "status": "ready" if ok else "not_ready",
        "version": package_version(),
        "request_id": request_id,
        **details,
    }
    return (200 if ok else 503), payload
