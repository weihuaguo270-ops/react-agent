"""Sandbox 安全后端的策略与失败关闭回归。"""
from __future__ import annotations

import json
import os
import subprocess

import pytest

import react_agent.harness.sandbox as sandbox_module
from react_agent.harness.sandbox import (
    RISK_CONTROL,
    RISK_UNTRUSTED,
    Sandbox,
    classify_risk,
    should_sandbox_by_risk,
)


@pytest.fixture(autouse=True)
def _clean_sandbox_env(monkeypatch):
    for key in list(os.environ):
        if key.startswith("REACT_AGENT_SANDBOX_"):
            monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("REACT_AGENT_SANDBOX_PREWARM", "0")


def _call(name: str, arguments: dict) -> dict:
    return {
        "function": {
            "name": name,
            "arguments": json.dumps(arguments, ensure_ascii=False),
        }
    }


def test_unknown_tools_fail_into_sandbox():
    assert classify_risk("third_party_tool") == RISK_UNTRUSTED
    assert should_sandbox_by_risk("third_party_tool", "auto") is True


def test_control_plane_tool_stays_on_host():
    assert classify_risk("toggle_sandbox") == RISK_CONTROL
    assert should_sandbox_by_risk("toggle_sandbox", "on") is False


@pytest.mark.parametrize(
    ("strategy", "backend"),
    [("auto", "container"), ("on", "process"), ("off", "container")],
)
def test_required_mode_rejects_insecure_configuration(strategy, backend):
    with pytest.raises(ValueError, match="required"):
        Sandbox(
            strategy=strategy,
            backend=backend,
            required=True,
            prewarm=False,
        )


def test_process_backend_does_not_inherit_api_key(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "host-secret-value")
    sandbox = Sandbox(strategy="on", backend="process", prewarm=False)
    result = sandbox.run(
        _call(
            "execute_python",
            {
                "code": (
                    "import os; "
                    "print(os.getenv('DEEPSEEK_API_KEY', 'secret-not-inherited'))"
                )
            },
        )
    )
    assert "secret-not-inherited" in result
    assert "host-secret-value" not in result


def test_process_runner_uses_absolute_package_path(monkeypatch):
    monkeypatch.setenv("PYTHONPATH", "src;.")
    env = sandbox_module._runner_env("calculator", 1000, 1000)
    assert os.path.isabs(env["PYTHONPATH"])
    assert env["PYTHONPATH"].endswith("react-agent\\src")


def test_container_backend_builds_hardened_command(monkeypatch):
    calls = []

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        if command[1:3] == ["image", "inspect"]:
            return subprocess.CompletedProcess(command, 0, "[]", "")
        if command[1] == "run":
            return subprocess.CompletedProcess(
                command,
                0,
                json.dumps({"ok": True, "result": "42"}),
                "",
            )
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(sandbox_module.shutil, "which", lambda _: "docker")
    monkeypatch.setattr(sandbox_module.subprocess, "run", fake_run)
    sandbox = Sandbox(
        strategy="on",
        backend="container",
        required=True,
        prewarm=False,
    )

    result = sandbox.run(_call("calculator", {"expression": "40+2"}))
    assert result == "42"

    run_command, run_kwargs = next(
        item for item in calls if item[0][1] == "run"
    )
    joined = " ".join(run_command)
    assert "--interactive" in run_command
    assert "--read-only" in run_command
    assert run_command[run_command.index("--network") + 1] == "none"
    assert run_command[run_command.index("--cap-drop") + 1] == "ALL"
    assert "no-new-privileges" in run_command
    assert run_command[run_command.index("--user") + 1] == "65532:65532"
    assert "--memory" in run_command
    assert "--memory-swap" in run_command
    assert "--cpus" in run_command
    assert "--pids-limit" in run_command
    assert "--tmpfs" in run_command
    assert "40+2" not in joined
    assert "40+2" in run_kwargs["input"]


def test_container_backend_fails_closed_without_runtime(monkeypatch):
    monkeypatch.setattr(sandbox_module.shutil, "which", lambda _: None)
    with pytest.raises(RuntimeError, match="服务拒绝启动"):
        Sandbox(
            strategy="on",
            backend="container",
            required=True,
            prewarm=False,
        )


def test_network_is_off_without_egress_proxy(monkeypatch):
    sandbox = Sandbox(
        strategy="on",
        backend="container",
        required=False,
        prewarm=False,
    )
    assert sandbox._container_network("web_search") == "none"

    monkeypatch.setenv(
        "REACT_AGENT_SANDBOX_EGRESS_NETWORK", "sandbox-egress"
    )
    sandbox = Sandbox(
        strategy="on",
        backend="container",
        required=False,
        prewarm=False,
    )
    assert sandbox._container_network("web_search") == "sandbox-egress"
    assert sandbox._container_network("calculator") == "none"


def test_secure_mode_blocks_external_tools():
    sandbox = Sandbox(
        strategy="on",
        backend="container",
        required=False,
        prewarm=False,
    )
    block = sandbox.external_tool_block_reason("remote_mcp_tool")
    assert block is not None
    payload = json.loads(block)
    assert payload["error"] == "blocked by sandbox boundary"


def test_runner_error_preserves_detail():
    sandbox = Sandbox(strategy="on", backend="process", prewarm=False)
    result = sandbox.run(_call("missing_tool", {}))
    assert "未知工具: missing_tool" in result

def test_required_boundary_never_calls_host_function(monkeypatch):
    import react_agent.harness.tool_boundary as boundary_module

    called = False

    def host_function(**_):
        nonlocal called
        called = True
        return "host"

    class RequiredSandbox:
        required = True

        @staticmethod
        def run(tool_call):
            assert tool_call["function"]["name"] == "calculator"
            return "42"

    monkeypatch.setattr(boundary_module, "SANDBOX", RequiredSandbox())
    result = boundary_module.execute_registered_tool(
        "calculator",
        {"expression": "40+2"},
        {"calculator": host_function},
    )
    assert result == "42"
    assert called is False


def test_required_boundary_propagates_sandbox_failure(monkeypatch):
    import react_agent.harness.tool_boundary as boundary_module

    class FailedSandbox:
        required = True

        @staticmethod
        def run(_tool_call):
            return "[沙箱] 安全后端不可用，已拒绝执行"

    monkeypatch.setattr(boundary_module, "SANDBOX", FailedSandbox())
    with pytest.raises(RuntimeError, match="已拒绝执行"):
        boundary_module.execute_registered_tool(
            "calculator",
            {"expression": "1+1"},
            {"calculator": lambda **_: "host"},
        )


def test_required_mode_enables_strict_confirmation(monkeypatch):
    from react_agent.safety.permission_gate import (
        permission_block_message,
        set_hitl,
    )

    set_hitl(None)
    monkeypatch.setenv("REACT_AGENT_SANDBOX_REQUIRED", "1")
    blocked = permission_block_message(
        "execute_python",
        {"code": "print(1)"},
    )
    assert blocked is not None
    assert "strict confirm" in blocked

def test_oversized_payload_is_rejected(monkeypatch):
    monkeypatch.setenv("REACT_AGENT_SANDBOX_MAX_INPUT", "1024")
    sandbox = Sandbox(strategy="on", backend="process", prewarm=False)
    result = sandbox.run(
        _call("summarize", {"text": "x" * 2048})
    )
    assert "参数超过" in result
    assert "已拒绝执行" in result
