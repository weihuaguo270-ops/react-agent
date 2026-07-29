"""StepWatcher integration with Harness recorder."""
from __future__ import annotations

import json
import os
import sys
import tempfile

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
TD_ROOT = os.path.abspath(os.path.join(ROOT, "..", "trace-debugger"))
if os.path.isdir(TD_ROOT) and TD_ROOT not in sys.path:
    sys.path.insert(0, TD_ROOT)

pytestmark = pytest.mark.skipif(
    not os.path.isdir(TD_ROOT),
    reason="trace-debugger repo not found beside react-agent",
)


@pytest.fixture
def watcher_env(monkeypatch, tmp_path):
    monkeypatch.setenv("REACT_AGENT_STEP_WATCHER", "1")
    log_path = str(tmp_path / "failures.jsonl")
    monkeypatch.setenv("REACT_AGENT_FAILURE_LOG", log_path)
    traj_dir = str(tmp_path / "trajectories")
    os.makedirs(traj_dir, exist_ok=True)
    monkeypatch.setattr(
        "react_agent.harness.recorder.TRAJECTORY_DIR",
        traj_dir,
    )
    return {"log_path": log_path, "traj_dir": traj_dir}


def test_recorder_live_tool_error(watcher_env):
    from react_agent.harness.recorder import Trajectory

    traj = Trajectory("calc 2+2", model="mock")
    traj.add_step(
        1,
        thought="call calc",
        action_name="calculator",
        action_args='{"expression": "2++"}',
        observation='{"error": "syntax error"}',
        tokens=10,
    )
    assert traj.steps[0].get("failure_tags") == ["tool_error"]

    path = traj.save()
    assert os.path.isfile(path)
    with open(path, encoding="utf-8") as f:
        saved = json.load(f)
    assert saved["steps"][0].get("failure_tags") == ["tool_error"]

    with open(watcher_env["log_path"], encoding="utf-8") as f:
        lines = [json.loads(line) for line in f if line.strip()]
    assert any(ev.get("failure_type") == "tool_error" for ev in lines)


def test_recorder_thought_then_tool_call_upsert(watcher_env):
    from react_agent.harness.recorder import Trajectory

    traj = Trajectory("search", model="mock")
    traj.add_thought(1, "searching")
    traj.add_tool_call(1, "web_search", '{"q": "x"}', "too short")
    entry = traj.steps[0]
    assert "failure_tags" in entry
    assert entry["failure_tags"][0] in ("search_empty", "tool_error")


def test_step_watcher_disabled(monkeypatch, tmp_path):
    monkeypatch.setenv("REACT_AGENT_STEP_WATCHER", "0")
    from react_agent.harness.recorder import Trajectory

    traj = Trajectory("q", model="m")
    traj.add_step(1, observation='{"error": "x"}', action_name="t", action_args="{}")
    assert "failure_tags" not in traj.steps[0]
