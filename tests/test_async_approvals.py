"""异步人工审批（HITL over HTTP）回归测试。

设计要点：审批被建模为**状态**而非消息——HTTP 请求无法挂着等人几分钟，
因此不存在"在流中途来回"的需求，也就不需要 WebSocket。

流程：命中 CONFIRM → 落盘待批项 → 本次 run 返回 awaiting_approval →
人工经独立 HTTP 批准/拒绝 → 客户端带 approval_id 重试 → 放行。
"""
from __future__ import annotations

import json
import os
import sys
import time

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))


@pytest.fixture
def approval_dir(tmp_path, monkeypatch):
    """隔离待批项存储，避免污染真实运行目录。"""
    monkeypatch.setenv("REACT_AGENT_APPROVAL_DIR", str(tmp_path / "approvals"))
    monkeypatch.setenv("REACT_AGENT_APPROVAL_MODE", "async")
    monkeypatch.delenv("REACT_AGENT_STRICT_CONFIRM", raising=False)
    from react_agent.safety import approvals

    yield tmp_path / "approvals"
    # 清理请求级信号，避免跨测试泄漏
    approvals.take_pending_approval()


@pytest.fixture(autouse=True)
def _reset_signals():
    from react_agent.safety import approvals
    from react_agent.safety.permission_gate import set_approval_credential, set_hitl

    set_hitl(None)
    set_approval_credential("")
    approvals.take_pending_approval()
    yield
    set_approval_credential("")
    approvals.take_pending_approval()


# ── 存储层 ──


def test_create_and_list_pending(approval_dir):
    from react_agent.safety import approvals

    assert approvals.list_pending() == []
    record = approvals.create_pending(
        tool="execute_python", arguments={"code": "print(1)"}, description="运行代码"
    )
    pending = approvals.list_pending()
    assert len(pending) == 1
    assert pending[0]["approval_id"] == record["approval_id"]
    assert pending[0]["status"] == "pending"
    assert pending[0]["tool"] == "execute_python"


def test_resolve_approve_and_deny(approval_dir):
    from react_agent.safety import approvals

    ok_rec = approvals.create_pending(tool="t1", arguments={})
    ok, resolved = approvals.resolve(ok_rec["approval_id"], decision="approve", scope="once")
    assert ok and resolved["status"] == "approved"

    deny_rec = approvals.create_pending(tool="t2", arguments={})
    ok2, resolved2 = approvals.resolve(deny_rec["approval_id"], decision="deny")
    assert ok2 and resolved2["status"] == "denied"


def test_resolve_rejects_unknown_and_double_resolve(approval_dir):
    from react_agent.safety import approvals

    ok, err = approvals.resolve("does-not-exist", decision="approve")
    assert ok is False and err["error"] == "approval_not_found"

    rec = approvals.create_pending(tool="t", arguments={})
    approvals.resolve(rec["approval_id"], decision="approve")
    ok2, err2 = approvals.resolve(rec["approval_id"], decision="approve")
    assert ok2 is False and err2["error"] == "approval_not_pending"


def test_resolve_rejects_invalid_decision_and_scope(approval_dir):
    from react_agent.safety import approvals

    rec = approvals.create_pending(tool="t", arguments={})
    ok, err = approvals.resolve(rec["approval_id"], decision="maybe")
    assert ok is False and err["error"] == "invalid_decision"
    ok2, err2 = approvals.resolve(rec["approval_id"], decision="approve", scope="forever")
    assert ok2 is False and err2["error"] == "invalid_scope"


def test_expired_pending_is_not_listed(approval_dir):
    from react_agent.safety import approvals

    approvals.create_pending(tool="t", arguments={}, ttl_seconds=-1.0)
    assert approvals.list_pending() == []


def test_once_credential_cannot_be_reused(approval_dir):
    from react_agent.safety import approvals

    rec = approvals.create_pending(tool="t", arguments={})
    approvals.resolve(rec["approval_id"], decision="approve", scope="once")
    assert approvals.consume(rec["approval_id"]) == (True, "once")
    allowed, reason = approvals.consume(rec["approval_id"])
    assert allowed is False and reason == "approval_already_used"


def test_session_grant_is_reusable(approval_dir):
    from react_agent.safety import approvals

    rec = approvals.create_pending(tool="t", arguments={}, tool_key="tool:execute_python")
    approvals.resolve(rec["approval_id"], decision="approve", scope="session")
    assert approvals.session_grant_for("tool:execute_python") is True
    assert approvals.consume(rec["approval_id"]) == (True, "session_grant")
    assert approvals.consume(rec["approval_id"]) == (True, "session_grant")


def test_denied_credential_is_not_consumable(approval_dir):
    from react_agent.safety import approvals

    rec = approvals.create_pending(tool="t", arguments={})
    approvals.resolve(rec["approval_id"], decision="deny")
    allowed, reason = approvals.consume(rec["approval_id"])
    assert allowed is False and reason == "approval_denied"


def test_approval_id_path_traversal_is_neutralized(approval_dir):
    """approval_id 会被拼进文件名，必须无害化。"""
    from react_agent.safety import approvals

    assert approvals.get("../../etc/passwd") is None
    assert approvals.consume("../../etc/passwd")[0] is False


