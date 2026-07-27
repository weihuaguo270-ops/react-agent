"""Offline answer path via Workflow v4 (unified with /v1/workflows/run)."""
from __future__ import annotations

import os
from typing import Any

from react_agent.tools import enable_app_tools


def answer_offline(query: str, **state: Any) -> dict[str, Any]:
    """Deterministic docs troubleshoot answer without LLM."""
    os.environ.setdefault("REACT_AGENT_APP", "docs_troubleshoot")
    os.environ.setdefault("REACT_AGENT_RAG_MODE", "keyword")
    enable_app_tools()
    from react_agent.apps.docs_troubleshoot.index import reset_index
    from react_agent.workflow import run_workflow

    reset_index()
    initial = {"query": query, **state}
    result = run_workflow("docs_troubleshoot", initial)
    return {
        "ok": result.ok,
        "answer": result.answer,
        "refused": bool(result.refused),
        "citations": result.citations or [],
        "diagnosis": result.diagnosis or {},
        "policy": result.state.get("policy"),
    }
