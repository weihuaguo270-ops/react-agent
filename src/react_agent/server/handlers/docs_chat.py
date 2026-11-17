"""docs_troubleshoot /v1/chat handler."""
from __future__ import annotations

import os
from typing import Any

from react_agent.server.http_util import error_response


def handle_docs_chat(body: dict, request_id: str) -> tuple[int, dict]:
    message = (body.get("message") or body.get("query") or "").strip()
    if not message:
        return error_response("invalid_request", "message is required", request_id, 400)

    use_llm = os.environ.get("REACT_AGENT_SERVER_LLM", "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )
    trajectory_id = ""
    actor_id = (
        body.get("actor_id")
        or body.get("actor")
        or body.get("x_actor_id")
        or ""
    )
    if isinstance(actor_id, str):
        actor_id = actor_id.strip()
    else:
        actor_id = ""

    if use_llm:
        try:
            from react_agent.harness.recorder import current_trajectory
            from react_agent.react_loop import react_loop
            from react_agent.tools import set_request_app

            # 请求级作用域：不再用 os.environ 全局改动 app
            set_request_app("docs_troubleshoot")
            answer = react_loop(message, max_steps=int(body.get("max_steps") or 6))
            if not isinstance(answer, str):
                answer = str(answer.get("output", answer))
            traj = current_trajectory()
            if traj is not None:
                trajectory_id = getattr(traj, "session_id", "") or getattr(traj, "id", "") or ""
            from react_agent.apps.docs_troubleshoot.policy import enforce_answer_policy

            out = enforce_answer_policy(answer)
            return 200, {
                "request_id": request_id,
                "app": "docs_troubleshoot",
                "answer": out["answer"],
                "trajectory_id": trajectory_id,
                "citations": out.get("citations") or [],
                "refused": out.get("refused", False),
                "mode": "llm",
            }
        except Exception as e:
            return error_response("internal_error", str(e)[:300], request_id, 500)

    from react_agent.apps.docs_troubleshoot.offline_answer import answer_offline

    extra: dict[str, Any] = {}
    if body.get("error_response") is not None:
        extra["error_response"] = body.get("error_response")
    if body.get("request_headers") is not None:
        extra["request_headers"] = body.get("request_headers")
    if body.get("run_health_check"):
        extra["run_health_check"] = True
        if body.get("health_url"):
            extra["health_url"] = body.get("health_url")
    if body.get("log_excerpt") is not None:
        extra["log_excerpt"] = body.get("log_excerpt")
    if body.get("trace_context") is not None:
        extra["trace_context"] = body.get("trace_context")
    if body.get("docs_sources") is not None:
        extra["docs_sources"] = body.get("docs_sources")
    if actor_id:
        extra["actor_id"] = actor_id

    out = answer_offline(message, **extra)
    sources = [c.get("source", "") for c in (out.get("citations") or []) if c.get("source")]
    citations = out.get("citations") or [{"source": s} for s in sources[:3]]
    # Prefer clickable URLs; label text-only bookmark citations for the UI.
    enriched = []
    for c in citations:
        item = dict(c) if isinstance(c, dict) else {"source": str(c)}
        src = str(item.get("source") or "")
        if not item.get("url") and (src.startswith("http://") or src.startswith("https://")):
            item["url"] = src
        if not item.get("title") and src.startswith("bookmark_") and src.endswith(".md"):
            item["title"] = "个人收藏"
        enriched.append(item)
    tid = out.get("trajectory_id") or trajectory_id or f"offline-{request_id[:8]}"
    return 200, {
        "request_id": request_id,
        "app": "docs_troubleshoot",
        "answer": out["answer"],
        "trajectory_id": tid,
        "citations": enriched,
        "refused": out.get("refused", False),
        "diagnosis": out.get("diagnosis") or {},
        "mode": "offline",
        "engine": out.get("engine") or "agent",
        "agent_steps": out.get("agent_steps") or [],
        "session_id": body.get("session_id") or "",
        "docs_sources": out.get("docs_sources") or [],
        "retrieval_process": out.get("retrieval_process") or [],
        "actor_id": actor_id or "",
    }
