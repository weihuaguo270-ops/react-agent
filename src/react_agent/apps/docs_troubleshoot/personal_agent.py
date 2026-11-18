"""Personal knowledge-base agent: tools + system prompt for Live LLM ReAct.

Uses the shared llm_config / LLM_PROVIDER path via react_loop. Tool execution is
scoped to the current actor's documents. Web search/fetch are only for
research + draft generation when the user asks — never as a fallback for
personal-library Q&A.
"""
from __future__ import annotations

import json
from typing import Any

from react_agent.apps.docs_troubleshoot.personal_kb import (
    current_actor_id,
    current_focused_document,
    get_document,
    ingest_document,
    list_documents,
    revise_document,
    save_document,
    save_generated_document,
    search_personal,
)


PERSONAL_KB_SYSTEM_PROMPT = """你是「个人知识库」助手，工作在文档库 + 正文阅读 + 对话的三分区工作区。

身份与边界：
- 你可以正常寒暄、自我介绍（例如回答「你是谁」「你好」）。寒暄不是入库要求，也不要要求用户必须先发链接。
- 提问取回时只能调用 personal_search_documents / personal_list_documents / personal_get_document，依据该员工个人库中的文档作答；有依据时给出引用（文档标题 + 原链接或文件名）。证据不足必须明确回答「个人库中没有足够依据」，禁止用内置语料或网页搜索结果冒充个人库答案。
- 非法或不可访问的 URL 应如实告知，不要创建空文档。
- 没有可用的网络检索时，说明无法联网生成，不要编造网页内容。

工作方式：
- 用户发来链接、粘贴正文或整理要求时：用 personal_upsert_document 写入/合并（同一 URL 合并更新）；先讨论也可以只说话。
- 改写摘要/正文：personal_update_document（按 requirement 或直接改字段）。若用户正在阅读某篇文档，优先针对该文档处理。
- 浏览库：personal_list_documents；取单篇：personal_get_document。
- 用户要求检索网上信息并生成文稿时：先 personal_web_search，需要正文再 personal_fetch_page，在对话里展示草稿；仅当用户明确要求保存到个人库时，调用 personal_save_generated_document。不要保存到用户本机路径。
- 模型自己决定何时说话、何时调用工具；不要把每一句当成入库或状态机分类。
"""


def get_system_prompt(question: str = "") -> str:
    _ = question
    prompt = PERSONAL_KB_SYSTEM_PROMPT
    focused = current_focused_document()
    if focused:
        title = str(focused.get("title") or "未命名文档")
        doc_id = str(focused.get("id") or "")
        url = str(focused.get("url") or "")
        filename = str(focused.get("filename") or "")
        source = url or filename or "本地"
        prompt += (
            f"\n\n当前用户正在阅读文档「{title}」（id={doc_id}，来源：{source}）。"
            "若用户要求改写、摘要、补充或提问该文，优先对该文档调用 "
            "personal_get_document / personal_update_document。"
        )
    return prompt


def _require_actor() -> str:
    actor = current_actor_id()
    if not actor:
        raise ValueError("X-Actor-Id / actor binding is required for personal KB tools")
    return actor


def personal_upsert_document(
    url: str = "",
    text: str = "",
    requirement: str = "",
    title_hint: str = "",
    filename: str = "",
) -> str:
    """Create or merge one document from URL and/or pasted / uploaded text."""
    actor = _require_actor()
    out = ingest_document(
        actor,
        url=(url or "").strip(),
        text=(text or "").strip(),
        requirement=(requirement or "").strip(),
        title_hint=(title_hint or "").strip(),
        filename=(filename or "").strip(),
        resolve=True if (url or "").strip() and not (text or "").strip() else False,
    )
    return json.dumps(out, ensure_ascii=False)


# Back-compat alias for older tests / tool names
def personal_ingest_bookmark(
    url: str = "",
    text: str = "",
    requirement: str = "",
    title_hint: str = "",
) -> str:
    return personal_upsert_document(
        url=url, text=text, requirement=requirement, title_hint=title_hint
    )


