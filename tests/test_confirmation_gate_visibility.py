"""CONFIRM 闸门可见性回归测试。

默认 ``REACT_AGENT_APPROVAL_MODE=async``：副作用 CONFIRM 有人把关。
显式 ``auto_allow`` 时必须暴露未把关的副作用工具清单（启动告警 + ``/ready``）。
"""
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from react_agent.server.health import (  # noqa: E402
    confirmation_gate_startup_warning,
    confirmation_gate_status,
)


@pytest.fixture(autouse=True)
def _clean_gate_env(monkeypatch):
    """显式清空影响闸门的变量，并还原 HITL 注入。"""
    from react_agent.safety.permission_gate import get_hitl, set_hitl

    original = get_hitl()
    monkeypatch.delenv("REACT_AGENT_STRICT_CONFIRM", raising=False)
    monkeypatch.delenv("REACT_AGENT_SANDBOX_REQUIRED", raising=False)
    monkeypatch.delenv("REACT_AGENT_APPROVAL_MODE", raising=False)
    try:
        yield
    finally:
        set_hitl(original)


def test_default_mode_is_async_and_enforced():
    """未设环境变量时默认 async，不应告警。"""
    status = confirmation_gate_status()
    assert status["mode"] == "async"
    assert status["unenforced_confirm_tools"] == []
    assert confirmation_gate_startup_warning() is None


def test_async_mode_is_reported_as_enforced(monkeypatch):
    """显式 async 下副作用 CONFIRM 已有人把关。"""
    monkeypatch.setenv("REACT_AGENT_APPROVAL_MODE", "async")
    status = confirmation_gate_status()
    assert status["mode"] == "async"
    assert status["unenforced_confirm_tools"] == []
    assert confirmation_gate_startup_warning() is None


def test_auto_allow_mode_is_reported(monkeypatch):
    monkeypatch.setenv("REACT_AGENT_APPROVAL_MODE", "auto_allow")
    status = confirmation_gate_status()
    assert status["mode"] == "auto_allow"
    assert status["unenforced_confirm_tools"], "auto_allow 应报告自动放行的副作用 CONFIRM"
    assert status["warning"]


def test_auto_allow_lists_reachable_side_effect_tools(monkeypatch):
    """默认沙箱（auto/process）下真正在宿主执行的是 execute_python 与 clear_trajectories。"""
    monkeypatch.setenv("REACT_AGENT_APPROVAL_MODE", "auto_allow")
    status = confirmation_gate_status()
    assert "execute_python" in status["unenforced_confirm_tools"]
    assert "clear_trajectories" in status["unenforced_confirm_tools"]
    # CONFIRM_READ 不进副作用未把关清单
    assert "read_config_snapshot" not in status["unenforced_confirm_tools"]
    assert "probe_service_health" not in status["unenforced_confirm_tools"]


def test_confirm_read_reported_unreachable_under_default_sandbox(monkeypatch):
    """CONFIRM_READ 不在沙箱子进程注册表里 → 默认配置下不可达。"""
    monkeypatch.setenv("REACT_AGENT_APPROVAL_MODE", "auto_allow")
    status = confirmation_gate_status()
    unreachable = status.get("unreachable_confirm_tools") or []
    assert "read_config_snapshot" in unreachable
    assert "read_config_snapshot" not in status["unenforced_confirm_tools"]
    assert "read_config_snapshot" not in (status.get("auto_allowed_confirm_read_tools") or [])


def test_sandbox_off_makes_confirm_read_listed(monkeypatch):
    """沙箱关闭后 CONFIRM_READ 可达 → 进入 auto_allowed_confirm_read_tools。"""
    from react_agent.harness.sandbox import SANDBOX

    monkeypatch.setenv("REACT_AGENT_APPROVAL_MODE", "auto_allow")
    original = SANDBOX.strategy
    try:
        SANDBOX.strategy = "off"
        status = confirmation_gate_status()
        assert "read_config_snapshot" in status["auto_allowed_confirm_read_tools"]
        assert "read_config_snapshot" not in status["unenforced_confirm_tools"]
    finally:
        SANDBOX.strategy = original


def test_strict_mode_reports_confirm_read_allowlist(monkeypatch):
    monkeypatch.setenv("REACT_AGENT_APPROVAL_MODE", "auto_allow")
    monkeypatch.setenv("REACT_AGENT_STRICT_CONFIRM", "1")
    status = confirmation_gate_status()
    assert status["mode"] == "strict_deny"
    assert status["unenforced_confirm_tools"] == []
    assert "read_config_snapshot" in status["strict_allowed_confirm_read_tools"]
    assert "probe_service_health" in status["strict_allowed_confirm_read_tools"]
    assert confirmation_gate_startup_warning() is None


def test_injected_hitl_reports_hitl_mode():
    from react_agent.safety.human_in_the_loop import HumanInTheLoop
    from react_agent.safety.permission_gate import set_hitl

    set_hitl(HumanInTheLoop(ask_fn=lambda op, opts: "n"))
    status = confirmation_gate_status()
    assert status["mode"] == "hitl"
    assert status["unenforced_confirm_tools"] == []
    assert confirmation_gate_startup_warning() is None


def test_startup_warning_under_auto_allow(monkeypatch):
    monkeypatch.setenv("REACT_AGENT_APPROVAL_MODE", "auto_allow")
    warning = confirmation_gate_startup_warning()
    assert warning is not None
    assert "auto_allow" in warning or "STRICT_CONFIRM" in warning


def test_ready_payload_exposes_gate_status():
    from react_agent.server.health import readiness_payload

    status_code, payload = readiness_payload(request_id="probe")
    assert status_code in (200, 503)
    assert "confirmation_gate" in payload
    assert payload["confirmation_gate"]["mode"] in {
        "auto_allow", "strict_deny", "hitl", "async",
    }
