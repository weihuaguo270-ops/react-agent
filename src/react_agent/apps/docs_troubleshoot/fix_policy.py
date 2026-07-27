"""Gate fix steps: destructive block + permission gate for actionable steps."""
from __future__ import annotations

import os
import re
from typing import Any

from react_agent.safety.permissions import PermissionLevel, evaluate_tool_permission

_BLOCKED = re.compile(
    r"(drop\s+table|drop\s+database|删库|删除生产|rm\s+-rf|格式化磁盘|"
    r"绕过鉴权|bypass\s+auth|truncate\s+table)",
    re.I,
)

_READONLY = re.compile(
    r"^(核对|检查|确认|对照|用\s|查询|读取|补充|查看|交叉验证|规划|在日志|用 trace)",
    re.I,
)

APPLY_FIX_STEP_TOOL = "apply_fix_step"


def _gate_enabled() -> bool:
    return os.environ.get("REACT_AGENT_PERMISSION_GATE", "1").strip().lower() not in (
        "0",
        "false",
        "off",
        "no",
    )


def classify_fix_step(step: str) -> PermissionLevel:
    text = str(step or "").strip()
    if not text:
        return PermissionLevel.SAFE
    if _BLOCKED.search(text):
        return PermissionLevel.DENY
    if _READONLY.search(text):
        return PermissionLevel.SAFE
    return PermissionLevel.CONFIRM


def gate_fix_steps(
    steps: list[str],
) -> tuple[list[str], list[str], list[dict[str, Any]]]:
    """Return (allowed_steps, blocked_steps, pending_fix_steps).

    Actionable fix steps must pass ``apply_fix_step`` permission evaluation when
    the harness permission gate is enabled (default ON).
    """
    allowed: list[str] = []
    blocked: list[str] = []
    pending: list[dict[str, Any]] = []

    for step in steps or []:
        text = str(step)
        level = classify_fix_step(text)
        if level == PermissionLevel.DENY:
            blocked.append(text)
            continue
        if level == PermissionLevel.CONFIRM and _gate_enabled():
            decision = evaluate_tool_permission(APPLY_FIX_STEP_TOOL, {"step": text})
            if decision.outcome == "allow":
                allowed.append(text)
            else:
                pending.append(
                    {
                        "step": text,
                        "outcome": decision.outcome,
                        "level": decision.level.value,
                        "reason": decision.reason,
                        "requires": "permission_gate_or_hitl",
                    }
                )
            continue
        allowed.append(text)

    return allowed, blocked, pending
