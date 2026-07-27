"""Offline answer path (same retrieve → draft → policy as HTTP /v1/chat default)."""
from __future__ import annotations

import json
from typing import Any

from react_agent.apps.docs_troubleshoot.draft import build_draft_from_hits
from react_agent.apps.docs_troubleshoot.policy import enforce_answer_policy
from react_agent.apps.docs_troubleshoot.tools import lookup_api, search_docs


def answer_offline(query: str) -> dict[str, Any]:
    """Deterministic docs troubleshoot answer without LLM."""
    search = json.loads(search_docs(query, top_k=3))
    api = json.loads(lookup_api(query, top_k=2))
    draft_out = build_draft_from_hits(query, search, api)
    out = enforce_answer_policy(
        draft_out["draft"],
        allowed_sources=draft_out.get("allowed_sources") or None,
        must_refuse=bool(draft_out.get("need_refuse")),
    )
    return {
        "ok": True,
        "answer": out["answer"],
        "refused": bool(out.get("refused")),
        "citations": out.get("citations") or [],
        "policy": out.get("policy"),
    }