def personal_update_document(
    document_id: str = "",
    bookmark_id: str = "",
    title: str | None = None,
    summary: str | None = None,
    body: str | None = None,
    keywords: str | None = None,
    requirement: str | None = None,
) -> str:
    """Update an existing document by fields and/or a natural-language requirement."""
    actor = _require_actor()
    did = (document_id or bookmark_id or "").strip()
    if not did:
        return json.dumps(
            {"ok": False, "error": "invalid_request", "message": "document_id required"},
            ensure_ascii=False,
        )
    req = (requirement or "").strip()
    if req and title is None and summary is None and body is None and keywords is None:
        out = revise_document(actor, did, requirement=req)
        return json.dumps(out, ensure_ascii=False)

    kwargs: dict[str, Any] = {}
    if title is not None:
        kwargs["title"] = title
    if summary is not None:
        kwargs["summary"] = summary
    if body is not None:
        kwargs["body"] = body
    if keywords is not None:
        kwargs["keywords"] = keywords
    if not kwargs and not req:
        return json.dumps(
            {
                "ok": False,
                "error": "invalid_request",
                "message": "provide title/summary/body/keywords and/or requirement",
            },
            ensure_ascii=False,
        )
    if kwargs:
        out = save_document(actor, did, **kwargs)
        if not out.get("ok"):
            return json.dumps(out, ensure_ascii=False)
        if req:
            out = revise_document(actor, did, requirement=req)
        return json.dumps(out, ensure_ascii=False)
    out = revise_document(actor, did, requirement=req)
    return json.dumps(out, ensure_ascii=False)


def personal_update_bookmark(
    bookmark_id: str,
    title: str | None = None,
    summary: str | None = None,
    keywords: str | None = None,
    requirement: str | None = None,
) -> str:
    return personal_update_document(
        document_id=bookmark_id,
        title=title,
        summary=summary,
        keywords=keywords,
        requirement=requirement,
    )


def personal_list_documents() -> str:
    """List documents for the current actor."""
    actor = _require_actor()
    items = list_documents(actor)
    return json.dumps(
        {
            "ok": True,
            "actor_id": actor,
            "document_count": len(items),
            "bookmark_count": len(items),
            "documents": items,
            "bookmarks": items,
        },
        ensure_ascii=False,
    )


personal_list_bookmarks = personal_list_documents


def personal_get_document(document_id: str) -> str:
    """Return one document including full body."""
    actor = _require_actor()
    did = (document_id or "").strip()
    if not did:
        return json.dumps(
            {"ok": False, "error": "invalid_request", "message": "document_id required"},
            ensure_ascii=False,
        )
    doc = get_document(actor, did)
    if not doc:
        return json.dumps(
            {"ok": False, "error": "not_found", "message": "文档不存在"},
            ensure_ascii=False,
        )
    return json.dumps({"ok": True, "document": doc, "bookmark": doc}, ensure_ascii=False)


def personal_search_documents(query: str, top_k: int = 5) -> str:
    """Search only the current actor's personal documents."""
    actor = _require_actor()
    out = search_personal(actor, query, top_k=int(top_k or 5))
    return json.dumps(out, ensure_ascii=False)


personal_search_bookmarks = personal_search_documents


def personal_web_search(query: str, max_results: int = 3) -> str:
    """Search the public web for research / draft generation (not personal Q&A)."""
    from react_agent.tools.web_search import web_search

    q = (query or "").strip()
    if not q:
        return json.dumps(
            {"ok": False, "error": "invalid_request", "message": "query required"},
            ensure_ascii=False,
        )
    try:
        raw = web_search(q, max_results=int(max_results or 3))
    except Exception as exc:  # noqa: BLE001
        return json.dumps(
            {
                "ok": False,
                "error": "search_unavailable",
                "message": f"网络检索不可用：{exc}"[:300],
            },
            ensure_ascii=False,
        )
    text = str(raw or "")
    failed = (
        not text
        or text.startswith("搜索出错")
        or "搜索未找到" in text
        or "不可用" in text
    )
    if failed:
        return json.dumps(
            {
                "ok": False,
                "error": "search_unavailable",
                "message": text or "当前无法检索网上信息，不能编造网页内容。",
                "results_text": text,
            },
            ensure_ascii=False,
        )
    return json.dumps(
        {"ok": True, "results_text": text, "message": "仅用于生成草稿；回答个人库问题请用 personal_search_documents"},
        ensure_ascii=False,
    )


def personal_fetch_page(url: str) -> str:
    """Fetch a public page for research / draft generation."""
    from react_agent.tools.fetch_page import fetch_page

    u = (url or "").strip()
    if not u:
        return json.dumps(
            {"ok": False, "error": "invalid_request", "message": "url required"},
            ensure_ascii=False,
        )
    try:
        raw = fetch_page(u)
    except Exception as exc:  # noqa: BLE001
        return json.dumps(
            {
                "ok": False,
                "error": "fetch_unavailable",
                "message": f"无法抓取网页：{exc}"[:300],
            },
            ensure_ascii=False,
        )
    text = str(raw or "")
    if text.startswith("不支持的地址") or text.startswith("[已拦截]") or text.startswith("[读取失败]"):
        return json.dumps(
            {"ok": False, "error": "fetch_failed", "message": text[:300]},
            ensure_ascii=False,
        )
    return json.dumps({"ok": True, "url": u, "content": text}, ensure_ascii=False)