# ── 闸门层 ──


def test_confirm_tool_blocks_and_registers_pending(approval_dir):
    from react_agent.safety import approvals
    from react_agent.safety.permission_gate import permission_block_message

    msg = permission_block_message("execute_python", {"code": "print(1)"})
    assert msg is not None
    payload = json.loads(msg)
    assert payload["error"] == "approval_required"
    assert payload["approval_id"]
    assert len(approvals.list_pending()) == 1


def test_safe_tool_is_not_blocked_in_async_mode(approval_dir):
    from react_agent.safety.permission_gate import permission_block_message

    assert permission_block_message("calculator", {"expression": "1+1"}) is None


def test_credential_allows_execution(approval_dir):
    from react_agent.safety import approvals
    from react_agent.safety.permission_gate import (
        permission_block_message,
        set_approval_credential,
    )

    msg = json.loads(permission_block_message("execute_python", {"code": "x"}))
    approvals.resolve(msg["approval_id"], decision="approve", scope="once")
    set_approval_credential(msg["approval_id"])
    assert permission_block_message("execute_python", {"code": "x"}) is None


def test_session_grant_allows_without_credential(approval_dir):
    from react_agent.safety import approvals
    from react_agent.safety.permission_gate import permission_block_message

    msg = json.loads(permission_block_message("execute_python", {"code": "x"}))
    approvals.resolve(msg["approval_id"], decision="approve", scope="session")
    # 无需凭据，同类工具在有效期内直接放行
    assert permission_block_message("execute_python", {"code": "y"}) is None


def test_denied_approval_keeps_blocking(approval_dir):
    from react_agent.safety import approvals
    from react_agent.safety.permission_gate import (
        permission_block_message,
        set_approval_credential,
    )

    msg = json.loads(permission_block_message("execute_python", {"code": "x"}))
    approvals.resolve(msg["approval_id"], decision="deny")
    set_approval_credential(msg["approval_id"])
    blocked = permission_block_message("execute_python", {"code": "x"})
    assert blocked is not None
    assert "approval" in blocked


def test_store_failure_fails_closed(monkeypatch, approval_dir):
    """审批目录不可写时必须**拒绝**执行，绝不退化为放行。"""
    from react_agent.safety import approvals
    from react_agent.safety.permission_gate import permission_block_message

    def _boom(*args, **kwargs):
        raise approvals.ApprovalStoreError("disk full")

    monkeypatch.setattr(approvals, "create_pending", _boom)
    msg = permission_block_message("execute_python", {"code": "x"})
    payload = json.loads(msg)
    assert payload["error"] == "approval_store_unavailable"
    assert payload["outcome"] == "deny"


def test_auto_allow_mode_unaffected(monkeypatch, approval_dir):
    """关闭异步审批时保持原有行为（不阻塞）。"""
    monkeypatch.setenv("REACT_AGENT_APPROVAL_MODE", "auto_allow")
    from react_agent.safety.permission_gate import permission_block_message

    assert permission_block_message("execute_python", {"code": "x"}) is None


# ── 响应侧信号 ──


def test_structured_pending_signal_is_preferred(approval_dir):
    from react_agent.safety import approvals
    from react_agent.server.health import capture_approval_status

    record = approvals.create_pending(tool="execute_python", arguments={})
    approvals.note_approval_required(record)
    # 载荷里没有任何 approval 文本，也应能从结构化信号取到
    assert capture_approval_status({"answer": "普通答复"}) == record["approval_id"]
    # take 语义：第二次应为空
    assert capture_approval_status({"answer": "普通答复"}) is None


def test_capture_falls_back_to_text_when_signal_absent(approval_dir):
    from react_agent.server.health import capture_approval_status

    payload = {
        "answer": "x",
        "agent_steps": [
            {"observation": json.dumps({"error": "approval_required", "approval_id": "abcdef123456"})}
        ],
    }
    assert capture_approval_status(payload) == "abcdef123456"


def test_capture_handles_escaped_and_wrapped_text(approval_dir):
    from react_agent.server.health import capture_approval_status

    escaped = json.dumps('{"error": "approval_required", "approval_id": "deadbeef99"}')
    assert capture_approval_status({"answer": escaped}) == "deadbeef99"
    wrapped = json.dumps({"error": '执行错误: {"approval_id": "cafebabe01"}'})
    assert capture_approval_status({"answer": wrapped}) == "cafebabe01"


def test_capture_returns_none_for_normal_payload(approval_dir):
    from react_agent.server.health import capture_approval_status

    assert capture_approval_status({"answer": "FINAL ANSWER: 42"}) is None


# ── 审批目录可覆盖 ──


def test_approval_dir_env_override(monkeypatch, tmp_path):
    target = tmp_path / "custom"
    monkeypatch.setenv("REACT_AGENT_APPROVAL_DIR", str(target))
    from react_agent.safety import approvals

    assert approvals.approvals_dir() == target
    approvals.create_pending(tool="t", arguments={})
    assert (target / f"{approvals.list_pending()[0]['approval_id']}.json").is_file()
