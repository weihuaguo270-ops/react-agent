from react_agent.eval.business_metrics import (
    business_scorecard,
    compare_scorecards,
    safe_rate,
)


def test_business_scorecard_reports_outcome_handoff_and_p95():
    report = business_scorecard(
        [
            {"passed": True, "handoff": False, "duration_ms": 10},
            {"passed": False, "handoff": True, "duration_ms": 50},
            {"passed": True, "handoff": False, "duration_ms": 20},
        ],
        human_handoff_key="handoff",
        duration_key="duration_ms",
    )
    assert report["task_success_rate"] == 0.667
    assert report["human_handoff_rate"] == 0.333
    assert report["duration_p95_ms"] == 50.0


def test_compare_scorecards_holds_on_hard_business_regression():
    report = compare_scorecards(
        {"task_success_rate": 1.0, "duration_avg_ms": 100},
        {"task_success_rate": 0.8, "duration_avg_ms": 80},
    )
    assert report["hard_metric_regressions"] == ["task_success_rate"]
    assert report["decision"] == "hold"


def test_safe_rate_handles_empty_and_bounds():
    assert safe_rate(0, 0) == 0.0
    assert safe_rate(5, 4) == 1.0
