"""将 `/v1/chat` 请求路由到各应用处理器。"""
from __future__ import annotations

import os
from typing import Any

from react_agent.server.http_util import error_response

APP_ALIASES = {
    "": "default",
    "default": "default",
    "react": "default",
    "general": "default",
    "docs": "docs_troubleshoot",
    "docs_troubleshoot": "docs_troubleshoot",
    "troubleshoot": "docs_troubleshoot",
    "expense": "expense",
    "报销": "expense",
}

APPLICATIONS = [
    {
        "id": "default",
        "pillar": "coding_execution",
        "description": "通用 ReAct（Live LLM 或 OFFLINE_REACT smoke）",
        "offline": False,
    },
    {
        "id": "docs_troubleshoot",
        "pillar": "support_automation",
        "description": "证据化文档/Runbook 问答（引用/拒答/现场证据）",
        "offline": True,
    },
    {
        "id": "expense",
        "pillar": "support_automation",
        "description": "报销政策检索 + 规则裁决 demo",
        "offline": True,
    },
]


def _message(body: dict[str, Any]) -> str | None:
    """Return a normalized message and reject structured values at the boundary."""
    value = body.get("message")
    if value is None:
        value = body.get("query")
    if not isinstance(value, str):
        return None
    return value.strip()


def normalize_app(raw: str | None) -> str:
    """将用户别名和默认配置统一为稳定的应用标识。"""
    key = (raw or "").strip().lower()
    if not key:
        key = os.environ.get("REACT_AGENT_DEFAULT_APP", "docs_troubleshoot").strip().lower()
    return APP_ALIASES.get(key, key)


def list_applications() -> list[dict[str, Any]]:
    """返回应用清单副本，避免调用方修改模块级配置。"""
    return [dict(a) for a in APPLICATIONS]


def handle_chat(
    body: dict[str, Any], request_id: str
) -> tuple[int, dict[str, Any]]:
    """按应用和运行模式处理一次对话请求。"""
    app = normalize_app(body.get("app") or body.get("application"))
    use_llm = os.environ.get("REACT_AGENT_SERVER_LLM", "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )

    if app == "docs_troubleshoot":
        # 文档排障维护独立策略和证据字段，由专用 handler 处理。
        from react_agent.server.handlers.docs_chat import handle_docs_chat

        return handle_docs_chat(body, request_id)

    if app == "expense":
        if use_llm:
            return error_response(
                "not_implemented",
                "expense app offline-only in v0.5; omit REACT_AGENT_SERVER_LLM",
                request_id,
                501,
            )
        from react_agent.apps.expense.offline_answer import answer_offline

        out = answer_offline(body)
        status = 200 if out.get("ok", True) else 400
        return status, {
            "request_id": request_id,
            "app": "expense",
            "answer": out.get("answer", ""),
            "refused": bool(out.get("refused")),
            "decision": out.get("decision"),
            "citations": out.get("citations") or [],
            "claim": out.get("claim") or {},
            "mode": "offline",
        }

    if app == "default":
        use_offline_react = (
            os.environ.get("REACT_AGENT_SERVER_OFFLINE_REACT", "")
            .strip()
            .lower()
            in ("1", "true", "yes", "on")
        )
        message = _message(body)
        if not message:
            return error_response("invalid_request", "message is required", request_id, 400)

        # 离线 ReAct 只用于无 Key 冒烟，不回退或伪装成 Live LLM。
        if use_offline_react:
            from react_agent.server.offline_react import offline_react_loop

            out = offline_react_loop(message, max_steps=int(body.get("max_steps") or 6))
            if not out.get("ok"):
                return error_response(
                    "not_implemented",
                    out.get("answer", "offline_react unsupported query"),
                    request_id,
                    501,
                )
            return 200, {
                "request_id": request_id,
                "app": "default",
                "answer": out.get("answer", ""),
                "tools_called": out.get("tools_called") or [],
                "agent_steps": out.get("agent_steps") or [],
                "mode": "offline_react",
            }

        if not use_llm:
            return error_response(
                "invalid_request",
                "app=default requires REACT_AGENT_SERVER_LLM=1 or "
                "REACT_AGENT_SERVER_OFFLINE_REACT=1; "
                "use app=docs_troubleshoot or app=expense for other offline paths",
                request_id,
                400,
            )
        try:
            # default 应用不应继承 docs_troubleshoot 的工具注册上下文。
            os.environ.pop("REACT_AGENT_APP", None)
            from react_agent.harness.recorder import current_trajectory
            from react_agent.react_loop import react_loop

            answer = react_loop(message, max_steps=int(body.get("max_steps") or 6))
            if not isinstance(answer, str):
                answer = str(answer.get("output", answer))
            traj = current_trajectory()
            tid = ""
            if traj is not None:
                tid = getattr(traj, "session_id", "") or getattr(traj, "id", "") or ""
            return 200, {
                "request_id": request_id,
                "app": "default",
                "answer": answer,
                "trajectory_id": tid,
                "mode": "llm",
            }
        except Exception as e:
            return error_response("internal_error", str(e)[:300], request_id, 500)

    return error_response("invalid_request", f"unknown app: {app}", request_id, 400)
