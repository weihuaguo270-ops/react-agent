"""Offline answer path — Agent loop by default (tool selection + Harness trajectory)."""
from __future__ import annotations

import os
from typing import Any

from react_agent.tools import enable_app_tools


def answer_offline(query: str, **state: Any) -> dict[str, Any]:
    """Deterministic docs troubleshoot via offline Agent loop (default) or Workflow."""
    os.environ.setdefault("REACT_AGENT_APP", "docs_troubleshoot")
    os.environ.setdefault("REACT_AGENT_RAG_MODE", "keyword")
    enable_app_tools()
    from react_agent.apps.docs_troubleshoot.index import reset_index
    from react_agent.apps.docs_troubleshoot.agent_runner import run_docs

    reset_index()
    initial = {"query": query, **state}
    result = run_docs(initial)
    out = {
        "ok": result.ok,
        "answer": result.answer,
        "refused": bool(result.refused),
        "citations": result.citations or [],
        "diagnosis": result.diagnosis or {},
        "policy": result.state.get("policy"),
        "trajectory_id": result.trajectory_id,
        "engine": os.environ.get("REACT_AGENT_DOCS_ENGINE", "agent"),
        "agent_steps": result.agent_steps,
    }
    return out
