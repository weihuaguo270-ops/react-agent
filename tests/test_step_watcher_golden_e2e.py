"""StepWatcher golden E2E — fixtures/step_watcher_scenarios.json + trace-debugger golden."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
TDEBUG = ROOT / "trace-debugger"
if not TDEBUG.is_dir():
    TDEBUG = ROOT.parent / "trace-debugger"
if TDEBUG.is_dir():
    sys.path.insert(0, str(TDEBUG))

SCENARIOS = ROOT / "fixtures" / "step_watcher_scenarios.json"


@pytest.fixture
def watcher_env(tmp_path, monkeypatch):
    monkeypatch.setenv("REACT_AGENT_STEP_WATCHER", "1")
    log_path = tmp_path / "failures.jsonl"
    monkeypatch.setenv("REACT_AGENT_FAILURE_LOG", str(log_path))
    traj_dir = tmp_path / "trajectories"
    traj_dir.mkdir()
    monkeypatch.setattr("react_agent.harness.recorder.TRAJECTORY_DIR", str(traj_dir))
    return {"log_path": log_path, "traj_dir": traj_dir}


def _load_scenarios():
    return json.loads(SCENARIOS.read_text(encoding="utf-8"))["scenarios"]


@pytest.mark.parametrize("scenario", _load_scenarios(), ids=lambda s: s["id"])
def test_step_watcher_scenario(scenario, watcher_env):
    pytest.importorskip("trace_debugger")
    from react_agent.harness.recorder import Trajectory

    traj = Trajectory(scenario["query"], model=scenario.get("model", "mock-gpt"))
    for step in scenario.get("steps") or []:
        if step.get("action_name"):
            traj.add_tool_call(
                step["step"],
                step["action_name"],
                step.get("action_args", ""),
                step.get("observation", ""),
                duration=step.get("duration", 0),
            )
        elif step.get("thought") and not step.get("action_name"):
            traj.add_thought(step["step"], step["thought"])
    traj.set_final_answer(scenario.get("final_answer", ""))
    path = traj.save()

    saved = json.loads(Path(path).read_text(encoding="utf-8"))
    detected = sorted({
        t for s in saved.get("steps") or [] for t in (s.get("failure_tags") or [])
    })
    expected = sorted(scenario.get("expected_failures") or [])
    assert detected == expected, f"{scenario['id']}: expected {expected}, got {detected}"

    log_path = watcher_env["log_path"]
    if expected:
        assert log_path.is_file(), "expected JSONL failure log"
        events = [json.loads(l) for l in log_path.read_text(encoding="utf-8").splitlines() if l.strip()]
        assert events, "JSONL should not be empty when failures expected"
    else:
        if log_path.is_file():
            events = [json.loads(l) for l in log_path.read_text(encoding="utf-8").splitlines() if l.strip()]
            assert not events or all(e.get("event_type") != "step_failure" for e in events)


@pytest.mark.skipif(not TDEBUG.is_dir(), reason="trace-debugger sibling missing")
def test_trace_debugger_golden_suite_passes():
    from trace_debugger.golden import run_golden_suite

    report = run_golden_suite()
    assert report["n_failed"] == 0, report
    assert report["n_cases"] >= 27
