from react_agent.apps.expense.eval_business import (
    compare_business_runs,
    load_business_cases,
    run_business_case,
    run_business_suite,
)


def test_expense_business_splits_and_reference_agent_pass():
    cases = load_business_cases()
    assert {case["split"] for case in cases} == {"dev", "golden", "held_out"}
    result = run_business_suite()
    assert len(result.cases) == 8
    assert result.pass_rate == 1.0
    assert result.to_dict()["by_split"]["held_out"]["num_cases"] == 3


def test_business_episode_contains_state_and_trace_evidence():
    case = next(case for case in load_business_cases() if case["split"] == "held_out")
    result = run_business_case(case, agent_version="candidate-v2")
    assert result.episode["schema_version"] == "evaluation-episode/v1"
    assert result.episode["agent_version"] == "candidate-v2"
    assert result.episode["state_verification"]["passed"] is True
    assert result.episode["trajectory"]["steps"][0]["action"]["name"] == "inspect_expense_claim"


def test_business_comparison_holds_state_regression():
    baseline = run_business_suite(agent_version="v1")

    def broken_agent(case, ledger):
        claim_id = case["claim"]["id"]
        return "no action", [{"step": 1, "thought": "FINAL ANSWER: no action"}]

    candidate = run_business_suite(agent_version="v2", agent_fn=broken_agent)
    comparison = compare_business_runs(baseline, candidate)
    assert comparison["decision"] == "hold"
    assert len(comparison["regressions"]) == len(baseline.cases)
