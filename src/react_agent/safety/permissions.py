"""permissions — 操作权限等级与工具分类（生产向：deny→ask→allow）

为 Agent 的每次操作定义风险等级，控制哪些操作需要人工审批。
本模块是运行时权限闸门依据，不是 OS ACL。

等级：SAFE / NOTIFY / CONFIRM / DENY
评估顺序：DENY → ASK(CONFIRM) → ALLOW

v2：参数级权限（Argument Rules）
  write_file /tmp/* → SAFE；write_file /etc/* → CONFIRM；
  execute_python 含 os.system → 抬升 CONFIRM
"""
from __future__ import annotations
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, Literal, Optional


class PermissionLevel(Enum):
    """操作权限等级"""
    SAFE = "safe"
    NOTIFY = "notify"
    CONFIRM = "confirm"
    DENY = "deny"


class Category(Enum):
    """操作分类"""
    TOOL_CALL = "tool_call"
    DIRECTION_CHANGE = "direction"
    RETRY = "retry"
    CORRECT = "correct"


Outcome = Literal["deny", "ask", "allow"]


@dataclass(frozen=True)
class PermissionDecision:
    """一次工具调用的权限裁决（供 Harness 闸门使用）。"""

    level: PermissionLevel
    outcome: Outcome
    reason: str
    source: str  # "arg_rule" | "tool_table" | "default"


# ── 工具权限表（工具名 → 默认等级） ──

TOOL_PERMISSIONS: dict[str, PermissionLevel] = {
    # SAFE
    "get_time": PermissionLevel.SAFE,
    "get_current_time": PermissionLevel.SAFE,
    "convert_time": PermissionLevel.SAFE,
    "calculator": PermissionLevel.SAFE,
    "web_search": PermissionLevel.SAFE,
    "fetch_page": PermissionLevel.SAFE,
    "summarize": PermissionLevel.SAFE,
    "rag_query": PermissionLevel.SAFE,
    "search_docs": PermissionLevel.SAFE,
    "lookup_api": PermissionLevel.SAFE,
    "verify_citations": PermissionLevel.SAFE,
    "list_workflows": PermissionLevel.SAFE,
    "run_workflow": PermissionLevel.SAFE,
    "apply_fix_step": PermissionLevel.CONFIRM,
    "fetch_trace": PermissionLevel.SAFE,
    "search_files": PermissionLevel.SAFE,
    "read_text_file": PermissionLevel.SAFE,
    "list_directory": PermissionLevel.SAFE,
    "directory_tree": PermissionLevel.SAFE,
    "list_allowed_directories": PermissionLevel.SAFE,

    # NOTIFY
    "get_file_info": PermissionLevel.NOTIFY,
    "read_env": PermissionLevel.NOTIFY,
    "mcp_list_tools": PermissionLevel.NOTIFY,
    "trajectory_replay": PermissionLevel.NOTIFY,
    "dashboard_query": PermissionLevel.NOTIFY,
    "get_memory": PermissionLevel.NOTIFY,
    "search_memory": PermissionLevel.NOTIFY,

    # CONFIRM
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

    # DENY
    "delete_directory": PermissionLevel.DENY,
    "format_disk": PermissionLevel.DENY,
    "shutdown": PermissionLevel.DENY,
    "restart": PermissionLevel.DENY,
    "modify_system_config": PermissionLevel.DENY,
    "install_package": PermissionLevel.DENY,
    "uninstall_package": PermissionLevel.DENY,
}

# ── 方向调整权限 ──

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


# ── 参数级规则（v2） ──
# DENY 规则在 evaluate 的 deny 阶段统一扫描，始终优先于 SAFE 放宽

ArgChecker = Callable[[dict[str, Any]], bool]


def _path_contains(substring: str) -> ArgChecker:
    """参数中的 path 包含指定子串"""
    def check(args: dict) -> bool:
        path = str(args.get("path", "") or args.get("filepath", "") or "")
        return substring in path
    return check


def _key_contains(substring: str) -> ArgChecker:
    def check(args: dict) -> bool:
        blob = " ".join(f"{k}={v}" for k, v in args.items()).lower()
        return substring.lower() in blob
    return check


