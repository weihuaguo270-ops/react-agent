"""Executable runner for the expanded Expense policy candidate fixture.

The S1 evaluator remains unchanged.  This runner executes the v2 candidate
fixture through the shared validator and legacy deterministic decision model,
while keeping known implementation gaps visible instead of counting them as
passes.
"""
from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

from .workflow import SimulationEvidenceAdapter, run_expense_workflow

_REPO = Path(__file__).resolve().parents[4]
EXPANDED_FIXTURE = _REPO / "fixtures" / "expense" / "business_cases_expanded_v1.json"
ALLOWED_SPLITS = {"dev", "golden", "held_out"}
EXPECTED_HELD_OUT_MANIFEST_SHA256 = "f8801e86298c59260b8d510df9c965f953bcbc5430672fefdbb50b523457da36"
RESOLVED_GAP_RULES = {
    "purchase.verified_registry_match",
    "purchase.unverified_registry",
    "transport.category_limit_over",
    "lodging.standard_market_exact",
    "lodging.preapproved_over_limit_within_market",
}


class CandidateFixtureError(ValueError):
    """Raised when the candidate fixture cannot be executed safely."""


@dataclass
class CandidateCaseResult:
    case_id: str
    split: str
    rule_id: str
    status: str
    passed: bool
    known_gap: str | None
    resolved_gap: str | None
    expected: dict[str, Any]
    actual: dict[str, Any]
    checks: list[dict[str, Any]]
    episode: dict[str, Any]


@dataclass
class CandidateSuiteResult:
    suite_id: str
    policy_version: str
    fixture_sha256: str
    held_out_manifest_sha256: str
    agent_version: str
    cases: list[CandidateCaseResult] = field(default_factory=list)

    @property
    def pass_rate(self) -> float:
        return sum(case.passed for case in self.cases) / len(self.cases) if self.cases else 0.0

    @property
    def counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for case in self.cases:
            counts[case.status] = counts.get(case.status, 0) + 1
        return counts

    def to_dict(self) -> dict[str, Any]:
        by_split: dict[str, dict[str, Any]] = {}
        for split in sorted({case.split for case in self.cases}):
            group = [case for case in self.cases if case.split == split]
            by_split[split] = {
                "num_cases": len(group),
                "pass_rate": sum(case.passed for case in group) / len(group),
                "counts": _counts(group),
            }
        return {
            "schema_version": "expense-candidate-report/v1",
            "suite_id": self.suite_id,
            "policy_version": self.policy_version,
            "fixture_sha256": self.fixture_sha256,
            "held_out_manifest_sha256": self.held_out_manifest_sha256,
            "agent_version": self.agent_version,
            "num_cases": len(self.cases),
            "pass_rate": self.pass_rate,
            "counts": self.counts,
            "by_split": by_split,
            "cases": [
                {
                    "case_id": case.case_id,
                    "split": case.split,
                    "rule_id": case.rule_id,
                    "status": case.status,
                    "passed": case.passed,
                    "known_gap": case.known_gap,
                    "resolved_gap": case.resolved_gap,
                    "expected": case.expected,
                    "actual": case.actual,
                    "checks": case.checks,
                }
                for case in self.cases
            ],
        }


def _counts(cases: list[CandidateCaseResult]) -> dict[str, int]:
    result: dict[str, int] = {}
    for case in cases:
        result[case.status] = result.get(case.status, 0) + 1
    return result


