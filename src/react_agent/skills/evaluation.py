"""Offline evaluation for business Skill routing and contract stability."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from react_agent.skills.registry import SkillRoutingError, route_skill_decision, run_skill


@dataclass(frozen=True)
class RouteCase:
    query: str
    expected: str
    payload: dict[str, Any] | None = None


@dataclass(frozen=True)
class ContractCase:
    skill: str
    payload: dict[str, Any]
    expected_ok: bool = True


DEFAULT_ROUTE_CASES = (
    RouteCase("API 401 如何排障", "docs_troubleshoot"),
    RouteCase("请检查这个报销单", "expense_claim_review", {"claim": {"category": "餐饮", "amount": 80, "has_receipt": True}}),
    RouteCase("", "github_delivery", {"repository": "repo", "replacements": [{}], "test_command": ["python", "-m", "pytest"], "acceptance_criteria": ["tests"]}),
    RouteCase("写一首诗", "", None),
)


DEFAULT_CONTRACT_CASES = (
    ContractCase(
        "expense_claim_review",
        {"claim": {"category": "交通", "amount": 80, "has_receipt": False}},
    ),
    ContractCase("docs_troubleshoot", {"query": "股价明天多少"}),
    ContractCase("expense_claim_review", {"claim": {"category": "交通", "amount": "bad", "has_receipt": True}}, False),
)


def evaluate_routing(cases: tuple[RouteCase, ...] = DEFAULT_ROUTE_CASES) -> dict[str, Any]:
    rows = []
    for case in cases:
        try:
            decision = route_skill_decision(case.query, case.payload)
            actual = decision.skill
            passed = actual == case.expected
            row = {"query": case.query, "expected": case.expected, "actual": actual, "passed": passed, "route": decision.to_dict()}
        except SkillRoutingError as exc:
            passed = case.expected == ""
            row = {"query": case.query, "expected": case.expected, "actual": "", "passed": passed, "error": str(exc)}
        rows.append(row)
    return {
        "sample_size": len(rows),
        "passed": sum(bool(row["passed"]) for row in rows),
        "accuracy": sum(bool(row["passed"]) for row in rows) / len(rows) if rows else 0.0,
        "cases": rows,
    }


def evaluate_contracts(cases: tuple[ContractCase, ...] = DEFAULT_CONTRACT_CASES) -> dict[str, Any]:
    rows = []
    for case in cases:
        result = run_skill(case.skill, case.payload)
        passed = result.ok == case.expected_ok
        rows.append({"skill": case.skill, "expected_ok": case.expected_ok, "actual_ok": result.ok, "passed": passed, "checks": result.checks, "error": result.error})
    return {
        "sample_size": len(rows),
        "passed": sum(bool(row["passed"]) for row in rows),
        "pass_rate": sum(bool(row["passed"]) for row in rows) / len(rows) if rows else 0.0,
        "cases": rows,
    }


def evaluate_stability(cases: tuple[RouteCase, ...] = DEFAULT_ROUTE_CASES, repeats: int = 5) -> dict[str, Any]:
    rows = []
    for case in cases:
        observed = []
        for _ in range(max(1, repeats)):
            try:
                observed.append(route_skill_decision(case.query, case.payload).skill)
            except SkillRoutingError:
                observed.append("")
        rows.append({"query": case.query, "observed": observed, "stable": len(set(observed)) == 1})
    return {
        "repeats": max(1, repeats),
        "sample_size": len(rows),
        "stable_rate": sum(bool(row["stable"]) for row in rows) / len(rows) if rows else 0.0,
        "cases": rows,
    }


def run_skill_evaluation() -> dict[str, Any]:
    routing = evaluate_routing()
    contracts = evaluate_contracts()
    stability = evaluate_stability()
    return {
        "schema": "business-skill-evaluation/v1",
        "routing": routing,
        "contracts": contracts,
        "stability": stability,
        "passed": (
            routing["accuracy"] == 1.0
            and contracts["pass_rate"] == 1.0
            and stability["stable_rate"] == 1.0
        ),
    }
