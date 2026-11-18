"""Personal knowledge-base agent: tools + system prompt for Live LLM ReAct.

Used by the workspace chat when ``REACT_AGENT_SERVER_LLM=1``. Tool execution is
scoped to the current actor's bookmarks only — no corpus / web fallback.
"""
from __future__ import annotations

import json
from typing import Any

from react_agent.apps.docs_troubleshoot.personal_kb import (
    current_actor_id,
    ingest_bookmark,
    list_bookmarks,
    revise_bookmark,
    save_bookmark,
    search_personal,
)


PERSONAL_KB_SYSTEM_PROMPT = """你是「个人知识库」助手，帮员工沉淀、整理和取回自己的收藏。

身份与边界：
- 你可以正常寒暄、自我介绍（例如回答「你是谁」「你好」），这不是入库要求。
- 只使用提供的个人库工具。禁止编造收藏，禁止用内置语料或外部网页冒充个人库内容。
- 提问取回时只能依据工具返回的个人收藏；证据不足时必须明确回答「个人库中没有足够依据」，并说明缺什么。
- 非法或不可访问的 URL 应如实告知用户，不要创建空收藏。

工作方式：
- 需要写入/合并收藏时调用 personal_ingest_bookmark（链接和/或正文，可选整理要求）。
- 需要改标题、摘要、关键词，或按自然语言要求重写某条时，调用 personal_update_bookmark。
- 需要浏览库时用 personal_list_bookmarks；需要按问题检索时用 personal_search_bookmarks。
- 真正改库后，在回复里展示更新后的标题、关键词和摘要（以及是否合并）。
- 先讨论整理方式可以只说话、不调用工具；材料够了再写入。
"""


def get_system_prompt(question: str = "") -> str:
    _ = question
    return PERSONAL_KB_SYSTEM_PROMPT


def _require_actor() -> str:
    actor = current_actor_id()
    if not actor:
        raise ValueError("X-Actor-Id / actor binding is required for personal KB tools")
    return actor


def personal_ingest_bookmark(
    url: str = "",
    text: str = "",
    requirement: str = "",
    title_hint: str = "",
) -> str:
    """Create or merge one bookmark from URL and/or pasted text."""
    actor = _require_actor()
    out = ingest_bookmark(
        actor,
        url=(url or "").strip(),
        text=(text or "").strip(),
        requirement=(requirement or "").strip(),
        title_hint=(title_hint or "").strip(),
        resolve=True if (url or "").strip() and not (text or "").strip() else False,
    )
    return json.dumps(out, ensure_ascii=False)


def personal_update_bookmark(
    bookmark_id: str,
    title: str | None = None,
    summary: str | None = None,
    keywords: str | None = None,
    requirement: str | None = None,
) -> str:
    """Update an existing bookmark by fields and/or a natural-language requirement."""
    actor = _require_actor()
    bid = (bookmark_id or "").strip()
    if not bid:
        return json.dumps(
            {"ok": False, "error": "invalid_request", "message": "bookmark_id required"},
            ensure_ascii=False,
        )
    req = (requirement or "").strip()
    if req and title is None and summary is None and keywords is None:
        out = revise_bookmark(actor, bid, requirement=req)
        return json.dumps(out, ensure_ascii=False)

    kwargs: dict[str, Any] = {}
    if title is not None:
        kwargs["title"] = title
    if summary is not None:
        kwargs["summary"] = summary
    if keywords is not None:
        kwargs["keywords"] = keywords
    if not kwargs and not req:
        return json.dumps(
            {
                "ok": False,
                "error": "invalid_request",
                "message": "provide title/summary/keywords and/or requirement",
            },
            ensure_ascii=False,
        )
    if kwargs:
        out = save_bookmark(actor, bid, **kwargs)
        if not out.get("ok"):
            return json.dumps(out, ensure_ascii=False)
        if req:
            out = revise_bookmark(actor, bid, requirement=req)
        return json.dumps(out, ensure_ascii=False)
    out = revise_bookmark(actor, bid, requirement=req)
    return json.dumps(out, ensure_ascii=False)


def personal_list_bookmarks() -> str:
    """List bookmarks for the current actor."""
    actor = _require_actor()
    items = list_bookmarks(actor)
    return json.dumps(
        {"ok": True, "actor_id": actor, "bookmark_count": len(items), "bookmarks": items},
        ensure_ascii=False,
    )


def personal_search_bookmarks(query: str, top_k: int = 5) -> str:
    """Search only the current actor's personal bookmarks."""
    actor = _require_actor()
    out = search_personal(actor, query, top_k=int(top_k or 5))
    # Never attach corpus hits here.
    return json.dumps(out, ensure_ascii=False)


_INGEST_DEF = {
    "type": "function",
    "function": {
        "name": "personal_ingest_bookmark",
        "description": (
            "将 https 链接和/或粘贴正文写入当前员工的个人收藏；"
            "同一 URL 或强关键词重叠时会合并。可选 requirement 指定整理重点。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "可选 https 链接"},
                "text": {"type": "string", "description": "可选粘贴正文"},
                "requirement": {
                    "type": "string",
                    "description": "可选整理要求，如「重点摘安装步骤」",
                },
                "title_hint": {"type": "string", "description": "可选标题提示"},
            },
        },
    },
}

_UPDATE_DEF = {
    "type": "function",
    "function": {
        "name": "personal_update_bookmark",
        "description": (
            "更新已有收藏：可直接改 title/summary/keywords，"
            "或只给 requirement 按正文重写摘要/关键词（如「摘要再短一点」）。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "bookmark_id": {"type": "string"},
                "title": {"type": "string"},
                "summary": {"type": "string"},
                "keywords": {
                    "type": "string",
                    "description": "逗号分隔关键词，或 JSON 数组字符串",
                },
                "requirement": {"type": "string"},
            },
            "required": ["bookmark_id"],
        },
    },
}

_LIST_DEF = {
    "type": "function",
    "function": {
        "name": "personal_list_bookmarks",
        "description": "列出当前员工个人库中的全部收藏（标题/关键词/摘要/链接）。",
        "parameters": {"type": "object", "properties": {}},
    },
}

_SEARCH_DEF = {
    "type": "function",
    "function": {
        "name": "personal_search_bookmarks",
        "description": (
            "仅在当前员工个人收藏中检索。结果不足时请拒答「个人库中没有足够依据」。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "top_k": {"type": "integer"},
            },
            "required": ["query"],
        },
    },
}

TOOL_DEFINITIONS = [_INGEST_DEF, _UPDATE_DEF, _LIST_DEF, _SEARCH_DEF]
TOOL_REGISTRY = {
    "personal_ingest_bookmark": personal_ingest_bookmark,
    "personal_update_bookmark": personal_update_bookmark,
    "personal_list_bookmarks": personal_list_bookmarks,
    "personal_search_bookmarks": personal_search_bookmarks,
}
