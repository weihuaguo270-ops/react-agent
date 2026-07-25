"""Permission evaluate order + harness gate (deny → ask → allow)."""
from __future__ import annotations

import json
import os

import pytest

from react_agent.safety.permissions import (
    PermissionLevel,
    evaluate_tool_permission,
    get_tool_permission,
)
from react_agent.safety.permission_gate import permission_block_message, set_hitl
from react_agent.safety.human_in_the_loop import HumanInTheLoop


def test_deny_tool_table():
    d = evaluate_tool_permission("delete_directory", {})
    assert d.outcome == "deny"
    assert d.level == PermissionLevel.DENY


def test_deny_arg_beats_safe_path():
    """Sensitive content DENY must win over /tmp SAFE path rule."""
    d = evaluate_tool_permission(
        "write_file",
        {"path": "/tmp/secrets.txt", "content": "password=hunter2"},
    )
    assert d.outcome == "deny"
    assert d.source == "arg_rule"


def test_safe_path_allow():
    d = evaluate_tool_permission("write_file", {"path": "/tmp/out.txt", "content": "hi"})
    assert d.outcome == "allow"
    assert d.level == PermissionLevel.SAFE


def test_confirm_is_ask():
    d = evaluate_tool_permission("execute_python", {"code": "print(1)"})
    assert d.outcome == "ask"
    assert d.level == PermissionLevel.CONFIRM


def test_gate_blocks_deny(monkeypatch):
    monkeypatch.delenv("REACT_AGENT_PERMISSION_GATE", raising=False)
    set_hitl(None)
    msg = permission_block_message("shutdown", {})
    assert msg is not None
    data = json.loads(msg)
    assert data["outcome"] == "deny"
    assert "blocked by permission gate" in data["error"]


def test_gate_allows_safe(monkeypatch):
    monkeypatch.delenv("REACT_AGENT_PERMISSION_GATE", raising=False)
    set_hitl(None)
    assert permission_block_message("calculator", {"expression": "1+1"}) is None


def test_gate_can_disable(monkeypatch):
    monkeypatch.setenv("REACT_AGENT_PERMISSION_GATE", "0")
    set_hitl(None)
    assert permission_block_message("shutdown", {}) is None


def test_strict_confirm_blocks_without_hitl(monkeypatch):
    monkeypatch.delenv("REACT_AGENT_PERMISSION_GATE", raising=False)
    monkeypatch.setenv("REACT_AGENT_STRICT_CONFIRM", "1")
    set_hitl(None)
    msg = permission_block_message("execute_python", {"code": "print(1)"})
    assert msg is not None
    assert json.loads(msg)["outcome"] == "ask"


def test_hitl_can_override_deny(monkeypatch):
    monkeypatch.delenv("REACT_AGENT_PERMISSION_GATE", raising=False)
    monkeypatch.delenv("REACT_AGENT_STRICT_CONFIRM", raising=False)

    def always_yes(msg, choices):
        return "3"  # permanent allow in _ask_override UI

    set_hitl(HumanInTheLoop(ask_fn=always_yes))
    # DENY with ask_fn goes through override prompt; choice "3" = permanent allow
    assert permission_block_message("shutdown", {}) is None
    set_hitl(None)


def test_get_tool_permission_compat():
    assert get_tool_permission("calculator") == PermissionLevel.SAFE
    assert get_tool_permission("install_package") == PermissionLevel.DENY
