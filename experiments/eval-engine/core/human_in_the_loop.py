"""human_in_the_loop — 人工审批管理器

在 Agent 执行高风险操作或 Eval Loop 要调整方向前，暂停并询问用户。

设计目标：
  - 高风险操作必须人工确认
  - 默认拒绝破坏性操作（Deny by default）
  - 所有审批记录可审计
  - 支持超时自动拒绝（防止阻塞等待）
  - 与 clarify 工具兼容

用法（在 Eval Loop 中嵌入）：
    hitl = HumanInTheLoop(ask_fn=ask_user_callback)

    # 在工具调用前
    if not hitl.check_tool_call("delete_file", {"path": "/etc"}):
        return "操作被用户拒绝"

    # 在方向调整前
    if not hitl.check_direction("修正指令注入", details="将注入28行新指令"):
        # 用户不同意自动修正
        pass
"""

from __future__ import annotations
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from .permissions import (
    PermissionLevel,
    get_tool_permission,
    get_direction_permission,
    is_high_risk,
    describe_action,
)


# ── 审批记录 ──

@dataclass
class ApprovalRecord:
    """一次审批的完整记录（可审计）"""
    timestamp: str
    operation: str              # 操作描述
    category: str               # "tool_call" | "direction_change"
    level: str                  # 权限等级
    approved: bool              # 是否批准
    reason: str = ""            # 用户给出的理由（可选）
    timeout: bool = False       # 是否超时


# ── HITL 管理器 ──

