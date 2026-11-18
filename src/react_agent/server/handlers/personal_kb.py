"""HTTP helpers for personal knowledge-base ingest / list / update / agent chat."""
from __future__ import annotations

from typing import Any

from react_agent.server.http_util import error_response


def _actor_from(body: dict | None, header_actor: str | None) -> str:
    raw = (header_actor or "").strip()
    if not raw and isinstance(body, dict):
        raw = str(body.get("actor_id") or body.get("actor") or "").strip()
    return raw


def handle_personal_agent_chat(
    body: dict,
    request_id: str,
    *,
    actor_id: str | None = None,
) -> tuple[int, dict]:
    """Workspace Agent chat via react_loop + personal KB tools (Live LLM)."""
    import os

    from react_agent.apps.docs_troubleshoot.personal_kb import (
        normalize_actor_id,
        reset_actor_id,
        set_actor_id,
    )

    actor = _actor_from(body, actor_id)
    if not actor:
        return error_response(
            "forbidden_actor",
            "X-Actor-Id is required",
            request_id,
            403,
        )
    try:
        normalize_actor_id(actor)
    except ValueError as exc:
        return error_response("invalid_request", str(exc), request_id, 400)

    message = body.get("message")
    if not isinstance(message, str) or not message.strip():
        return error_response(
            "invalid_request",
            "message is required",
            request_id,
            400,
        )

    use_llm = os.environ.get("REACT_AGENT_SERVER_LLM", "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )
    if not use_llm:
        msg = (
            "当前未接入灵活对话与联网生成所需的模型。"
            "请配置 LLM，并设置 REACT_AGENT_SERVER_LLM=1 后再使用知识库助手。"
            "若只想把已有链接、PDF 或文件收入个人库，仍可用左侧「加入资料」有限后备。"
        )
        return 200, {
            "request_id": request_id,
            "ok": False,
            "needs_llm": True,
            "actor_id": actor,
            "answer": msg,
            "reply": msg,
            "mode": "needs_llm",
            "citations": [],
            "refused": False,
            "agent_steps": [],
        }

    from react_agent.apps.docs_troubleshoot.personal_agent import TOOL_DEFINITIONS
    from react_agent.harness.recorder import current_trajectory
    from react_agent.react_loop import get_last_trajectory_steps, react_loop
    from react_agent.tools import set_request_app

    token = set_actor_id(actor)
    set_request_app("personal_kb")
    answer = ""
    tid = ""
    steps: list = []
    try:
        try:
            answer = react_loop(
                message.strip(),
                max_steps=int(body.get("max_steps") or 8),
                tool_defs=TOOL_DEFINITIONS,
            )
            if not isinstance(answer, str):
                answer = str(answer.get("output", answer))
            traj = current_trajectory()
            if traj is not None:
                tid = getattr(traj, "session_id", "") or getattr(traj, "id", "") or ""
            steps = get_last_trajectory_steps() or []
        except Exception as exc:  # noqa: BLE001
            return error_response("internal_error", str(exc)[:300], request_id, 500)
    finally:
        reset_actor_id(token)
        set_request_app("")

    refused = "个人库中没有足够依据" in (answer or "")
    return 200, {
        "request_id": request_id,
        "ok": True,
        "needs_llm": False,
        "actor_id": actor,
        "answer": answer,
        "reply": answer,
        "mode": "llm",
        "app": "personal_kb",
        "trajectory_id": tid or request_id,
        "agent_steps": steps,
        "citations": [],
        "refused": refused,
    }


def handle_personal_ingest(
    body: dict,
    request_id: str,
    *,
    actor_id: str | None = None,
    fetcher=None,
    generator=None,
) -> tuple[int, dict]:
    """Ingest a URL, pasted text, PDF, or local file as one document."""
    from react_agent.apps.docs_troubleshoot.personal_kb import (
        ingest_document,
        normalize_actor_id,
        parse_ingest_message,
    )

    actor = _actor_from(body, actor_id)
    if not actor:
        return error_response(
            "forbidden_actor",
            "X-Actor-Id is required",
            request_id,
            403,
        )
    try:
        normalize_actor_id(actor)
    except ValueError as exc:
        return error_response("invalid_request", str(exc), request_id, 400)

    url = str(body.get("url") or body.get("link") or "").strip()
    text = body.get("text")
    text_s = text.strip() if isinstance(text, str) else ""
    title = str(body.get("title") or "").strip()
    requirement = str(
        body.get("requirement") or body.get("request") or body.get("ask") or ""
    ).strip()
    filename = str(body.get("filename") or body.get("file_name") or "").strip()
    content_base64 = str(
        body.get("content_base64") or body.get("file_base64") or ""
    ).strip()
    content_type = str(body.get("content_type") or body.get("mime") or "").strip()

    message = body.get("message")
    if isinstance(message, str) and message.strip():
        parsed = parse_ingest_message(message)
        if not parsed.get("ok") and not url and not text_s and not content_base64:
            code = str(parsed.get("error") or "invalid_request")
            return error_response(
                code,
                str(parsed.get("message") or code),
                request_id,
                400,
            )
        if parsed.get("ok"):
            if not url:
                url = str(parsed.get("url") or "").strip()
            if not text_s:
                text_s = str(parsed.get("text") or "").strip()
            if not requirement:
                requirement = str(parsed.get("requirement") or "").strip()

    if not url and not text_s and not content_base64:
        return error_response(
            "invalid_request",
            "url, text, or file upload is required",
            request_id,
            400,
        )

    out = ingest_document(
        actor,
        url=url,
        text=text_s,
        requirement=requirement,
        title_hint=title,
        filename=filename,
        content_base64=content_base64,
        content_type=content_type,
        fetcher=fetcher,
        generator=generator,
        resolve=True if url and not text_s and not content_base64 else False,
    )

    if not out.get("ok"):
        code = str(out.get("error") or "ingest_failed")
        status = (
            400
            if code
            in (
                "invalid_url",
                "empty_text",
                "empty_body",
                "empty_input",
                "invalid_upload",
                "too_large",
            )
            else 502
        )
        return error_response(code, str(out.get("message") or code), request_id, status)

    document = out.get("document") or out.get("bookmark") or {}
    return 200, {
        "request_id": request_id,
        "ok": True,
        "actor_id": out.get("actor_id") or actor,
        "document": document,
        "bookmark": document,
        "source": document,
        "merged": bool(out.get("merged")),
        "merge_reason": out.get("merge_reason") or "",
        "message": out.get("message") or "ok",
    }


def handle_personal_sources(
    request_id: str,
    *,
    actor_id: str | None = None,
) -> tuple[int, dict[str, Any]]:
    """List documents already stored for the actor."""
    from react_agent.apps.docs_troubleshoot.personal_kb import (
        list_documents,
        normalize_actor_id,
    )

    actor = (actor_id or "").strip()
    if not actor:
        return error_response(
            "forbidden_actor",
            "X-Actor-Id is required",
            request_id,
            403,
        )
    try:
        normalize_actor_id(actor)
    except ValueError as exc:
        return error_response("invalid_request", str(exc), request_id, 400)

    documents = list_documents(actor)
    return 200, {
        "request_id": request_id,
        "ok": True,
        "actor_id": actor,
        "documents": documents,
        "bookmarks": documents,
        "sources": documents,
        "document_count": len(documents),
        "bookmark_count": len(documents),
        "source_count": len(documents),
    }


def handle_personal_update(
    document_id: str,
    body: dict,
    request_id: str,
    *,
    actor_id: str | None = None,
) -> tuple[int, dict[str, Any]]:
    """Patch title / summary / body, or revise via requirement/message."""
    from react_agent.apps.docs_troubleshoot.personal_kb import (
        normalize_actor_id,
        revise_document,
        save_document,
    )

    actor = _actor_from(body, actor_id)
    if not actor:
        return error_response(
            "forbidden_actor",
            "X-Actor-Id is required",
            request_id,
            403,
        )
    try:
        normalize_actor_id(actor)
    except ValueError as exc:
        return error_response("invalid_request", str(exc), request_id, 400)

    did = (document_id or "").strip()
    if not did:
        return error_response("invalid_request", "document id required", request_id, 400)

    kwargs: dict[str, Any] = {}
    if "title" in body:
        kwargs["title"] = body.get("title")
    if "summary" in body:
        kwargs["summary"] = body.get("summary")
    if "body" in body:
        kwargs["body"] = body.get("body")
    if "keywords" in body:
        kwargs["keywords"] = body.get("keywords")

    requirement = str(
        body.get("requirement") or body.get("message") or body.get("request") or ""
    ).strip()

    if not kwargs and requirement:
        out = revise_document(actor, did, requirement=requirement)
        if not out.get("ok"):
            code = str(out.get("error") or "update_failed")
            status = 404 if code == "not_found" else 400
            return error_response(
                code, str(out.get("message") or code), request_id, status
            )
        document = out.get("document") or out.get("bookmark") or {}
        return 200, {
            "request_id": request_id,
            "ok": True,
            "actor_id": actor,
            "document": document,
            "bookmark": document,
            "revised": True,
            "message": out.get("message") or "已按要求更新文档",
        }

    if not kwargs:
        return error_response(
            "invalid_request",
            "provide title, summary, body, keywords, and/or requirement",
            request_id,
            400,
        )

    out = save_document(actor, did, **kwargs)
    if not out.get("ok"):
        code = str(out.get("error") or "update_failed")
        status = 404 if code == "not_found" else 400
        return error_response(code, str(out.get("message") or code), request_id, status)

    document = out.get("document") or out.get("bookmark") or {}
    return 200, {
        "request_id": request_id,
        "ok": True,
        "actor_id": actor,
        "document": document,
        "bookmark": document,
        "message": "已保存",
    }
