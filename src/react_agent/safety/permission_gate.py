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
from typing import Any, Optional

from react_agent.safety.permissions import evaluate_tool_permission

_HITL = None


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

    # 非交互学习默认：CONFIRM 放行（CI / 无 TTY），但带可观测标记
    # 设 REACT_AGENT_STRICT_CONFIRM=1 则无 HITL 时拒绝 CONFIRM
    strict = os.environ.get("REACT_AGENT_STRICT_CONFIRM", "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
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
