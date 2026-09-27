"""异步人工审批（HITL over stateless HTTP）。

背景：``human_in_the_loop.py`` 的交互式审批要求**同一个通道在中途来回**，而 HTTP
请求无法挂着等人几分钟。因此审批被建模为**状态**而非消息：

1. 工具命中 ``CONFIRM`` → 写入待批项（持久化）→ 本次 run 返回
   ``awaiting_approval``，并发出 ``approval_required`` 事件；
2. 人工经独立 HTTP 请求批准/拒绝；
3. 客户端带 ``approval_id`` 重试，闸门放行。

这样不需要 WebSocket，且审批可审计、可重试、跨进程重启不丢。
"""
from __future__ import annotations

import json
import os
import secrets
import time
import uuid
from contextvars import ContextVar
from pathlib import Path
from typing import Any, Optional

from react_agent.paths import runtime_dir

_STATUS_PENDING = "pending"
_STATUS_APPROVED = "approved"
_STATUS_DENIED = "denied"


class ApprovalStoreError(RuntimeError):
    """待批项无法持久化。

    刻意**不**退化为"放行"：审批是失败关闭机制，存不下待批项说明无人能把关，
    此时拒绝执行才是正确行为。
    """

# 单次授权在批准后仍保留的有效期（给客户端留出重试窗口）
_TEMP_AUTH_TTL_SECONDS = 300.0


def approvals_dir() -> Path:
    return runtime_dir("approvals", env_var="REACT_AGENT_APPROVAL_DIR")


def _path(approval_id: str) -> Path:
    # 只允许安全字符，避免 approval_id 变成路径穿越
    safe = "".join(ch for ch in approval_id if ch.isalnum() or ch in "-_")
    if not safe:
        raise ValueError("invalid approval_id")
    return approvals_dir() / f"{safe}.json"


def _write(record: dict[str, Any]) -> None:
    path = _path(str(record["approval_id"]))
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def _read(approval_id: str) -> Optional[dict[str, Any]]:
    try:
        path = _path(approval_id)
    except ValueError:
        return None
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def create_pending(
    *,
    tool: str,
    arguments: dict[str, Any],
    description: str = "",
    reason: str = "",
    tool_key: str = "",
    request_id: str = "",
    ttl_seconds: float = 900.0,
) -> dict[str, Any]:
    """登记一个待批项并返回其记录。

    持久化失败时**抛异常**（不是静默放行）：审批是有意采用的失败关闭机制，
    写不下待批项就意味着无人能把关，此时宁可不执行。
    """
    record = {
        "approval_id": uuid.uuid4().hex,
        "status": _STATUS_PENDING,
        "tool": tool,
        "tool_key": tool_key or f"tool:{tool}",
        "arguments": arguments,
        "description": description[:400],
        "reason": reason[:400],
        "request_id": request_id,
        "scope": "",
        "created_at": time.time(),
        "expires_at": time.time() + ttl_seconds,
    }
    try:
        _write(record)
    except OSError as exc:
        raise ApprovalStoreError(
            f"无法持久化待批项（审批目录不可写？{approvals_dir()}）: {exc}"
        ) from exc
    return record


def get(approval_id: str) -> Optional[dict[str, Any]]:
    return _read(approval_id)


def list_pending() -> list[dict[str, Any]]:
    """未决且未过期的待批项（按创建时间升序）。"""
    out: list[dict[str, Any]] = []
    root = approvals_dir()
    if not root.is_dir():
        return out
    now = time.time()
    for path in sorted(root.glob("*.json")):
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if record.get("status") != _STATUS_PENDING:
            continue
        if float(record.get("expires_at") or 0) <= now:
            record["status"] = "expired"
            try:
                _write(record)
            except OSError:
                pass
            continue
        out.append(record)
    out.sort(key=lambda r: float(r.get("created_at") or 0))
    return out


