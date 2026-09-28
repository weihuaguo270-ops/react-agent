"""Offline answer path — Agent loop by default (tool selection + Harness trajectory)."""
from __future__ import annotations

import os
from typing import Any

from react_agent.tools import set_request_app


def answer_offline(query: str, **state: Any) -> dict[str, Any]:
    """Deterministic docs troubleshoot via offline Agent loop (default) or Workflow."""
    os.environ.setdefault("REACT_AGENT_RAG_MODE", "keyword")
    # 声明本次请求的 app 作用域，而不是把 app 工具永久并入全局注册表
    set_request_app("docs_troubleshoot")
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
        "multimodal": result.state.get("multimodal_summary") or {},
    }
    return out
