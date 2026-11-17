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
    from react_agent.apps.docs_troubleshoot.docs_sources import (
        SOURCE_PERSONAL,
        reset_docs_sources,
        resolve_docs_sources,
        set_docs_sources,
    )
    from react_agent.apps.docs_troubleshoot.agent_runner import run_docs
    from react_agent.apps.docs_troubleshoot.personal_kb import (
        reset_actor_id,
        set_actor_id,
    )

    sources = resolve_docs_sources(state.get("docs_sources"))
    token = set_docs_sources(sources)
    actor_raw = state.get("actor_id") or state.get("actor")
    actor_token = None
    try:
        if SOURCE_PERSONAL in sources:
            # Personal KB is durable per actor — do not rebuild the shared corpus index.
            if not actor_raw:
                return {
                    "ok": False,
                    "answer": "个人知识库需要提供员工身份（X-Actor-Id）。",
                    "refused": True,
                    "citations": [],
                    "diagnosis": {},
                    "policy": "actor_required",
                    "trajectory_id": "",
                    "engine": os.environ.get("REACT_AGENT_DOCS_ENGINE", "agent"),
                    "agent_steps": [],
                    "docs_sources": sources,
                    "retrieval_process": [
                        {"step": "personal_kb", "detail": "missing actor_id"}
                    ],
                }
            actor_token = set_actor_id(str(actor_raw))
        else:
            from react_agent.apps.docs_troubleshoot.index import reset_index

            reset_index()

        initial = {"query": query, **state, "docs_sources": sources}
        if actor_raw:
            initial["actor_id"] = str(actor_raw).strip()
        result = run_docs(initial)
        search_meta = result.state.get("search_hits") or {}
        if isinstance(search_meta, str):
            search_meta = {}
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
            "docs_sources": sources,
            "retrieval_process": list(
                search_meta.get("retrieval_process")
                or result.state.get("retrieval_process")
                or []
            ),
        }
        return out
    finally:
        reset_docs_sources(token)
        if actor_token is not None:
            reset_actor_id(actor_token)