def _code_contains(substring: str) -> ArgChecker:
    def check(args: dict) -> bool:
        code = str(args.get("code", "") or args.get("expression", "") or "")
        return substring in code
    return check


ARG_RULES: list[tuple[str, ArgChecker, PermissionLevel]] = [
    ("write_file", _key_contains("password"), PermissionLevel.DENY),
    ("write_file", _key_contains("secret"), PermissionLevel.DENY),
    ("write_file", _key_contains("api_key"), PermissionLevel.DENY),
    ("write_file", _path_contains("/tmp/"), PermissionLevel.SAFE),
    ("write_file", _path_contains("/Temp/"), PermissionLevel.SAFE),
    ("write_file", _path_contains("temp"), PermissionLevel.SAFE),
    ("write_file", _path_contains("/etc/"), PermissionLevel.CONFIRM),
    ("write_file", _path_contains("/usr/"), PermissionLevel.CONFIRM),
    ("execute_python", _code_contains("os.system"), PermissionLevel.CONFIRM),
    ("execute_python", _code_contains("subprocess"), PermissionLevel.CONFIRM),
    ("execute_python", _code_contains("shutil.rmtree"), PermissionLevel.DENY),
    ("execute_python", _code_contains("os.remove"), PermissionLevel.CONFIRM),
    ("execute_python", _code_contains("__import__"), PermissionLevel.CONFIRM),
]


def _level_to_outcome(level: PermissionLevel) -> Outcome:
    if level == PermissionLevel.DENY:
        return "deny"
    if level == PermissionLevel.CONFIRM:
        return "ask"
    return "allow"


def evaluate_tool_permission(
    tool_name: str,
    tool_args: Optional[dict] = None,
) -> PermissionDecision:
    """按 deny → ask → allow 顺序裁决工具调用。

    模型产生 tool_call 不等于允许执行；本函数结果由 Harness 强制执行。
    """
    args = tool_args or {}
    base = TOOL_PERMISSIONS.get(tool_name, PermissionLevel.SAFE)
    base_source = "tool_table" if tool_name in TOOL_PERMISSIONS else "default"

    # ── 1) DENY ──
    for name, checker, level in ARG_RULES:
        if name == tool_name and level == PermissionLevel.DENY and checker(args):
            return PermissionDecision(
                level=PermissionLevel.DENY,
                outcome="deny",
                reason=f"arg DENY rule matched for {tool_name}",
                source="arg_rule",
            )
    if base == PermissionLevel.DENY:
        return PermissionDecision(
            level=PermissionLevel.DENY,
            outcome="deny",
            reason=f"tool {tool_name} is DENY in tool table",
            source="tool_table",
        )

    # ── 2/3) ASK / ALLOW via remaining arg rules, else base ──
    for name, checker, level in ARG_RULES:
        if name == tool_name and level != PermissionLevel.DENY and checker(args):
            return PermissionDecision(
                level=level,
                outcome=_level_to_outcome(level),
                reason=f"arg rule set {tool_name} → {level.value}",
                source="arg_rule",
            )

    return PermissionDecision(
        level=base,
        outcome=_level_to_outcome(base),
        reason=f"default level {base.value} ({base_source})",
        source=base_source,
    )


def get_tool_permission(
    tool_name: str,
    tool_args: Optional[dict] = None,
) -> PermissionLevel:
    """获取工具的权限等级（deny-first；兼容旧调用方）。"""
    return evaluate_tool_permission(tool_name, tool_args).level


def get_direction_permission(action: str) -> PermissionLevel:
    return DIRECTION_CHANGE_LEVELS.get(action, PermissionLevel.CONFIRM)


def is_high_risk(level: PermissionLevel) -> bool:
    return level in (PermissionLevel.CONFIRM, PermissionLevel.DENY)


def describe_action(tool_name: str, args: Optional[dict] = None) -> str:
    """生成操作的可读描述"""
    desc = f"调用工具：{tool_name}"
    if args:
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
