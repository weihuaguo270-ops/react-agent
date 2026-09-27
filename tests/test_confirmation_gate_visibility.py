"""CONFIRM 闸门可见性回归测试。

背景：``safety/human_in_the_loop.py`` 有完整的 HITL 实现，但生产入口从未注入
（``permission_gate.set_hitl`` 只在测试里调用）。因此非严格模式下 ``CONFIRM``
级工具会**自动放行**——看起来有闸门，实际无人把关。

本模块锁定「该状态必须被显式暴露」：启动告警 + ``/ready`` 的
``confirmation_gate`` 字段，并区分**实际可达**与**被沙箱拦下**（避免误报）。
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


def test_async_mode_is_reported_as_enforced(monkeypatch):
    """异步审批模式下 CONFIRM 已有人把关，不应再报 auto_allow。"""
    monkeypatch.setenv("REACT_AGENT_APPROVAL_MODE", "async")
    status = confirmation_gate_status()
    assert status["mode"] == "async"
    assert status["unenforced_confirm_tools"] == []
    assert confirmation_gate_startup_warning() is None


def test_default_mode_is_auto_allow_and_reported():
    status = confirmation_gate_status()
    assert status["mode"] == "auto_allow"
    assert status["unenforced_confirm_tools"], "默认应报告自动放行的 CONFIRM 工具"
    assert status["warning"]


def test_default_mode_lists_reachable_confirm_tools():
    """默认沙箱（auto/process）下真正在宿主执行的是 execute_python 与 clear_trajectories。"""
    status = confirmation_gate_status()
    assert "execute_python" in status["unenforced_confirm_tools"]
    assert "clear_trajectories" in status["unenforced_confirm_tools"]


def test_app_tools_are_reported_as_unreachable_under_default_sandbox():
    """app 层工具不在沙箱子进程注册表里 → 默认配置下不可达，不应算作"已放行"。"""
    status = confirmation_gate_status()
    unreachable = status.get("unreachable_confirm_tools") or []
    assert "read_config_snapshot" in unreachable
    assert "read_config_snapshot" not in status["unenforced_confirm_tools"]


def test_sandbox_off_makes_unreachable_tools_reachable(monkeypatch):
    """沙箱关闭后，app 工具确实会在宿主执行 → 必须纳入自动放行清单。"""
    from react_agent.harness.sandbox import SANDBOX

    original = SANDBOX.strategy
    try:
        SANDBOX.strategy = "off"
        status = confirmation_gate_status()
        assert "read_config_snapshot" in status["unenforced_confirm_tools"]
        assert status.get("unreachable_confirm_tools") == []
    finally:
        SANDBOX.strategy = original


def test_strict_mode_reports_no_unenforced_and_no_warning(monkeypatch):
    monkeypatch.setenv("REACT_AGENT_STRICT_CONFIRM", "1")
    status = confirmation_gate_status()
    assert status["mode"] == "strict_deny"
    assert status["unenforced_confirm_tools"] == []
    assert confirmation_gate_startup_warning() is None


def test_injected_hitl_reports_hitl_mode():
    from react_agent.safety.human_in_the_loop import HumanInTheLoop
    from react_agent.safety.permission_gate import set_hitl

    set_hitl(HumanInTheLoop(ask_fn=lambda op, opts: "n"))
    status = confirmation_gate_status()
    assert status["mode"] == "hitl"
    assert status["unenforced_confirm_tools"] == []
    assert confirmation_gate_startup_warning() is None


def test_startup_warning_includes_actionable_switch():
    warning = confirmation_gate_startup_warning()
    assert warning is not None
    assert "REACT_AGENT_STRICT_CONFIRM=1" in warning


def test_ready_payload_exposes_gate_status():
    from react_agent.server.health import readiness_payload

    status_code, payload = readiness_payload(request_id="probe")
    assert status_code in (200, 503)
    assert "confirmation_gate" in payload
    assert payload["confirmation_gate"]["mode"] in {
        "auto_allow", "strict_deny", "hitl", "async",
    }
