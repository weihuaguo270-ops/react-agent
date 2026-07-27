"""Domain tools for docs/API troubleshoot."""
from __future__ import annotations

import json
from typing import Any

from react_agent.apps.docs_troubleshoot.index import get_index
from react_agent.apps.docs_troubleshoot.policy import verify_citations


def search_docs(query: str, top_k: int = 3) -> str:
    """Search internal docs/runbooks for troubleshooting context."""
    rag = get_index()
    hits = rag.query(query, top_k=top_k)
    if not hits:
        return json.dumps(
            {"ok": False, "message": "no_hits", "results": []},
            ensure_ascii=False,
        )
    results = [
        {
            "source": h.get("source", ""),
            "score": h.get("score"),
            "content": h.get("content", "")[:800],
        }
        for h in hits
    ]
    return json.dumps({"ok": True, "results": results}, ensure_ascii=False)


def lookup_api(topic: str, top_k: int = 3) -> str:
    """Lookup API reference sections (auth, endpoints, error codes)."""
    rag = get_index()
    # Bias toward api_reference by query rewrite
    q = f"API {topic} endpoint error Authorization"
    hits = rag.query(q, top_k=max(top_k * 2, 4))
    api_hits = [h for h in hits if "api" in (h.get("source") or "").lower()]
    use = api_hits[:top_k] or hits[:top_k]
    if not use:
        return json.dumps(
            {"ok": False, "message": "no_api_hits", "results": []},
            ensure_ascii=False,
        )
    results = [
        {
            "source": h.get("source", ""),
            "score": h.get("score"),
            "content": h.get("content", "")[:800],
        }
        for h in use
    ]
    return json.dumps({"ok": True, "results": results}, ensure_ascii=False)


def verify_citations_tool(answer: str, allowed_sources: str = "") -> str:
    """
    Verify that an answer cites corpus sources.
    allowed_sources: comma-separated filenames (optional).
    """
    allowed = None
    if allowed_sources and allowed_sources.strip():
        allowed = [s.strip() for s in allowed_sources.split(",") if s.strip()]
    else:
        # Default: any file currently in the index
        rag = get_index()
        allowed = list({s for s in rag.sources if s})
    check = verify_citations(answer, allowed_sources=allowed)
    return json.dumps(check, ensure_ascii=False)


SEARCH_DOCS_DEF: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "search_docs",
        "description": "检索内部文档与排障 Runbook。回答事实前必须先检索。",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "检索问题或关键词"},
                "top_k": {"type": "integer", "description": "返回条数，默认 3"},
            },
            "required": ["query"],
        },
    },
}

LOOKUP_API_DEF: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "lookup_api",
        "description": "查阅 API 参考（鉴权、端点、错误码）。涉及接口行为时使用。",
        "parameters": {
            "type": "object",
            "properties": {
                "topic": {"type": "string", "description": "如 auth、/v1/chat、429"},
                "top_k": {"type": "integer", "description": "返回条数，默认 3"},
            },
            "required": ["topic"],
        },
    },
}

VERIFY_CITATIONS_DEF: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "verify_citations",
        "description": "校验回答是否引用了语料来源；失败则不得给出确定结论。",
        "parameters": {
            "type": "object",
            "properties": {
                "answer": {"type": "string", "description": "待校验的回答草稿"},
                "allowed_sources": {
                    "type": "string",
                    "description": "可选，逗号分隔的允许文件名",
                },
            },
            "required": ["answer"],
        },
    },
}

TOOL_DEFINITIONS = [SEARCH_DOCS_DEF, LOOKUP_API_DEF, VERIFY_CITATIONS_DEF]
TOOL_REGISTRY = {
    "search_docs": search_docs,
    "lookup_api": lookup_api,
    "verify_citations": verify_citations_tool,
}