def resolve(
    approval_id: str,
    *,
    decision: str,
    scope: str = "once",
    approver: str = "",
) -> tuple[bool, dict[str, Any]]:
    """批准/拒绝一个待批项。返回 ``(ok, record_or_error)``。"""
    record = _read(approval_id)
    if record is None:
        return False, {"error": "approval_not_found", "approval_id": approval_id}
    if record.get("status") != _STATUS_PENDING:
        return False, {"error": "approval_not_pending", "status": record.get("status")}
    if float(record.get("expires_at") or 0) <= time.time():
        record["status"] = "expired"
        _write(record)
        return False, {"error": "approval_expired", "approval_id": approval_id}

    decision = (decision or "").strip().lower()
    if decision not in ("approve", "deny"):
        return False, {"error": "invalid_decision", "decision": decision}
    scope = (scope or "once").strip().lower()
    if scope not in ("once", "session"):
        return False, {"error": "invalid_scope", "scope": scope}

    record["status"] = _STATUS_APPROVED if decision == "approve" else _STATUS_DENIED
    record["scope"] = scope
    record["approver"] = approver
    record["resolved_at"] = time.time()
    if decision == "approve" and scope == "session":
        # 会话级授权：后续同类工具调用直接放行，直至进程重启或过期
        record["grant_expires_at"] = time.time() + _TEMP_AUTH_TTL_SECONDS
    _write(record)
    return True, record


def consume(approval_id: str) -> tuple[bool, str]:
    """尝试用掉一个批准记录。返回 ``(allowed, reason)``。

    - 找不到 / 未批准 / 已过期 → 拒绝
    - 单次（once）：用掉后立即作废，防止重复利用
    - 会话（session）：在有效期内可重复使用
    """
    record = _read(approval_id)
    if record is None:
        return False, "approval_not_found"
    status = record.get("status")
    if status == _STATUS_DENIED:
        return False, "approval_denied"
    # 已被用掉的一次性凭据：给出更具体的原因（先于状态判断）
    if record.get("consumed_at"):
        return False, "approval_already_used"
    if status != _STATUS_APPROVED:
        return False, f"approval_{status or 'unknown'}"
    scope = record.get("scope") or "once"
    if scope == "session":
        if time.time() > float(record.get("grant_expires_at") or 0):
            return False, "approval_expired"
        return True, "session_grant"
    # once：标记已用，防止同一 approval_id 被反复消费
    record["consumed_at"] = time.time()
    record["status"] = "consumed"
    _write(record)
    return True, "once"


def session_grant_for(tool_key: str) -> bool:
    """是否已有覆盖该工具的、仍在有效期内的会话级授权。"""
    root = approvals_dir()
    if not root.is_dir():
        return False
    now = time.time()
    for path in root.glob("*.json"):
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if record.get("tool_key") != tool_key:
            continue
        if record.get("status") != _STATUS_APPROVED:
            continue
        if (record.get("scope") or "") != "session":
            continue
        if now <= float(record.get("grant_expires_at") or 0):
            return True
    return False


def new_approval_token() -> str:
    """用于 approver 标识的默认值（避免留空）。"""
    return secrets.token_hex(4)


def purge_expired(*, keep_seconds: float = 86400.0) -> int:
    """清理早已过期的记录（默认保留 1 天便于审计查询）。"""
    root = approvals_dir()
    if not root.is_dir():
        return 0
    removed = 0
    cutoff = time.time() - keep_seconds
    for path in root.glob("*.json"):
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        created = float(record.get("created_at") or 0)
        expires = float(record.get("expires_at") or 0)
        if max(created, expires) < cutoff:
            try:
                path.unlink()
                removed += 1
            except OSError:
                pass
    return removed


def approval_mode() -> str:
    """审批模式：async（异步审批）/ auto_allow（默认放行）。"""
    raw = os.environ.get("REACT_AGENT_APPROVAL_MODE", "").strip().lower()
    if raw in ("async", "auto_allow", "off"):
        return "auto_allow" if raw == "off" else raw
    return "auto_allow"


def async_approval_enabled() -> bool:
    return approval_mode() == "async"


# ── 请求级「待审批」信号 ──
# 工具观测会被截断（trajectory 只留 500 字符），依赖字符串解析不可靠；
# 这里用 ContextVar 直接记录结构化信号，由响应侧读取后标注 awaiting_approval。
_PENDING_SIGNAL: ContextVar[Optional[dict[str, Any]]] = ContextVar(
    "react_agent_pending_approval", default=None
)


def note_approval_required(record: dict[str, Any]) -> None:
    _PENDING_SIGNAL.set(record)


def take_pending_approval() -> Optional[dict[str, Any]]:
    """读取并清空本次请求的待审批信号（幂等：第二次返回 None）。"""
    record = _PENDING_SIGNAL.get()
    if record is not None:
        _PENDING_SIGNAL.set(None)
    return record
