"""Liveness / readiness helpers for the thin HTTP server."""
from __future__ import annotations

import os
from typing import Any


def package_version() -> str:
    try:
        from importlib.metadata import version

        return version("react-agent")
    except Exception:
        return "0.7.0"


def tool_reachable_on_host(tool_name: str) -> bool:
    """该工具在**当前沙箱配置**下是否真的会在宿主上执行。

    仅按权限等级统计会误报：app 层工具（search_docs / read_config_snapshot /
    probe_service_health / fetch_trace）不在沙箱子进程的注册表里，配置为 auto
    时会被沙箱拦下（"未知工具"），实际不可达。这里复刻 react_loop 的派发判据。
    """
    from react_agent.harness.sandbox import SANDBOX

    if SANDBOX.strategy != "off" and SANDBOX.should_sandbox(tool_name):
        # 会走沙箱子进程；而子进程只加载 Core 工具 → app 工具不可达
        try:
            from react_agent.tools import _CORE_TOOL_NAMES

            if _CORE_TOOL_NAMES and tool_name not in _CORE_TOOL_NAMES:
                return False
        except Exception:
            pass
        # Core 工具在沙箱内仍会执行（隔离执行，但确实执行）
        return True
    if SANDBOX.required:
        return False
    return True


def confirmation_gate_status() -> dict[str, Any]:
    """报告 CONFIRM 级工具当前是「有人把关」还是「自动放行」。

    背景：``safety/human_in_the_loop.py`` 提供了完整的 HITL，但生产入口从未注入
    它（``permission_gate.set_hitl`` 只在测试里被调用）。于是非严格模式下
    ``CONFIRM`` 会**自动放行**——看起来有闸门，实际无人把关。这里把该状态显式
    暴露出来，避免"以为有审批"的误判。
    """
    from react_agent.safety.approvals import approval_mode as _approval_mode
    from react_agent.safety.permission_gate import get_hitl
    from react_agent.safety.permissions import evaluate_tool_permission
    from react_agent.tools import get_registry

    if get_hitl() is not None:
        mode = "hitl"
    elif _approval_mode() == "async":
        # 异步审批：CONFIRM 由人经 HTTP 批准，已有人把关
        mode = "async"
    elif os.environ.get("REACT_AGENT_STRICT_CONFIRM", "").strip().lower() in (
        "1", "true", "yes", "on",
    ):
        mode = "strict_deny"
    else:
        mode = "auto_allow"

    # 取「所有应用作用域」的并集，且以**注册表**为准：react_loop 按注册表成员派发，
    # 未出现在 TOOL_DEFINITIONS 里的工具（如 read_config_snapshot）也应纳入评估。
    names: set[str] = set()
    scopes = ["", *[str(a.get("id") or "") for a in _app_ids()]]
    for scope in scopes:
        try:
            names.update(get_registry(scope))
        except Exception:
            continue

    confirm_tools = sorted(
        name for name in names
        if evaluate_tool_permission(name, {}).level.value == "confirm"
    )
    if mode != "auto_allow":
        return {"mode": mode, "unenforced_confirm_tools": []}

    unreachable = [n for n in confirm_tools if not tool_reachable_on_host(n)]
    enforced = [n for n in confirm_tools if n not in unreachable]

    result: dict[str, Any] = {
        "mode": mode,
        "unenforced_confirm_tools": enforced,
        "unreachable_confirm_tools": unreachable,
    }
    if enforced:
        result["warning"] = (
            f"CONFIRM 级工具当前自动放行（未注入 HITL）：{enforced}。"
            "如需失败关闭请设 REACT_AGENT_STRICT_CONFIRM=1。"
        )
    return result


def _app_ids() -> list[dict[str, Any]]:
    try:
        from react_agent.server.chat_router import list_applications

        return list_applications()
    except Exception:
        return []


def confirmation_gate_startup_warning() -> str | None:
    """启动期告警文本；无需告警时返回 None。"""
    status = confirmation_gate_status()
    if status["mode"] == "auto_allow" and status["unenforced_confirm_tools"]:
        return f"[server] WARNING: {status['warning']}"
    return None


