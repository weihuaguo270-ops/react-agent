import importlib.util
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "examples" / "eval" / "harness_closed_loop.py"
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
    fixtures = Path(__file__).parents[1] / "examples" / "fixtures" / "software_tasks"
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
