"""safety — Agent 运行时权限（Harness 强制）与 HITL。

Permissions（准不准）与 ``harness.sandbox``（崩不崩）是两层，互不替代。
"""
from react_agent.safety.permissions import (
    ARG_RULES,
    TOOL_PERMISSIONS,
    PermissionDecision,
    PermissionLevel,
    describe_action,
    evaluate_tool_permission,
    get_direction_permission,
    get_tool_permission,
    is_high_risk,
)
from react_agent.safety.human_in_the_loop import ApprovalRecord, HumanInTheLoop
from react_agent.safety.permission_gate import (
    get_hitl,
    permission_block_message,
    set_hitl,
)

__all__ = [
    "ARG_RULES",
    "TOOL_PERMISSIONS",
    "ApprovalRecord",
    "HumanInTheLoop",
    "PermissionDecision",
    "PermissionLevel",
    "describe_action",
    "evaluate_tool_permission",
    "get_direction_permission",
    "get_hitl",
    "get_tool_permission",
    "is_high_risk",
    "permission_block_message",
    "set_hitl",
]
