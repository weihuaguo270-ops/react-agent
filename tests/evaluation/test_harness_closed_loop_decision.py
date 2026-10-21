import importlib.util
import json
from pathlib import Path


SCRIPT = Path(__file__).parents[2] / "scripts" / "eval" / "acceptance" / "harness_closed_loop.py"
SPEC = importlib.util.spec_from_file_location("harness_closed_loop", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


def test_release_decision_mapping():
    assert MODULE.release_decision({"failures": []}, {"pass_rate": 1.0}) == "pass"
    assert MODULE.release_decision({"failures": []}, {"pass_rate": 0.5}) == "review"
    assert MODULE.release_decision({"failures": [{"type": "tool_error"}]}, {"pass_rate": 1.0}) == "hold"


def test_failure_takes_precedence_over_review():
    assert MODULE.release_decision({"failures": [{"type": "x"}]}, {"pass_rate": 0.0}) == "hold"


def test_trace_debugger_failure_contracts():
    fixtures = Path(__file__).parents[2] / "fixtures" / "software_tasks"
    expected = {
        "tests_still_fail.json": "tool_error",
        "tool_timeout.json": "search_timeout",
        "approval_denied.json": "approval_denied",
    }
    for name, failure_type in expected.items():
        trajectory = __import__("json").loads((fixtures / name).read_text(encoding="utf-8"))
        result = MODULE._analyze_tdebug(trajectory)
        assert result is not None
        assert [item["type"] for item in result["failures"]] == [failure_type]


def test_run_emits_shared_recorded_evidence(monkeypatch, tmp_path):
    trajectory = {
        "session_id": "closed-loop-test",
        "query": "q",
        "model": "mock",
        "steps": [{
            "step": 1,
            "action": {"name": "calculator", "arguments": "{}"},
            "observation": "2",
        }],
        "final_answer": "2",
    }
    monkeypatch.setattr(MODULE, "_analyze_tdebug", lambda _traj: None)
    monkeypatch.setattr(MODULE, "_score_eval", lambda _traj: {"pass_rate": 1.0})
    out_path = tmp_path / "closed-loop.json"
    assert MODULE.run(trajectory, str(out_path)) == 0
    report = json.loads(out_path.read_text(encoding="utf-8"))
    assert report["fixture_manifest"]["environment"]["dataset_status"] == "recorded_evidence"
    assert report["batch_id"].startswith("closed-loop-")
    episode = report["evaluation_episodes"][0]
    assert episode["environment"]["evidence_only"] is True
    assert episode["artifacts"][0]["sha256"]

