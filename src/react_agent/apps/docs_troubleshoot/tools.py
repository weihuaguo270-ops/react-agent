"""Domain tools for docs/API troubleshoot."""
from __future__ import annotations

import json
from typing import Any

from react_agent.apps.docs_troubleshoot.evidence import (
    parse_error_evidence,
    parse_log_evidence,
    parse_request_headers,
    parse_trace_context,
    probe_service_health,
    read_config_snapshot,
)
from react_agent.apps.docs_troubleshoot.trace_backend import fetch_trace_bundle
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
    """Verify that an answer cites corpus sources."""
    allowed = None
    if allowed_sources and allowed_sources.strip():
        allowed = [s.strip() for s in allowed_sources.split(",") if s.strip()]
    else:
        rag = get_index()
        allowed = list({s for s in rag.sources if s})
    check = verify_citations(answer, allowed_sources=allowed)
    return json.dumps(check, ensure_ascii=False)


def parse_error_evidence_tool(status_code: int = 0, body_json: str = "") -> str:
    return json.dumps(parse_error_evidence(status_code=status_code, body_json=body_json), ensure_ascii=False)


def parse_request_headers_tool(headers_json: str = "") -> str:
    return json.dumps(parse_request_headers(headers_json=headers_json), ensure_ascii=False)


def read_config_snapshot_tool(prefixes: str = "REACT_AGENT_") -> str:
    return json.dumps(read_config_snapshot(prefixes=prefixes), ensure_ascii=False)


def probe_service_health_tool(url: str = "") -> str:
    return json.dumps(probe_service_health(url=url), ensure_ascii=False)


def parse_log_evidence_tool(log_text: str = "", trace_id: str = "") -> str:
    return json.dumps(parse_log_evidence(log_text, trace_id=trace_id), ensure_ascii=False)


def parse_trace_context_tool(trace_json: str = "") -> str:
    return json.dumps(parse_trace_context(trace_json), ensure_ascii=False)


def fetch_trace_tool(trace_id: str = "") -> str:
    """Fetch trace from mock fixtures or MCP trace backend."""
    return json.dumps(fetch_trace_bundle(trace_id), ensure_ascii=False)


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

PARSE_ERROR_EVIDENCE_DEF: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "parse_error_evidence",
        "description": "解析 HTTP 错误响应（status + JSON body）为结构化现场证据。",
        "parameters": {
            "type": "object",
            "properties": {
                "status_code": {"type": "integer"},
                "body_json": {"type": "string", "description": "错误 JSON 字符串"},
            },
        },
    },
}

PROBE_HEALTH_DEF: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "probe_service_health",
        "description": "探测服务 /health（只读）。",
        "parameters": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "默认 REACT_AGENT_HEALTH_URL 或 :8765/health"},
            },
        },
    },
}

PARSE_LOG_EVIDENCE_DEF: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "parse_log_evidence",
        "description": "解析日志片段，提取 trace_id / 错误行作为现场证据。",
        "parameters": {
            "type": "object",
            "properties": {
                "log_text": {"type": "string", "description": "日志原文（多行）"},
                "trace_id": {"type": "string", "description": "可选，优先过滤该 trace"},
            },
            "required": ["log_text"],
        },
    },
}

PARSE_TRACE_CONTEXT_DEF: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "parse_trace_context",
        "description": "解析分布式 Trace JSON（spans / trace_id）。",
        "parameters": {
            "type": "object",
            "properties": {
                "trace_json": {"type": "string", "description": "Trace JSON 字符串"},
            },
            "required": ["trace_json"],
        },
    },
}

FETCH_TRACE_DEF: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "fetch_trace",
        "description": "从 Trace 后端（mock 或 MCP）按 trace_id 拉取 Trace 与日志。",
        "parameters": {
            "type": "object",
            "properties": {
                "trace_id": {"type": "string", "description": "分布式 trace_id"},
            },
            "required": ["trace_id"],
        },
    },
}

TOOL_DEFINITIONS = [
    SEARCH_DOCS_DEF,
    LOOKUP_API_DEF,
    VERIFY_CITATIONS_DEF,
    PARSE_ERROR_EVIDENCE_DEF,
    PARSE_LOG_EVIDENCE_DEF,
    PARSE_TRACE_CONTEXT_DEF,
    FETCH_TRACE_DEF,
    PROBE_HEALTH_DEF,
]
TOOL_REGISTRY = {
    "search_docs": search_docs,
    "lookup_api": lookup_api,
    "verify_citations": verify_citations_tool,
    "parse_error_evidence": parse_error_evidence_tool,
    "parse_request_headers": parse_request_headers_tool,
    "read_config_snapshot": read_config_snapshot_tool,
    "probe_service_health": probe_service_health_tool,
    "parse_log_evidence": parse_log_evidence_tool,
    "parse_trace_context": parse_trace_context_tool,
    "fetch_trace": fetch_trace_tool,
}