def personal_save_generated_document(
    title: str,
    body: str,
    summary: str = "",
    source_url: str = "",
) -> str:
    """Save an Agent-generated document into the personal library after user confirms."""
    actor = _require_actor()
    out = save_generated_document(
        actor,
        title=(title or "").strip(),
        body=(body or "").strip(),
        summary=(summary or "").strip(),
        source_url=(source_url or "").strip(),
    )
    return json.dumps(out, ensure_ascii=False)


_UPSERT_DEF = {
    "type": "function",
    "function": {
        "name": "personal_upsert_document",
        "description": (
            "将 https 链接和/或粘贴/上传正文写入当前员工的个人文档库；"
            "同一 URL 再次加入会合并更新。可选 requirement 指定摘要重点。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "可选 https 链接"},
                "text": {"type": "string", "description": "可选粘贴或文件正文"},
                "requirement": {
                    "type": "string",
                    "description": "可选整理要求，如「重点摘安装步骤」",
                },
                "title_hint": {"type": "string", "description": "可选标题提示"},
                "filename": {"type": "string", "description": "可选本地文件名（如 note.pdf）"},
            },
        },
    },
}

_UPDATE_DEF = {
    "type": "function",
    "function": {
        "name": "personal_update_document",
        "description": (
            "更新已有文档：可直接改 title/summary/body，"
            "或只给 requirement 按正文重写摘要（如「摘要再短一点」）。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "document_id": {"type": "string"},
                "title": {"type": "string"},
                "summary": {"type": "string"},
                "body": {"type": "string"},
                "keywords": {
                    "type": "string",
                    "description": "可选内部检索词，逗号分隔",
                },
                "requirement": {"type": "string"},
            },
            "required": ["document_id"],
        },
    },
}

_LIST_DEF = {
    "type": "function",
    "function": {
        "name": "personal_list_documents",
        "description": "列出当前员工个人库中的全部文档（标题/摘要/来源）。",
        "parameters": {"type": "object", "properties": {}},
    },
}

_GET_DEF = {
    "type": "function",
    "function": {
        "name": "personal_get_document",
        "description": "按 id 读取一篇文档的全文与摘要。",
        "parameters": {
            "type": "object",
            "properties": {"document_id": {"type": "string"}},
            "required": ["document_id"],
        },
    },
}

_SEARCH_DEF = {
    "type": "function",
    "function": {
        "name": "personal_search_documents",
        "description": (
            "仅在当前员工个人文档中检索。结果不足时请拒答「个人库中没有足够依据」。"
            "回答个人库问题时必须用此工具，不要用联网搜索代替。"
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

_WEB_DEF = {
    "type": "function",
    "function": {
        "name": "personal_web_search",
        "description": (
            "按用户要求检索网上信息，用于生成新文稿草稿。"
            "不可用作个人库提问的答案来源。不可用时说明无法联网生成。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "max_results": {"type": "integer"},
            },
            "required": ["query"],
        },
    },
}

_FETCH_DEF = {
    "type": "function",
    "function": {
        "name": "personal_fetch_page",
        "description": "抓取公开网页正文，用于生成草稿；非法 URL 会被拒绝。",
        "parameters": {
            "type": "object",
            "properties": {"url": {"type": "string"}},
            "required": ["url"],
        },
    },
}

_SAVE_GEN_DEF = {
    "type": "function",
    "function": {
        "name": "personal_save_generated_document",
        "description": (
            "在用户确认后，把 Agent 生成的文稿保存进当前身份的个人库工作区。"
            "不要保存到用户本机文件系统路径。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "body": {"type": "string"},
                "summary": {"type": "string"},
                "source_url": {"type": "string"},
            },
            "required": ["title", "body"],
        },
    },
}

TOOL_DEFINITIONS = [
    _UPSERT_DEF,
    _UPDATE_DEF,
    _LIST_DEF,
    _GET_DEF,
    _SEARCH_DEF,
    _WEB_DEF,
    _FETCH_DEF,
    _SAVE_GEN_DEF,
]
TOOL_REGISTRY = {
    "personal_upsert_document": personal_upsert_document,
    "personal_update_document": personal_update_document,
    "personal_list_documents": personal_list_documents,
    "personal_get_document": personal_get_document,
    "personal_search_documents": personal_search_documents,
    "personal_web_search": personal_web_search,
    "personal_fetch_page": personal_fetch_page,
    "personal_save_generated_document": personal_save_generated_document,
    # Aliases kept registered so older prompts/tests still resolve.
    "personal_ingest_bookmark": personal_ingest_bookmark,
    "personal_update_bookmark": personal_update_bookmark,
    "personal_list_bookmarks": personal_list_bookmarks,
    "personal_search_bookmarks": personal_search_bookmarks,
}
