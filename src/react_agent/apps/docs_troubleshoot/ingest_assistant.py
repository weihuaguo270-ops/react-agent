"""Ingest assistant: clarify requirements, then generate/update one bookmark.

Conversation turns are NOT ingest. Only when URL/text is available (or the user
explicitly asks to generate and materials are ready) do we call ingest/revise.
Thread state is stored under the actor's personal runtime directory.
"""
from __future__ import annotations

import json
import os
import re
import uuid
from typing import Any, Optional

from react_agent.apps.docs_troubleshoot.personal_kb import (
    Fetcher,
    BookmarkGenerator,
    _lock_for,
    actor_dir,
    extract_ingest_fields,
    ingest_bookmark,
    normalize_actor_id,
    revise_bookmark,
    validate_ingest_url,
    _now,
)

_GREETING_RE = re.compile(
    r"^\s*(你好|您好|嗨|哈喽|hi|hello|hey)[\s!！。.?？～~]*$",
    re.IGNORECASE,
)
_GENERATE_RE = re.compile(
    r"(现在生成|生成收藏|生成草稿|入库|保存收藏|可以生成|直接生成|帮我生成|开始生成)"
)
_REVISE_RE = re.compile(
    r"(短一点|缩短|再短|更短|关键词.*(加上|增加|加一下)|改(一下)?摘要|摘要.*(改|再)|标题.*(改|换成)|再整理|按.*要求.*改)"
)


def _threads_dir(actor_id: str):
    path = actor_dir(actor_id) / "ingest_threads"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _thread_path(actor_id: str, thread_id: str):
    safe_tid = re.sub(r"[^A-Za-z0-9._-]", "_", (thread_id or "").strip())[:80]
    if not safe_tid:
        raise ValueError("thread_id required")
    return _threads_dir(actor_id) / f"{safe_tid}.json"


def new_thread_id() -> str:
    return f"th_{uuid.uuid4().hex[:12]}"


def _empty_thread(actor_id: str, thread_id: str) -> dict[str, Any]:
    return {
        "id": thread_id,
        "actor_id": actor_id,
        "requirement": "",
        "pending_url": "",
        "pending_text": "",
        "bookmark_id": "",
        "messages": [],
        "created_at": _now(),
        "updated_at": _now(),
    }


def load_thread(actor_id: str, thread_id: str) -> dict[str, Any] | None:
    safe = normalize_actor_id(actor_id)
    path = _thread_path(safe, thread_id)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    data["id"] = thread_id
    data["actor_id"] = safe
    return data


