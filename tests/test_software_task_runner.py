from __future__ import annotations

from pathlib import Path
import subprocess

import pytest

from react_agent.eval.software_task import SoftwareTask
from react_agent.eval.software_task_runner import SoftwareTaskRunner, SoftwareTaskRunnerConfig


def task(**overrides):
    value = {
        "task_id": "task-1",
        "repository": "repo",
        "issue_url": "issue",
        "base_commit": "abc123",
        "split": "dev",
        "test_command": ["python", "-m", "pytest", "-q"],
        "acceptance_criteria": ["tests pass"],
        "allowed_paths": ["src/", "tests/"],
    }
    value.update(overrides)
    return SoftwareTask.from_dict(value)


def test_container_command_has_isolation_and_task_command():
    runner = SoftwareTaskRunner(SoftwareTaskRunnerConfig(runtime="docker", image="test-image"))
    command = runner.container_command(task(), Path("workspace"), "container-1")
    assert "--network" in command and command[command.index("--network") + 1] == "none"
    assert "--read-only" in command
    assert "--cap-drop" in command and command[command.index("--cap-drop") + 1] == "ALL"
    assert "--user" in command and "65532:65532" in command
    assert command[-4:] == ["test-image", "python", "-m", "pytest"] or command[-5:] == ["test-image", "python", "-m", "pytest", "-q"]


def test_runner_rejects_non_test_commands():
    runner = SoftwareTaskRunner()
    with pytest.raises(ValueError, match="allowlist"):
        runner.validate_commands(task(test_command=["powershell", "Remove-Item", "-Recurse", "*"]))


def test_runner_requires_network_disabled():
    with pytest.raises(ValueError, match="network=none"):
        SoftwareTaskRunner(SoftwareTaskRunnerConfig(network="bridge"))


def test_runner_rejects_non_docker_runtime():
    with pytest.raises(ValueError, match="runtime must be docker"):
        SoftwareTaskRunner(SoftwareTaskRunnerConfig(runtime="containerd"))


def test_docker_runtime_preflight_checks_daemon_and_image(monkeypatch):
    calls = []
    runner = SoftwareTaskRunner(SoftwareTaskRunnerConfig(runtime="docker", image="test-image"))
    monkeypatch.setattr("react_agent.eval.software_task_runner.shutil.which", lambda _: "docker")

    def fake_run(command, **kwargs):
        calls.append(command)
        return subprocess.CompletedProcess(command, 0, "{}", "")

    monkeypatch.setattr("react_agent.eval.software_task_runner.subprocess.run", fake_run)
    assert runner.verify_runtime() == (True, None)
    assert calls == [["docker", "info"], ["docker", "image", "inspect", "test-image"]]


def test_docker_runtime_fails_closed_when_daemon_is_unavailable(monkeypatch):
    runner = SoftwareTaskRunner(SoftwareTaskRunnerConfig(runtime="docker", image="test-image"))
    monkeypatch.setattr("react_agent.eval.software_task_runner.shutil.which", lambda _: "docker")
    monkeypatch.setattr(
        "react_agent.eval.software_task_runner.subprocess.run",
        lambda command, **kwargs: subprocess.CompletedProcess(command, 1, "", "permission denied"),
    )
    ready, error = runner.verify_runtime()
    assert ready is False
    assert "daemon is unavailable" in error


def test_hidden_test_command_is_checked_against_allowlist():
    runner = SoftwareTaskRunner()
    with pytest.raises(ValueError, match="allowlist"):
        runner.validate_commands(task(hidden_test_command=["python", "-c", "print(1)"]))


def test_container_command_can_target_hidden_test():
    runner = SoftwareTaskRunner(SoftwareTaskRunnerConfig(runtime="docker", image="test-image"))
    command = runner.container_command(
        task(hidden_test_command=["pytest", "tests/hidden.py"]),
        Path("workspace"),
        "container-2",
        ["pytest", "tests/hidden.py"],
    )
    assert command[-3:] == ["test-image", "pytest", "tests/hidden.py"]


def test_hidden_asset_is_read_only_mounted_only_for_hidden_command(tmp_path):
    asset_root = tmp_path / "hidden"
    asset_root.mkdir()
    (asset_root / "check.py").write_text("# hidden\n", encoding="utf-8")
    runner = SoftwareTaskRunner(SoftwareTaskRunnerConfig(
        runtime="docker", image="test-image", hidden_test_root=asset_root,
    ))
    item = task(
        hidden_test_command=["pytest", "/hidden-tests/check.py"],
        hidden_test_asset="check.py",
    )
    public = runner.container_command(item, tmp_path, "public", item.test_command)
    hidden = runner.container_command(item, tmp_path, "hidden", item.hidden_test_command)
    assert "--mount" not in public
    mount = hidden[hidden.index("--mount") + 1]
    assert "type=bind" in mount and "readonly" in mount
    assert "/hidden-tests/check.py" in mount


def test_hidden_asset_rejects_escape_and_missing_root(tmp_path):
    with pytest.raises(ValueError, match="safe relative"):
        task(hidden_test_asset="../secret.py")
    item = task(hidden_test_command=["pytest", "hidden.py"], hidden_test_asset="hidden.py")
    with pytest.raises(ValueError, match="hidden_test_root"):
        SoftwareTaskRunner().validate_commands(item)
