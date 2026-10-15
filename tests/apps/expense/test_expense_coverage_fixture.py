"""Structural checks for the post-S1 Expense coverage design fixture."""

from __future__ import annotations

import json
import hashlib
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
FIXTURE = ROOT / "fixtures" / "expense" / "business_cases_expanded_v1.json"


def test_expanded_coverage_fixture_is_unique_and_split_complete():
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    cases = data["cases"]
    assert data["schema_version"] == "expense-business-cases/v2"
    assert data["execution_status"] == "candidate_rules_executable_workflow_scenarios_pending"
    assert len({case["id"] for case in cases}) == len(cases)
    assert {case["split"] for case in cases} == {"dev", "golden", "held_out"}
    assert Counter(case["split"] for case in cases) == {
        "dev": 41,
        "golden": 12,
        "held_out": 16,
    }
    assert {case["template"] for case in cases if case["split"] == "held_out"} == {
        "meal",
        "transport",
        "lodging",
        "office_purchase",
    }
    assert all(case["template"] in data["templates"] for case in cases)
    assert len({scenario["id"] for scenario in data["workflow_scenarios"]}) == len(
        data["workflow_scenarios"]
    )
    held_out_payload = json.dumps(
        {
            "policy_version": data["policy_version"],
            "cases": [case for case in cases if case["split"] == "held_out"],
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    assert hashlib.sha256(held_out_payload).hexdigest() == (
        "f8801e86298c59260b8d510df9c965f953bcbc5430672fefdbb50b523457da36"
    )


def test_expanded_coverage_fixture_preserves_policy_and_expected_shape():
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert data["policy_version"] == "expense-policy-sim-v1"
    assert data["profile_id"] == "project_simulation_v1"
    for case in data["cases"]:
        assert {"id", "split", "rule_id", "template", "overrides", "expected"} <= set(case)
        expected = case["expected"]
        assert "valid" in expected
        if expected["valid"]:
            assert "review_required" in expected or "policy_decision" in expected
        else:
            assert expected["error_code"] in {"invalid_claim", "policy_profile_unavailable"}
