"""Harness 权限闸门 — 模型想调 ≠ 允许执行。

在工具真正执行（及沙箱）之前强制 ``evaluate_tool_permission``：
  deny → 直接拒绝
  ask  → HITL（若有）或非交互默许（学习/CI 默认）
  allow → 放行

与 ``harness.sandbox`` 正交：本模块管「准不准」；沙箱管「崩不崩/超时」。
关闭闸门：``REACT_AGENT_PERMISSION_GATE=0``
"""
from __future__ import annotations

import json
import os
from contextvars import ContextVar
from typing import Any, Optional

from react_agent.safety.approvals import approval_mode
from react_agent.safety.permissions import evaluate_tool_permission

_HITL = None

# 当前请求 id（供待批项关联到具体请求；未安装时为空）
_REQUEST_ID: ContextVar[str] = ContextVar("react_agent_request_id", default="")


def set_request_id(request_id: str) -> None:
    _REQUEST_ID.set((request_id or "").strip())


def current_request_id() -> str:
    return _REQUEST_ID.get()


def _async_approval_block(tool_name: str, tool_args: dict, decision) -> Optional[str]:
    """异步审批分支：放行有凭据的调用，否则阻塞并登记待批项。"""
    import json as _json

    from react_agent.safety import approvals
    from react_agent.safety.permissions import describe_action

    tool_key = f"tool:{tool_name}"
    # 1) 已批准的会话级授权
    if approvals.session_grant_for(tool_key):
        return None

    # 2) 本次请求携带的审批凭据
    approval_id = _pending_credential()
    if approval_id:
        allowed, reason = approvals.consume(approval_id)
        if allowed:
            return None
        # 凭据无效：继续走阻塞路径，把原因一并暴露，便于排查
        invalid_note = f"（审批凭据不可用: {reason}）"
    else:
        invalid_note = ""

    try:
        record = approvals.create_pending(
            tool=tool_name,
            arguments=tool_args,
            description=describe_action(tool_name, tool_args),
            reason=decision.reason,
            tool_key=tool_key,
            request_id=current_request_id(),
        )
    except approvals.ApprovalStoreError as exc:
        # 存不下待批项 → 无人能把关 → 拒绝（失败关闭，绝不退化为放行）
        return _json.dumps(
            {
                "error": "approval_store_unavailable",
                "tool": tool_name,
                "outcome": "deny",
                "level": decision.level.value,
                "reason": str(exc)[:300],
                "hint": "审批目录不可写，已按失败关闭拒绝执行；请检查 REACT_AGENT_APPROVAL_DIR 权限。",
            },
            ensure_ascii=False,
        )
    # 结构化信号：工具观测会被截断，字符串解析不可靠，故在闸门处直接登记
    approvals.note_approval_required(record)
    try:
        from react_agent.server.streaming import emit_event

        emit_event("approval_required", {
            "approval_id": record["approval_id"],
            "tool": tool_name,
            "arguments": tool_args,
            "level": decision.level.value,
            "expires_at": record["expires_at"],
        })
    except Exception:
        pass
    return _json.dumps(
        {
            "error": "approval_required",
            "approval_id": record["approval_id"],
            "tool": tool_name,
            "outcome": "ask",
            "level": decision.level.value,
            "reason": decision.reason,
            "hint": (
                "该操作需要人工批准。请 GET /v1/approvals 查看，"
                "POST /v1/approvals/{approval_id} {\"decision\":\"approve\"} 批准，"
                "然后带上同一 approval_id 重试本次请求。" + invalid_note
            ),
        },
        ensure_ascii=False,
    )


# 请求级审批凭据（由上层按请求设置；与 _REQUEST_ID 分开以免混淆语义）
_APPROVAL_CREDENTIAL: ContextVar[str] = ContextVar(
    "react_agent_approval_credential", default=""
)


def set_approval_credential(approval_id: str) -> None:
    _APPROVAL_CREDENTIAL.set((approval_id or "").strip())


def _pending_credential() -> str:
    return _APPROVAL_CREDENTIAL.get()


def _gate_enabled() -> bool:
    return os.environ.get("REACT_AGENT_PERMISSION_GATE", "1").strip().lower() not in (
        "0",
        "false",
        "off",
        "no",
    )


def set_hitl(hitl) -> None:
    """注入 HumanInTheLoop（可选；无则 DENY 仍拦截，CONFIRM 非交互放行）。"""
    global _HITL
    _HITL = hitl


def get_hitl():
    return _HITL


def permission_block_message(tool_name: str, tool_args: Optional[dict] = None) -> Optional[str]:
    """若应拦截则返回 error JSON 字符串；放行返回 None。"""
    if not _gate_enabled():
        return None

    decision = evaluate_tool_permission(tool_name, tool_args)
    if decision.outcome == "allow":
        return None

    if decision.outcome == "deny":
        # DENY 始终拦截；仅当显式 HITL 且用户覆盖时放行
        hitl = _HITL
        if hitl is not None:
            if hitl.check_tool_call(tool_name, tool_args or {}, reason=decision.reason):
                return None
        return json.dumps(
            {
                "error": "blocked by permission gate",
                "tool": tool_name,
                "outcome": "deny",
                "level": decision.level.value,
                "reason": decision.reason,
                "hint": "model tool_call != harness allow; DENY is enforced by runtime",
            },
            ensure_ascii=False,
        )

    # ask (CONFIRM)
    hitl = _HITL
    if hitl is not None:
        if hitl.check_tool_call(tool_name, tool_args or {}, reason=decision.reason):
            return None
        return json.dumps(
            {
                "error": "blocked by user (HITL ask)",
                "tool": tool_name,
                "outcome": "ask",
                "level": decision.level.value,
                "reason": decision.reason,
            },
            ensure_ascii=False,
        )

    # 异步审批（HTTP 场景）：审批建模为状态而非消息，故不需要双向通道。
    # 优先于"非交互默认放行"，让 CONFIRM 级工具真正有人把关。
    if approval_mode() == "async":
        return _async_approval_block(tool_name, tool_args or {}, decision)

    # 非交互学习默认：CONFIRM 放行（CI / 无 TTY），但带可观测标记
    # 设 REACT_AGENT_STRICT_CONFIRM=1 则无 HITL 时拒绝 CONFIRM
    strict = (
        os.environ.get("REACT_AGENT_STRICT_CONFIRM", "").strip().lower()
        in ("1", "true", "yes", "on")
        or os.environ.get("REACT_AGENT_SANDBOX_REQUIRED", "").strip().lower()
        in ("1", "true", "yes", "on")
    )
    if strict:
        return json.dumps(
            {
                "error": "blocked by strict confirm (no HITL)",
                "tool": tool_name,
                "outcome": "ask",
                "level": decision.level.value,
                "reason": decision.reason,
            },
            ensure_ascii=False,
        )
    return None
