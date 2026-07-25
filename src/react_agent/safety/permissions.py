"""permissions — 操作权限等级与工具分类（学习用提示策略）

为 Agent 的每次操作定义风险等级，控制哪些操作需要人工审批。

等级划分：
  SAFE     — 纯读取，无需审批
  NOTIFY   — 读取敏感信息，通知用户但不阻塞
  CONFIRM  — 写入/执行，需用户确认（ask）
  DENY     — 表内登记的高风险工具名，默认拒绝

评估顺序（Harness 强制，模型 prompt 改不了允许集）：
  1. DENY  — 参数级 DENY 规则，或工具默认 DENY
  2. ASK   — CONFIRM（及参数级抬升到 CONFIRM）
  3. ALLOW — SAFE / NOTIFY（及参数级放宽）

诚实边界：
  - 主要按 **工具名查表**；不是对 shell/路径的通配拦截（不会解析 “rm -rf”）
  - 未登记的工具名不自动 DENY
  - 本模块是 HITL 提示层，不是 OS 权限系统
  - 与 ``harness.sandbox`` 是两层：权限决定「能不能调」；沙箱只隔离崩溃/超时

v2 新增：参数级权限（Argument Rules）
  根据工具参数动态调整权限等级：
    write_file /tmp/* → SAFE（临时文件）
    write_file /etc/* → CONFIRM（系统配置）
    execute_python 含 os.system → 自动提升为 CONFIRM
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
