"""文档排障应用的 `/v1/chat` 处理器。"""
from __future__ import annotations

import os
from typing import Any

from react_agent.server.http_util import error_response


def handle_docs_chat(
    body: dict[str, Any], request_id: str
) -> tuple[int, dict[str, Any]]:
    """执行 Live 或离线文档问答并返回统一证据字段。"""
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

    if use_llm:
        try:
            # Live 路径仍需经过回答策略，不能直接返回未经校验的模型文本。
            os.environ["REACT_AGENT_APP"] = "docs_troubleshoot"
            from react_agent.harness.recorder import current_trajectory
            from react_agent.react_loop import react_loop
            from react_agent.tools import enable_app_tools

            enable_app_tools()
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

    # 现场错误、请求头、日志和 trace 作为调用方提供的证据传入，
    # handler 不主动访问生产系统。
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

    out = answer_offline(message, **extra)
    sources = [c.get("source", "") for c in (out.get("citations") or []) if c.get("source")]
    tid = out.get("trajectory_id") or trajectory_id or f"offline-{request_id[:8]}"
    return 200, {
        "request_id": request_id,
        "app": "docs_troubleshoot",
        "answer": out["answer"],
        "trajectory_id": tid,
        "citations": out.get("citations") or [{"source": s} for s in sources[:3]],
        "refused": out.get("refused", False),
        "diagnosis": out.get("diagnosis") or {},
        "mode": "offline",
        "engine": out.get("engine") or "agent",
        "agent_steps": out.get("agent_steps") or [],
        "session_id": body.get("session_id") or "",
    }