class HumanInTheLoop:
    """人工审批管理器

    用法：
        hitl = HumanInTheLoop(
            ask_fn=lambda msg, choices: await_user_choice(msg, choices)
        )

        # 同步检查（返回是否允许）
        if hitl.check_tool_call("execute_python", {"code": "..."}):
            execute()
        else:
            cancel()

        # 获取所有审批记录
        for record in hitl.audit_log:
            print(record)
    """

    def __init__(
        self,
        ask_fn: Optional[Callable[[str, list[str]], str]] = None,
        auto_approve_safe: bool = True,
        default_timeout: float = 60.0,
        audit_log_size: int = 100,
    ):
        """初始化 HITL 管理器

        参数:
            ask_fn: 询问用户的回调函数。
                    输入 (message, choices) → 返回用户选择的选项文本。
                    传 None 时自动批准所有操作（测试/非交互模式）。
            auto_approve_safe: 是否自动放行 SAFE 操作（默认 True）
            default_timeout:    用户未响应时的超时秒数
            audit_log_size:     审计日志最大条数
        """
        self.ask_fn = ask_fn
        self.auto_approve_safe = auto_approve_safe
        self.default_timeout = default_timeout
        self.audit_log: list[ApprovalRecord] = []
        self._max_log = audit_log_size

    # ── 公开 API ──

    def check_tool_call(
        self,
        tool_name: str,
        tool_args: Optional[dict] = None,
        reason: str = "",
    ) -> bool:
        """在 Agent 调用工具前检查权限

        参数:
            tool_name: 工具名
            tool_args: 工具参数
            reason:    调用的理由说明

        返回:
            True  = 允许执行
            False = 拒绝执行
        """
        level = get_tool_permission(tool_name)
        desc = describe_action(tool_name, tool_args)
        return self._check(
            operation=desc,
            category="tool_call",
            level=level,
            reason=reason,
        )

    def check_direction(
        self,
        action: str,
        details: str = "",
    ) -> bool:
        """在 Eval Loop 调整方向前检查权限

        参数:
            action:  操作描述，如 "修正指令注入"
            details: 详细说明

        返回:
            True  = 允许
            False = 拒绝
        """
        level = get_direction_permission(action)
        desc = f"{action}：{details}" if details else action
        return self._check(
            operation=desc,
            category="direction_change",
            level=level,
        )

    # ── 内部逻辑 ──

    def _check(
        self,
        operation: str,
        category: str,
        level: PermissionLevel,
        reason: str = "",
    ) -> bool:
        """统一的权限检查逻辑"""
        approved = True
        timeout = False

        if level == PermissionLevel.SAFE:
            # SAFE：自动放行
            if self.auto_approve_safe:
                return True
            approved = True

        elif level == PermissionLevel.NOTIFY:
            # NOTIFY：通知但不阻塞
            self._notify(operation, reason)
            approved = True

        elif level == PermissionLevel.CONFIRM:
            # CONFIRM：需用户确认
            if self.ask_fn is None:
                approved = True  # 非交互模式默认放行
            else:
                approved, timeout = self._ask_confirm(operation, reason)

        elif level == PermissionLevel.DENY:
            # DENY：默认拒绝，除非用户明确覆盖
            if self.ask_fn is None:
                approved = False  # 非交互模式默认拒绝
            else:
                approved, timeout = self._ask_override(operation, reason)

        # 记录审计
        self._log(ApprovalRecord(
            timestamp=time.strftime("%Y-%m-%dT%H:%M:%S"),
            operation=operation[:200],
            category=category,
            level=level.value,
            approved=approved,
            reason=reason[:100],
            timeout=timeout,
        ))

        return approved

    def _ask_confirm(self, operation: str, reason: str) -> tuple[bool, bool]:
        """询问用户是否批准操作"""
        msg = f"🔐 Agent 请求执行以下操作：\n\n{operation}"
        if reason:
            msg += f"\n\n理由：{reason}"
        msg += "\n\n是否允许？"

        try:
            choice = self.ask_fn(msg, ["✅ 允许", "❌ 拒绝", "🔍 查看详情"])
            if "允许" in choice or "✅" in choice:
                return True, False
            return False, False
        except Exception:
            return False, True  # 超时 = 拒绝

    def _ask_override(self, operation: str, reason: str) -> tuple[bool, bool]:
        """询问用户是否覆盖默认拒绝"""
        msg = f"🚫 Agent 尝试执行高风险操作：\n\n{operation}"
        if reason:
            msg += f"\n\n理由：{reason}"
        msg += "\n\n此操作默认拒绝。是否要覆盖并允许？"

        try:
            choice = self.ask_fn(msg, ["🚫 保持拒绝", "⚠ 仅此一次允许", "🔓 今后允许此类操作"])
            if "允许" in choice or "🔓" in choice:
                return True, False
            return False, False
        except Exception:
            return False, True  # 超时 = 拒绝

    def _notify(self, operation: str, reason: str = "") -> None:
        """通知用户但不阻塞"""
        if self.ask_fn is None:
            return
        msg = f"ℹ️ Agent 正在执行：{operation}"
        if reason:
            msg += f"\n\n原因：{reason}"
        try:
            self.ask_fn(msg, ["知道了"])
        except Exception:
            pass

    def _log(self, record: ApprovalRecord) -> None:
        """记录审计日志"""
        self.audit_log.append(record)
        if len(self.audit_log) > self._max_log:
            self.audit_log.pop(0)

    # ── 审计接口 ──

    def recent_approvals(self, n: int = 10) -> list[ApprovalRecord]:
        """最近 n 条审批记录"""
        return self.audit_log[-n:]

    def stats(self) -> dict[str, Any]:
        """审批统计"""
        total = len(self.audit_log)
        approved = sum(1 for r in self.audit_log if r.approved)
        denied = sum(1 for r in self.audit_log if not r.approved)
        timed_out = sum(1 for r in self.audit_log if r.timeout)
        return {
            "total_checks": total,
            "approved": approved,
            "denied": denied,
            "timed_out": timed_out,
            "approval_rate": round(approved / total, 3) if total else 0,
        }

    # ── 工具方法 ──

    def tool_call_blocker(self, tool_name: str, tool_args: dict) -> Optional[str]:
        """可用作工具调用的装饰器/拦截器

        返回 None 表示允许执行，返回字符串表示拒绝理由。
        """
        if self.check_tool_call(tool_name, tool_args):
            return None
        return f"操作被用户拒绝：{tool_name}"

    def __repr__(self) -> str:
        return (
            f"HumanInTheLoop("
            f"ask_fn={'✓' if self.ask_fn else '✗'}, "
            f"auto_approve_safe={self.auto_approve_safe}, "
            f"audit_log={len(self.audit_log)} entries)"
        )