def capture_approval_status(payload: dict) -> str | None:
    """若本次请求需要人工审批，返回其 approval_id，否则 None。

    优先读闸门登记的**结构化信号**（``approvals.take_pending_approval``）：工具观测
    在轨迹里会被截断到 500 字符，approval_id 常常落在截断之外，因此字符串解析只
    作为兜底。
    """
    try:
        from react_agent.safety.approvals import take_pending_approval

        record = take_pending_approval()
        if record and record.get("approval_id"):
            return str(record["approval_id"])
    except Exception:
        pass

    import json as _json
    import re as _re

    candidates: list[str] = []
    answer = payload.get("answer")
    if isinstance(answer, str):
        candidates.append(answer)
    for step in payload.get("agent_steps") or []:
        if isinstance(step, dict):
            for key in ("observation", "detail"):
                value = step.get(key)
                if isinstance(value, str):
                    candidates.append(value)

    # 宽松回退：容忍 "approval_id":"x" / "approval_id": "x" / 被转义的 \"approval_id\"
    loose = _re.compile(r'approval_id\\*"?\s*:?\s*\\*"([0-9a-fA-F]{6,64})')

    def _maybe(blob: str) -> str | None:
        if "approval" not in blob:
            return None
        for text in (blob, blob.replace('\\"', '"')):
            try:
                data = _json.loads(text)
            except (ValueError, TypeError):
                continue
            if isinstance(data, dict):
                if data.get("approval_id"):
                    return str(data["approval_id"])
                inner = data.get("error")
                if isinstance(inner, str) and inner.strip().startswith("{"):
                    try:
                        nested = _json.loads(inner.strip().replace('\\"', '"'))
                    except (ValueError, TypeError):
                        nested = None
                    if isinstance(nested, dict) and nested.get("approval_id"):
                        return str(nested["approval_id"])
        match = loose.search(blob)
        return match.group(1) if match else None

    for blob in candidates:
        found = _maybe(blob)
        if found:
            return found
    return None


def _default_app() -> str:
    return (
        os.environ.get("REACT_AGENT_DEFAULT_APP")
        or os.environ.get("REACT_AGENT_APP")
        or "docs_troubleshoot"
    ).strip()


def liveness_payload(*, request_id: str) -> dict[str, Any]:
    return {
        "status": "ok",
        "version": package_version(),
        "default_app": _default_app(),
        "request_id": request_id,
    }


def readiness_check() -> tuple[bool, dict[str, Any]]:
    """检查 Sandbox 后端和默认应用依赖。"""
    from react_agent.harness import SANDBOX

    app = _default_app()
    sandbox_status = SANDBOX.status()
    if SANDBOX.required:
        ready, error = SANDBOX.verify_runtime()
        sandbox_status = SANDBOX.status()
        if not ready:
            return False, {
                "app": app,
                "reason": "sandbox_unavailable",
                "error": str(error or "")[:200],
                "sandbox": sandbox_status,
            }
    if app != "docs_troubleshoot":
        return True, {
            "app": app,
            "reason": "non_docs_app_skipped",
            "sandbox": sandbox_status,
        }

    try:
        from react_agent.apps.docs_troubleshoot.index import get_index

        idx = get_index()
        n = len(getattr(idx, "chunks", []) or [])
        if n <= 0:
            return False, {
                "app": app,
                "chunks": 0,
                "reason": "empty_index",
                "sandbox": sandbox_status,
            }
        return True, {
            "app": app,
            "chunks": n,
            "rag_mode": os.environ.get("REACT_AGENT_RAG_MODE", ""),
            "sandbox": sandbox_status,
        }
    except Exception as exc:
        return False, {
            "app": app,
            "reason": "index_error",
            "error": str(exc)[:200],
            "sandbox": sandbox_status,
        }


def readiness_payload(*, request_id: str) -> tuple[int, dict[str, Any]]:
    ok, details = readiness_check()
    payload: dict[str, Any] = {
        "status": "ready" if ok else "not_ready",
        "version": package_version(),
        "request_id": request_id,
        # 始终附带：让运维一眼看到「CONFIRM 是否真的有人把关」
        "confirmation_gate": confirmation_gate_status(),
        **details,
    }
    return (200 if ok else 503), payload