def _fixture_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _held_out_hash(data: Mapping[str, Any]) -> str:
    payload = {
        "policy_version": data["policy_version"],
        "cases": [case for case in data["cases"] if case["split"] == "held_out"],
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def load_candidate_fixture(path: Path = EXPANDED_FIXTURE) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CandidateFixtureError(f"candidate fixture unavailable: {path}") from exc
    if not isinstance(data, dict) or data.get("schema_version") != "expense-business-cases/v2":
        raise CandidateFixtureError("unsupported candidate fixture schema")
    if not isinstance(data.get("templates"), dict) or not data["templates"]:
        raise CandidateFixtureError("templates are required")
    cases = data.get("cases")
    if not isinstance(cases, list) or not cases:
        raise CandidateFixtureError("cases are required")
    if _held_out_hash(data) != EXPECTED_HELD_OUT_MANIFEST_SHA256:
        raise CandidateFixtureError("held_out manifest changed; update its reviewed hash explicitly")
    ids: set[str] = set()
    for case in cases:
        if not isinstance(case, dict) or not isinstance(case.get("id"), str):
            raise CandidateFixtureError("each case needs an id")
        if case["id"] in ids:
            raise CandidateFixtureError(f"duplicate case id: {case['id']}")
        ids.add(case["id"])
        if case.get("split") not in ALLOWED_SPLITS:
            raise CandidateFixtureError(f"unsupported split: {case.get('split')}")
        if case.get("template") not in data["templates"]:
            raise CandidateFixtureError(f"unknown template: {case.get('template')}")
        if not isinstance(case.get("overrides", {}), dict) or not isinstance(case.get("expected"), dict):
            raise CandidateFixtureError(f"invalid case shape: {case['id']}")
    return data


def _overlay(template: Any, overrides: Any) -> Any:
    if isinstance(template, Mapping) and isinstance(overrides, Mapping):
        result = {key: copy.deepcopy(value) for key, value in template.items()}
        for key, value in overrides.items():
            result[key] = _overlay(result[key], value) if key in result else copy.deepcopy(value)
        return result
    return copy.deepcopy(overrides)


def expand_candidate_case(data: Mapping[str, Any], case: Mapping[str, Any]) -> dict[str, Any]:
    claim = _overlay(data["templates"][case["template"]], case.get("overrides", {}))
    claim = _replace_case_id(claim, str(case["id"]))
    if not isinstance(claim, dict):
        raise CandidateFixtureError(f"expanded claim is not an object: {case['id']}")
    return claim


def _replace_case_id(value: Any, case_id: str) -> Any:
    if isinstance(value, str):
        return value.replace("$case_id", case_id)
    if isinstance(value, list):
        return [_replace_case_id(item, case_id) for item in value]
    if isinstance(value, dict):
        return {key: _replace_case_id(item, case_id) for key, item in value.items()}
    return value


def _check_expected(expected: Mapping[str, Any], actual: Mapping[str, Any]) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    for key, expected_value in expected.items():
        actual_value = actual.get(key)
        checks.append({"path": f"$.{key}", "expected": expected_value, "actual": actual_value, "passed": actual_value == expected_value})
    return checks


def _execute_claim(claim: dict[str, Any], *, case_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
    """Execute candidate claims through the same registered S3 decision path."""
    workflow_claim = copy.deepcopy(claim)
    purchase_orders: dict[str, bool] = {}
    market_prices: dict[str, float] = {}
    purchase_order_id = workflow_claim.get("purchase_order_id")
    if purchase_order_id and "purchase_order_verified" in workflow_claim:
        purchase_orders[str(purchase_order_id)] = bool(workflow_claim.pop("purchase_order_verified"))
    if "market_price" in workflow_claim:
        price = workflow_claim.pop("market_price")
        if price is not None:
            market_prices[str(workflow_claim.get("claim_id") or case_id)] = float(price)
    if "market_price_per_night" in workflow_claim:
        price = workflow_claim.pop("market_price_per_night")
        if price is not None:
            market_prices[str(workflow_claim.get("claim_id") or case_id)] = float(price)
    adapter = SimulationEvidenceAdapter(
        purchase_orders=purchase_orders,
        market_prices=market_prices,
        version="expense-candidate-fixture-v1",
    )
    result = run_expense_workflow({
        "claim": workflow_claim,
        "policy_profile": workflow_claim.get("policy_profile"),
        "evidence_adapter": adapter,
        "idempotency_key": f"expense-candidate:{case_id}",
    })
    state = result.state
    actual: dict[str, Any] = {"valid": bool(state.get("claim_valid"))}
    if actual["valid"]:
        decision = state.get("decision") or {}
        actual["review_required"] = bool(decision.get("review_required"))
        code = state.get("decision_code")
        if code:
            actual["decision"] = code
            if code.startswith("reject"):
                actual["policy_decision"] = code
        if state.get("error_code"):
            actual["error_code"] = state["error_code"]
    else:
        actual["error_code"] = state.get("error_code") or "invalid_claim"
    return actual, {"workflow": result.workflow, "run_id": result.run_id, "external_adapter": state.get("external_adapter")}


def run_candidate_case(case: Mapping[str, Any], data: Mapping[str, Any], *, agent_version: str) -> CandidateCaseResult:
    claim = expand_candidate_case(data, case)
    expected = dict(case["expected"])
    actual, execution = _execute_claim(claim, case_id=str(case["id"]))
    checks = _check_expected(expected, actual)
    matched = all(check["passed"] for check in checks)
    declared_gap = case.get("known_gap")
    resolved_gap = declared_gap if declared_gap and case["rule_id"] in RESOLVED_GAP_RULES and matched else None
    known_gap = declared_gap if declared_gap and resolved_gap is None else None
    if known_gap:
        status = "known_gap"
        passed = False
    elif matched:
        status = "passed"
        passed = True
    else:
        status = "failed"
        passed = False
    episode = {
        "schema_version": "evaluation-episode/v1",
        "episode_id": str(case["id"]),
        "task": str(case.get("rule_id", case["id"])),
        "framework": "react-agent-expense-candidate",
        "agent_version": agent_version,
        "split": str(case["split"]),
        "acceptance_criteria": [f"expected.{key}={value!r}" for key, value in expected.items()],
        "expected_state": expected,
        "final_state": actual,
        "state_verification": {"passed": passed, "status": status, "checks": checks},
        "trajectory": {"steps": [{"step": 1, "action": "run_expense_claim_review", "claim": claim, **execution}], "final_answer": status},
        "metadata": {"domain": "expense", "verifier": "candidate_contract_subset", "workflow": execution["workflow"], "external_adapter": execution["external_adapter"], "known_gap": known_gap, "resolved_gap": resolved_gap},
    }
    return CandidateCaseResult(str(case["id"]), str(case["split"]), str(case["rule_id"]), status, passed, known_gap, resolved_gap, expected, actual, checks, episode)


def run_candidate_suite(*, split: str | None = None, agent_version: str = "expense-candidate-v1", path: Path = EXPANDED_FIXTURE, allow_held_out: bool = False) -> CandidateSuiteResult:
    data = load_candidate_fixture(path)
    if split is not None and split not in ALLOWED_SPLITS:
        raise CandidateFixtureError(f"unsupported split: {split}")
    if split == "held_out" and not allow_held_out:
        raise CandidateFixtureError("held_out execution requires allow_held_out=True")
    cases = [case for case in data["cases"] if split is None or case["split"] == split]
    if any(case["split"] == "held_out" for case in cases) and not allow_held_out:
        raise CandidateFixtureError("held_out execution requires allow_held_out=True")
    return CandidateSuiteResult(
        suite_id=str(data["suite_id"]), policy_version=str(data["policy_version"]),
        fixture_sha256=_fixture_hash(path), held_out_manifest_sha256=_held_out_hash(data),
        agent_version=agent_version,
        cases=[run_candidate_case(case, data, agent_version=agent_version) for case in cases],
    )


__all__ = ["CandidateFixtureError", "CandidateSuiteResult", "expand_candidate_case", "load_candidate_fixture", "run_candidate_case", "run_candidate_suite"]
