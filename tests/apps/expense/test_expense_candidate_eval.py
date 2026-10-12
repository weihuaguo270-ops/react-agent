from __future__ import annotations

import json
from pathlib import Path

import pytest

from react_agent.apps.expense.candidate_eval import (
    CandidateFixtureError,
    expand_candidate_case,
    load_candidate_fixture,
    run_candidate_suite,
)


def test_candidate_loader_expands_case_id_and_explicit_null_override():
    data = load_candidate_fixture()
    case = next(item for item in data["cases"] if item["id"] == "D-MEAL-005")
    claim = expand_candidate_case(data, case)
    assert claim["claim_id"] == "D-MEAL-005"
    assert claim["expense_type"] is None


def test_candidate_runner_executes_dev_and_preserves_known_gap_status():
    result = run_candidate_suite(split="dev", agent_version="test-candidate")
    assert len(result.cases) == 41
    assert result.held_out_manifest_sha256 == "f8801e86298c59260b8d510df9c965f953bcbc5430672fefdbb50b523457da36"
    assert result.counts["known_gap"] >= 1
    assert result.cases[0].episode["schema_version"] == "evaluation-episode/v1"


def test_held_out_requires_explicit_opt_in():
    with pytest.raises(CandidateFixtureError, match="allow_held_out"):
        run_candidate_suite(split="held_out")


def test_runner_rejects_duplicate_ids():
    source = Path(__file__).resolve().parents[3] / "fixtures" / "expense" / "business_cases_expanded_v1.json"
    data = json.loads(source.read_text(encoding="utf-8"))
    data["cases"].append(dict(data["cases"][0]))

    class InMemoryFixture:
        def read_text(self, encoding):
            return json.dumps(data)

    with pytest.raises(CandidateFixtureError, match="duplicate case id"):
        load_candidate_fixture(InMemoryFixture())
