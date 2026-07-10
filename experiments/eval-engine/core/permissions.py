"""permissions — 操作权限等级与工具分类

为 Agent 的每次操作定义风险等级，控制哪些操作需要人工审批。

等级划分：
  SAFE     — 纯读取，无需审批
  NOTIFY   — 读取敏感信息，通知用户但不阻塞
  CONFIRM  — 写入/执行，需用户确认
  DENY     — 破坏性操作，默认拒绝（除非用户明确覆盖）
"""

from __future__ import annotations
from enum import Enum
from typing import Optional


class PermissionLevel(Enum):
    """操作权限等级"""
    SAFE = "safe"           # 安全操作，自动放行
    NOTIFY = "notify"       # 通知用户但不阻塞
    CONFIRM = "confirm"     # 需用户确认
    DENY = "deny"           # 默认拒绝，需用户明确覆盖


class Category(Enum):
    """操作分类"""
    TOOL_CALL = "tool_call"           # Agent 调用工具
    DIRECTION_CHANGE = "direction"    # Eval Loop 改变执行方向
    RETRY = "retry"                   # 重试步骤
    CORRECT = "correct"               # 修正指令注入


# ── 工具权限表 ──
# 每新增一个工具，在这里添加权限等级

TOOL_PERMISSIONS: dict[str, PermissionLevel] = {
    # ── SAFE：只读/信息类 ──
    "get_time": PermissionLevel.SAFE,
    "get_current_time": PermissionLevel.SAFE,
    "convert_time": PermissionLevel.SAFE,
    "calculator": PermissionLevel.SAFE,
    "web_search": PermissionLevel.SAFE,
    "fetch_page": PermissionLevel.SAFE,
    "summarize": PermissionLevel.SAFE,
    "rag_query": PermissionLevel.SAFE,
    "search_files": PermissionLevel.SAFE,
    "read_text_file": PermissionLevel.SAFE,
    "list_directory": PermissionLevel.SAFE,
    "directory_tree": PermissionLevel.SAFE,
    "list_allowed_directories": PermissionLevel.SAFE,

    # ── NOTIFY：可能涉及敏感信息，通知用户 ──
    "get_file_info": PermissionLevel.NOTIFY,
    "read_env": PermissionLevel.NOTIFY,
    "mcp_list_tools": PermissionLevel.NOTIFY,
    "trajectory_replay": PermissionLevel.NOTIFY,
    "dashboard_query": PermissionLevel.NOTIFY,
    "get_memory": PermissionLevel.NOTIFY,
    "search_memory": PermissionLevel.NOTIFY,

    # ── CONFIRM：写操作，需用户确认 ──
    "write_file": PermissionLevel.CONFIRM,
    "patch_file": PermissionLevel.CONFIRM,
    "execute_python": PermissionLevel.CONFIRM,
    "execute_command": PermissionLevel.CONFIRM,
    "send_email": PermissionLevel.CONFIRM,
    "mcp_call_tool": PermissionLevel.CONFIRM,
    "save_memory": PermissionLevel.CONFIRM,
    "update_memory": PermissionLevel.CONFIRM,
    "delete_file": PermissionLevel.CONFIRM,
    "create_file": PermissionLevel.CONFIRM,

    # ── DENY：破坏性操作，默认拒绝 ──
    "delete_directory": PermissionLevel.DENY,
    "format_disk": PermissionLevel.DENY,
    "shutdown": PermissionLevel.DENY,
    "restart": PermissionLevel.DENY,
    "modify_system_config": PermissionLevel.DENY,
    "install_package": PermissionLevel.DENY,
    "uninstall_package": PermissionLevel.DENY,
}


# ── 方向调整权限 ──
# Eval Loop 在做出某些自动决策前，需要用户确认

DIRECTION_CHANGE_LEVELS: dict[str, PermissionLevel] = {
    "修正指令注入": PermissionLevel.CONFIRM,
    "重新执行步骤": PermissionLevel.CONFIRM,
    "更换 Provider 重试": PermissionLevel.CONFIRM,
    "跳过失败步骤": PermissionLevel.CONFIRM,
    "终止执行": PermissionLevel.CONFIRM,
    "调整温度参数": PermissionLevel.NOTIFY,
    "调整最大步数": PermissionLevel.NOTIFY,
    "增加测试用例": PermissionLevel.SAFE,
}


# ── 查询函数 ──


def get_tool_permission(tool_name: str) -> PermissionLevel:
    """获取工具的权限等级

    不在表中的工具默认 SAFE（安全优先原则）。
    """
    return TOOL_PERMISSIONS.get(tool_name, PermissionLevel.SAFE)


def get_direction_permission(action: str) -> PermissionLevel:
    """获取方向调整操作的权限等级"""
    return DIRECTION_CHANGE_LEVELS.get(action, PermissionLevel.CONFIRM)


def is_high_risk(level: PermissionLevel) -> bool:
    """是否高风险操作（需要用户参与）"""
    return level in (PermissionLevel.CONFIRM, PermissionLevel.DENY)


def describe_action(tool_name: str, args: Optional[dict] = None) -> str:
    """生成操作的可读描述（供用户确认时看）"""
    desc = f"调用工具：{tool_name}"
    if args:
        # 简略显示参数，敏感信息截断
        args_summary = {}
        for k, v in (args or {}).items():
            if isinstance(v, str) and len(v) > 100:
                args_summary[k] = v[:50] + "..."
            elif k.lower() in ("password", "secret", "key", "token", "api_key"):
                args_summary[k] = "******"
            else:
                args_summary[k] = v
        desc += f"\n  参数：{args_summary}"
    return desc
