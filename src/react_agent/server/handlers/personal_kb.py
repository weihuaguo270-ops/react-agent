"""HTTP helpers for personal knowledge-base ingest / list / update."""
from __future__ import annotations

from typing import Any

from react_agent.server.http_util import error_response


def _actor_from(body: dict | None, header_actor: str | None) -> str:
    raw = (header_actor or "").strip()
    if not raw and isinstance(body, dict):
        raw = str(body.get("actor_id") or body.get("actor") or "").strip()
    return raw


def handle_personal_ingest(
    body: dict,
    request_id: str,
    *,
    actor_id: str | None = None,
    fetcher=None,
    generator=None,
) -> tuple[int, dict]:
    """Ingest a URL and/or pasted text (+ optional requirement) as one bookmark."""
    from react_agent.apps.docs_troubleshoot.personal_kb import (
        ingest_bookmark,
        normalize_actor_id,
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

    if not url and not text_s:
        return error_response(
            "invalid_request",
            "url or text is required",
            request_id,
            400,
        )

    out = ingest_bookmark(
        actor,
        url=url,
        text=text_s,
        requirement=requirement,
        title_hint=title,
        fetcher=fetcher,
        generator=generator,
        resolve=True if url and not text_s else False,
    )

    if not out.get("ok"):
        code = str(out.get("error") or "ingest_failed")
        status = (
            400
            if code in ("invalid_url", "empty_text", "empty_body", "empty_input")
            else 502
        )
        return error_response(code, str(out.get("message") or code), request_id, status)

    bookmark = out.get("bookmark") or {}
    return 200, {
        "request_id": request_id,
        "ok": True,
        "actor_id": out.get("actor_id") or actor,
        "bookmark": bookmark,
        "source": bookmark,
        "merged": bool(out.get("merged")),
        "merge_reason": out.get("merge_reason") or "",
        "message": out.get("message") or "ok",
    }


def handle_personal_sources(
    request_id: str,
    *,
    actor_id: str | None = None,
) -> tuple[int, dict[str, Any]]:
    """List bookmarks already stored for the actor."""
    from react_agent.apps.docs_troubleshoot.personal_kb import (
        list_bookmarks,
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

    bookmarks = list_bookmarks(actor)
    return 200, {
        "request_id": request_id,
        "ok": True,
        "actor_id": actor,
        "bookmarks": bookmarks,
        "sources": bookmarks,
        "bookmark_count": len(bookmarks),
        "source_count": len(bookmarks),
    }


def handle_personal_update(
    bookmark_id: str,
    body: dict,
    request_id: str,
    *,
    actor_id: str | None = None,
) -> tuple[int, dict[str, Any]]:
    """Patch title / summary / keywords on one bookmark."""
    from react_agent.apps.docs_troubleshoot.personal_kb import (
        normalize_actor_id,
        save_bookmark,
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

    bid = (bookmark_id or "").strip()
    if not bid:
        return error_response("invalid_request", "bookmark id required", request_id, 400)

    kwargs: dict[str, Any] = {}
    if "title" in body:
        kwargs["title"] = body.get("title")
    if "summary" in body:
        kwargs["summary"] = body.get("summary")
    if "keywords" in body:
        kwargs["keywords"] = body.get("keywords")
    if not kwargs:
        return error_response(
            "invalid_request",
            "provide title, summary, and/or keywords",
            request_id,
            400,
        )

    out = save_bookmark(actor, bid, **kwargs)
    if not out.get("ok"):
        code = str(out.get("error") or "update_failed")
        status = 404 if code == "not_found" else 400
        return error_response(code, str(out.get("message") or code), request_id, status)

    return 200, {
        "request_id": request_id,
        "ok": True,
        "actor_id": actor,
        "bookmark": out.get("bookmark") or {},
        "message": "已保存",
    }