def save_thread(actor_id: str, thread: dict[str, Any]) -> None:
    safe = normalize_actor_id(actor_id)
    tid = str(thread.get("id") or "").strip()
    thread["actor_id"] = safe
    thread["updated_at"] = _now()
    path = _thread_path(safe, tid)
    with _lock_for(safe):
        path.write_text(
            json.dumps(thread, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )


def _append_message(thread: dict[str, Any], role: str, content: str) -> None:
    msgs = list(thread.get("messages") or [])
    msgs.append({"role": role, "content": content, "at": _now()})
    # Keep a bounded history for offline / LLM context.
    thread["messages"] = msgs[-40:]


def _has_materials(thread: dict[str, Any]) -> bool:
    return bool(
        str(thread.get("pending_url") or "").strip()
        or str(thread.get("pending_text") or "").strip()
    )


def _merge_extract_into_thread(thread: dict[str, Any], message: str) -> dict[str, Any]:
    fields = extract_ingest_fields(message)
    got_url = bool(fields.get("url"))
    got_text = bool(str(fields.get("text") or "").strip())
    got_req = bool(str(fields.get("requirement") or "").strip())

    if got_url:
        thread["pending_url"] = str(fields["url"]).strip()
    if got_text:
        existing = str(thread.get("pending_text") or "").strip()
        new_text = str(fields["text"]).strip()
        if existing and new_text and new_text not in existing:
            thread["pending_text"] = f"{existing}\n\n{new_text}"
        else:
            thread["pending_text"] = new_text or existing
    if got_req:
        req = str(fields["requirement"]).strip()
        prev = str(thread.get("requirement") or "").strip()
        if prev and req and req not in prev:
            thread["requirement"] = f"{prev}；{req}"
        else:
            thread["requirement"] = req or prev

    return {
        "got_url": got_url,
        "got_text": got_text,
        "got_requirement": got_req,
        "fields": fields,
    }


def _is_greeting(message: str) -> bool:
    return bool(_GREETING_RE.match((message or "").strip()))


def _wants_generate(message: str) -> bool:
    return bool(_GENERATE_RE.search(message or ""))


_URL_HINT_RE = re.compile(
    r"(?:https?|file|ftp|data|javascript|vbscript)://", re.I
)
_REQ_HINT = re.compile(r"(重点|摘要|复习|做成|关键词|短一点|整理|摘|安装)")


def _message_has_new_material(message: str) -> bool:
    raw = (message or "").strip()
    if _URL_HINT_RE.search(raw):
        return True
    fields = extract_ingest_fields(raw)
    return bool(str(fields.get("text") or "").strip())


def _looks_like_revise(message: str, thread: dict[str, Any]) -> bool:
    if not str(thread.get("bookmark_id") or "").strip():
        return False
    if _message_has_new_material(message):
        return False
    if _wants_generate(message):
        return False
    if _REVISE_RE.search(message or ""):
        return True
    # Short follow-up requirement after a draft exists.
    return (
        len((message or "").strip()) <= 80
        and bool(_REQ_HINT.search(message or ""))
    )


def _llm_enabled() -> bool:
    flag = os.environ.get("REACT_AGENT_PERSONAL_INGEST_LLM", "").strip().lower()
    if flag in ("1", "true", "yes", "on"):
        return True
    # Fall back to the general server LLM flag when set.
    return os.environ.get("REACT_AGENT_SERVER_LLM", "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def _try_llm_chat_reply(thread: dict[str, Any], user_message: str) -> str | None:
    """Optional natural reply for non-tool turns. Never creates bookmarks."""
    if not _llm_enabled():
        return None
    try:
        from react_agent.llm import get_default_llm

        llm = get_default_llm()
        if not llm or (
            llm.provider_name != "ollama" and not (llm.api_key or "").strip()
        ):
            return None
        state = (
            f"已记录要求：{thread.get('requirement') or '（尚未明确）'}\n"
            f"已有链接：{thread.get('pending_url') or '无'}\n"
            f"已有正文：{'有' if thread.get('pending_text') else '无'}\n"
            f"当前收藏 id：{thread.get('bookmark_id') or '尚未生成'}"
        )
        system = (
            "你是个人知识库的「投递助手」。帮助员工澄清要沉淀的内容与整理要求。"
            "不要假装已经入库；材料不足时用自然语气询问还缺链接还是正文。"
            "不要回答与投递无关的开放域问题。只用中文，简短。"
            f"\n当前线程状态：\n{state}"
        )
        history = []
        for m in (thread.get("messages") or [])[-8]:
            role = m.get("role")
            if role in ("user", "assistant") and m.get("content"):
                history.append({"role": role, "content": str(m["content"])[:1200]})
        history.append({"role": "user", "content": user_message[:2000]})
        messages = [{"role": "system", "content": system}, *history]
        out = llm.chat(messages, temperature=0.4, max_tokens=400)
        if isinstance(out, dict):
            text = str(out.get("content") or out.get("answer") or "").strip()
        else:
            text = str(out or "").strip()
        if not text or text.startswith("LLM调用"):
            return None
        return text[:1200]
    except Exception:  # noqa: BLE001 — offline path must always work
        return None


def _format_bookmark_reply(
    bookmark: dict[str, Any],
    *,
    merged: bool = False,
    merge_reason: str = "",
    revised: bool = False,
) -> str:
    title = bookmark.get("title") or "未命名收藏"
    kws = bookmark.get("keywords") or []
    kw_line = "、".join(str(k) for k in kws) if kws else "（无）"
    summary = bookmark.get("summary") or "（无摘要）"
    url = bookmark.get("url") or ""
    source = f"来源：{url}" if url else "文本收藏（无来源链接）"
    if revised:
        note = "已按你的要求更新当前这条收藏。"
    elif merged:
        reason = (
            "同一链接"
            if merge_reason == "same_url"
            else ("关键词相近" if merge_reason == "keyword_overlap" else "已有条目")
        )
        note = f"已合并到已有收藏（{reason}）。"
    else:
        note = "已生成新收藏。"
    return (
        f"{note}\n"
        f"标题：{title}\n"
        f"关键词：{kw_line}\n"
        f"摘要：{summary}\n"
        f"{source}"
    )


def _offline_chat_reply(
    thread: dict[str, Any],
    message: str,
    *,
    got_material: bool,
    got_requirement: bool,
) -> str:
    req = str(thread.get("requirement") or "").strip()
    has_mat = _has_materials(thread)

    if _is_greeting(message):
        return (
            "你好，我是投递助手。可以先告诉我你想怎么整理（例如复习摘要、重点摘安装步骤），"
            "也可以直接粘贴链接或正文；材料够了再说一声「生成收藏」即可。"
        )

    if got_requirement and not has_mat:
        return (
            f"好的，已记住整理要求：「{req}」。"
            "把要收藏的 https 链接或正文发给我后，我再按这个要求生成标题、关键词和摘要。"
        )

    if got_material and not req:
        return (
            "材料收到了。你希望怎么整理？例如「做成复习摘要」或「重点摘安装步骤」。"
            "确认后可以说「生成收藏」。"
        )

    if got_material and req:
        return (
            f"材料和要求都齐了（要求：「{req}」）。"
            "需要的话直接说「生成收藏」，我会按要求写出标题、关键词和摘要。"
        )

    if has_mat and req:
        return (
            f"当前已记录要求「{req}」，并且材料也在。"
            "可以说「生成收藏」让我入库；也可以继续补充链接、正文或调整要求。"
        )

    if has_mat:
        return "材料还在。补充整理要求后，或直接说「生成收藏」。"

    if req:
        return (
            f"要求「{req}」还在。接下来发链接或粘贴正文即可；"
            "也可以继续改要求，例如改成「摘要适合复习」。"
        )

    return (
        "我可以帮你沉淀一条收藏。先说整理目标，或直接发链接 / 粘贴正文；"
        "材料够了再说「生成收藏」。"
    )


def _run_generate(
    actor_id: str,
    thread: dict[str, Any],
    *,
    fetcher: Optional[Fetcher] = None,
    generator: Optional[BookmarkGenerator] = None,
) -> dict[str, Any]:
    url = str(thread.get("pending_url") or "").strip()
    text = str(thread.get("pending_text") or "").strip()
    requirement = str(thread.get("requirement") or "").strip()
    if not url and not text:
        return {
            "ok": False,
            "error": "need_content",
            "reply": "现在还没有链接或正文，我先不入库。把材料发来后我再生成收藏。",
        }
    if url:
        ok, reason = validate_ingest_url(url, resolve=False)
        if not ok:
            return {
                "ok": False,
                "error": "invalid_url",
                "reply": f"这个链接我没法收录：{reason}。请换一个可公开访问的 https 链接，或直接粘贴正文。",
            }
    out = ingest_bookmark(
        actor_id,
        url=url,
        text=text,
        requirement=requirement,
        fetcher=fetcher,
        generator=generator,
        resolve=True if url and not text else False,
    )
    if not out.get("ok"):
        code = str(out.get("error") or "ingest_failed")
        msg = str(out.get("message") or code)
        if code == "invalid_url":
            reply = f"这个链接我没法收录：{msg}。请换一个可公开访问的 https 链接，或直接粘贴正文。"
        else:
            reply = f"生成收藏时遇到问题：{msg}。可以换个链接，或把正文直接贴过来。"
        return {"ok": False, "error": code, "reply": reply}
    bm = out.get("bookmark") or {}
    thread["bookmark_id"] = str(bm.get("id") or "")
    reply = _format_bookmark_reply(
        bm,
        merged=bool(out.get("merged")),
        merge_reason=str(out.get("merge_reason") or ""),
    )
    return {
        "ok": True,
        "bookmark": bm,
        "merged": bool(out.get("merged")),
        "merge_reason": out.get("merge_reason") or "",
        "revised": False,
        "reply": reply,
        "action": "ingest",
    }


def _run_revise(
    actor_id: str,
    thread: dict[str, Any],
    message: str,
    *,
    generator: Optional[BookmarkGenerator] = None,
) -> dict[str, Any]:
    bid = str(thread.get("bookmark_id") or "").strip()
    req = (message or "").strip()
    # Keep cumulative requirement on the thread.
    prev = str(thread.get("requirement") or "").strip()
    if prev and req and req not in prev:
        thread["requirement"] = f"{prev}；{req}"
    elif req:
        thread["requirement"] = req
    out = revise_bookmark(
        actor_id, bid, requirement=req, generator=generator
    )
    if not out.get("ok"):
        return {
            "ok": False,
            "error": out.get("error") or "revise_failed",
            "reply": f"没能按要求更新：{out.get('message') or out.get('error')}。"
            "可以换种说法，或到「我的收藏」里直接编辑。",
        }
    bm = out.get("bookmark") or {}
    return {
        "ok": True,
        "bookmark": bm,
        "merged": False,
        "merge_reason": "",
        "revised": True,
        "reply": _format_bookmark_reply(bm, revised=True),
        "action": "revise",
    }


def ingest_chat_turn(
    actor_id: str,
    message: str,
    *,
    thread_id: str | None = None,
    fetcher: Optional[Fetcher] = None,
    generator: Optional[BookmarkGenerator] = None,
) -> dict[str, Any]:
    """One turn of the ingest assistant.

    Returns reply text always (HTTP 200 for normal dialogue). Tool failures that
    the user can recover from (invalid URL, missing materials) still return ok
    dialogue payloads with ``action`` explaining what happened.
    """
    safe = normalize_actor_id(actor_id)
    text = (message or "").strip()
    if not text:
        return {
            "ok": False,
            "error": "empty_message",
            "message": "请输入消息",
            "reply": "发一条消息即可，例如打招呼、说明整理要求，或粘贴链接/正文。",
        }

    if thread_id and str(thread_id).strip():
        tid = str(thread_id).strip()
        thread = load_thread(safe, tid) or _empty_thread(safe, tid)
    else:
        tid = new_thread_id()
        thread = _empty_thread(safe, tid)

    _append_message(thread, "user", text)
    extracted = _merge_extract_into_thread(thread, text)
    got_material = bool(extracted["got_url"] or extracted["got_text"])
    got_requirement = bool(extracted["got_requirement"])

    # Validate URL early when user just provided one (even before generate).
    if extracted["got_url"]:
        ok_url, reason = validate_ingest_url(thread["pending_url"], resolve=False)
        if not ok_url:
            thread["pending_url"] = ""
            reply = (
                f"这个链接我没法收录：{reason}。"
                "请换一个可公开访问的 https 链接，或直接粘贴正文；我们仍可先讨论整理要求。"
            )
            _append_message(thread, "assistant", reply)
            save_thread(safe, thread)
            return {
                "ok": True,
                "actor_id": safe,
                "thread_id": thread["id"],
                "reply": reply,
                "action": "reject_url",
                "bookmark": None,
                "merged": False,
                "merge_reason": "",
                "revised": False,
                "requirement": thread.get("requirement") or "",
                "has_materials": _has_materials(thread),
            }

    result: dict[str, Any] | None = None

    if _looks_like_revise(text, thread) and not got_material:
        result = _run_revise(safe, thread, text, generator=generator)
    else:
        should_generate = False
        if _wants_generate(text) and _has_materials(thread):
            should_generate = True
        elif got_material and str(thread.get("requirement") or "").strip():
            # Materials just arrived (or both in one turn) and requirement known.
            should_generate = True
        elif (
            got_requirement
            and _has_materials(thread)
            and not str(thread.get("bookmark_id") or "").strip()
        ):
            # Requirement clarified after materials were already present.
            should_generate = True
        if should_generate:
            result = _run_generate(
                safe, thread, fetcher=fetcher, generator=generator
            )

    if result is not None and result.get("ok"):
        reply = str(result["reply"])
        _append_message(thread, "assistant", reply)
        save_thread(safe, thread)
        return {
            "ok": True,
            "actor_id": safe,
            "thread_id": thread["id"],
            "reply": reply,
            "action": result.get("action") or "ingest",
            "bookmark": result.get("bookmark"),
            "merged": bool(result.get("merged")),
            "merge_reason": result.get("merge_reason") or "",
            "revised": bool(result.get("revised")),
            "requirement": thread.get("requirement") or "",
            "has_materials": _has_materials(thread),
        }

    if result is not None and not result.get("ok"):
        reply = str(result.get("reply") or result.get("message") or "暂时无法完成。")
        _append_message(thread, "assistant", reply)
        save_thread(safe, thread)
        return {
            "ok": True,
            "actor_id": safe,
            "thread_id": thread["id"],
            "reply": reply,
            "action": str(result.get("error") or "error"),
            "bookmark": None,
            "merged": False,
            "merge_reason": "",
            "revised": False,
            "requirement": thread.get("requirement") or "",
            "has_materials": _has_materials(thread),
        }

    # Pure dialogue turn.
    reply = _try_llm_chat_reply(thread, text) or _offline_chat_reply(
        thread,
        text,
        got_material=got_material,
        got_requirement=got_requirement,
    )
    _append_message(thread, "assistant", reply)
    save_thread(safe, thread)
    return {
        "ok": True,
        "actor_id": safe,
        "thread_id": thread["id"],
        "reply": reply,
        "action": "chat",
        "bookmark": None,
        "merged": False,
        "merge_reason": "",
        "revised": False,
        "requirement": thread.get("requirement") or "",
        "has_materials": _has_materials(thread),
    }
