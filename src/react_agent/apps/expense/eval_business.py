"""Deterministic business-state evaluation for the expense Agent example."""

from __future__ import annotations

import copy
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from .offline_answer import _load_limits
from .operations import ExpenseLedger


DATASET_PATH = Path(__file__).with_name("business_cases.json")


@dataclass
class BusinessCaseResult:
    """一个费用用例的状态断言和 EvaluationEpisode 证据。"""

    case_id: str
    split: str
    passed: bool
    checks: list[dict[str, Any]]
    episode: dict[str, Any]


@dataclass
class BusinessSuiteResult:
    """同一 Agent 版本在固定费用任务集上的聚合结果。"""

    agent_version: str
    cases: list[BusinessCaseResult] = field(default_factory=list)

    @property
    def pass_rate(self) -> float:
        """返回执行用例的等权通过率；空集合返回零。"""
        if not self.cases:
            return 0.0
        return sum(case.passed for case in self.cases) / len(self.cases)

    def to_dict(self) -> dict[str, Any]:
        """生成可持久化并用于版本门禁的报告结构。"""
        by_split = {}
        for split in sorted({case.split for case in self.cases}):
            group = [case for case in self.cases if case.split == split]
            by_split[split] = {
                "num_cases": len(group),
                "pass_rate": sum(case.passed for case in group) / len(group),
            }
        return {
            "agent_version": self.agent_version,
            "num_cases": len(self.cases),
            "pass_rate": self.pass_rate,
            "by_split": by_split,
            "cases": [
                {
                    "case_id": case.case_id,
                    "split": case.split,
                    "passed": case.passed,
                    "checks": case.checks,
                }
                for case in self.cases
            ],
        }


def load_business_cases(path: Path = DATASET_PATH) -> list[dict[str, Any]]:
    """加载费用业务清单；调用方负责进一步校验用例字段。"""
    data = json.loads(path.read_text(encoding="utf-8"))
    return list(data.get("cases") or [])


def run_business_case(
    case: dict[str, Any],
    *,
    agent_version: str = "expense-agent-v1",
    agent_fn: Callable[[dict[str, Any], ExpenseLedger], tuple[str, list[dict[str, Any]]]]
    | None = None,
) -> BusinessCaseResult:
    """在独立 ledger 上执行用例并校验期望业务状态子集。"""
    claim = copy.deepcopy(case["claim"])
    claim_id = str(claim["id"])
    ledger = ExpenseLedger.from_claims([claim])
    final_answer, steps = (agent_fn or _reference_agent)(case, ledger)
    final_state = ledger.snapshot(claim_id)
    checks = _verify_expected_subset(case["expected_state"], final_state)
    passed = bool(checks) and all(check["passed"] for check in checks)
    episode = {
        "schema_version": "evaluation-episode/v1",
        "episode_id": str(case["id"]),
        "task": str(case["task"]),
        "framework": "react-agent-expense",
        "agent_version": agent_version,
        "split": str(case["split"]),
        "acceptance_criteria": list(case.get("acceptance_criteria") or []),
        "expected_state": copy.deepcopy(case["expected_state"]),
        "final_state": final_state,
        "state_verification": {"passed": passed, "checks": checks},
        "trajectory": {
            "session_id": f"expense-{case['id']}-{agent_version}",
            "task_episode_id": str(case["id"]),
            "acceptance_criteria": list(case.get("acceptance_criteria") or []),
            "query": str(case["task"]),
            "model": agent_version,
            "steps": steps,
            "final_answer": final_answer,
        },
        "metadata": {"domain": "expense", "verifier": "business_state_subset"},
    }
    return BusinessCaseResult(
        case_id=str(case["id"]),
        split=str(case["split"]),
        passed=passed,
        checks=checks,
        episode=episode,
    )


def run_business_suite(
    *,
    split: str | None = None,
    agent_version: str = "expense-agent-v1",
    agent_fn: Callable[[dict[str, Any], ExpenseLedger], tuple[str, list[dict[str, Any]]]]
    | None = None,
) -> BusinessSuiteResult:
    """运行指定数据切片并保留 Agent 版本证据。"""
    cases = load_business_cases()
    if split:
        cases = [case for case in cases if case["split"] == split]
    return BusinessSuiteResult(
        agent_version=agent_version,
        cases=[
            run_business_case(
                case,
                agent_version=agent_version,
                agent_fn=agent_fn,
            )
            for case in cases
        ],
    )


def compare_business_runs(
    baseline: BusinessSuiteResult,
    candidate: BusinessSuiteResult,
) -> dict[str, Any]:
    """比较候选版和基线，任何逐用例回归都会阻止发布。"""
    baseline_cases = {case.case_id: case for case in baseline.cases}
    candidate_cases = {case.case_id: case for case in candidate.cases}
    comparable = sorted(set(baseline_cases) & set(candidate_cases))
    regressions = [
        case_id
        for case_id in comparable
        if baseline_cases[case_id].passed and not candidate_cases[case_id].passed
    ]
    improvements = [
        case_id
        for case_id in comparable
        if not baseline_cases[case_id].passed and candidate_cases[case_id].passed
    ]
    return {
        "baseline_version": baseline.agent_version,
        "candidate_version": candidate.agent_version,
        "comparable_cases": len(comparable),
        "pass_rate_delta": candidate.pass_rate - baseline.pass_rate,
        "regressions": regressions,
        "improvements": improvements,
        "decision": "hold" if regressions else "pass",
    }


def _reference_agent(
    case: dict[str, Any], ledger: ExpenseLedger
) -> tuple[str, list[dict[str, Any]]]:
    claim_id = str(case["claim"]["id"])
    claim = ledger.inspect_claim(claim_id)
    result = ledger.decide_claim(
        claim_id,
        limits=_load_limits(),
        idempotency_key=f"{case['id']}:decision",
    )
    steps = [
        {
            "step": 1,
            "thought": "Inspect the claim before applying policy.",
            "action": {
                "name": "inspect_expense_claim",
                "arguments": json.dumps({"claim_id": claim_id}),
            },
            "observation": json.dumps(claim, ensure_ascii=False, sort_keys=True),
        },
        {
            "step": 2,
            "thought": "Apply the policy once with an idempotency key.",
            "action": {
                "name": "decide_expense_claim",
                "arguments": json.dumps(
                    {
                        "claim_id": claim_id,
                        "idempotency_key": f"{case['id']}:decision",
                    }
                ),
            },
            "observation": json.dumps(result, ensure_ascii=False, sort_keys=True),
        },
    ]
    return f"{result['claim_id']}: {result['decision']}", steps


def _verify_expected_subset(expected: Any, actual: Any, path: str = "$") -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    if isinstance(expected, dict):
        actual_mapping = actual if isinstance(actual, dict) else {}
        for key, value in expected.items():
            checks.extend(
                _verify_expected_subset(value, actual_mapping.get(key), f"{path}.{key}")
            )
        return checks
    return [
        {
            "path": path,
            "expected": expected,
            "actual": actual,
            "passed": actual == expected,
        }
    ]
