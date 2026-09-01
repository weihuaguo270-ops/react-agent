"""运行脱敏业务试点闭环并输出版本比较报告。"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from react_agent.eval.business_pilot import evaluate_pilot, load_pilot_dataset  # noqa: E402


def _no_action_agent(case, ledger):
    """生成用于 baseline 对照的确定性失败结果。"""
    return "no action", [{"step": 1, "thought": "FINAL ANSWER: no action"}]


def _load_expense_pilot() -> dict:
    """实际运行费用业务集，并转换为 pilot 数据契约。"""
    from react_agent.apps.expense.eval_business import run_business_suite

    baseline = run_business_suite(agent_version="expense-baseline-v0", agent_fn=_no_action_agent)
    candidate = run_business_suite(agent_version="expense-candidate-v1")
    baseline_by_id = {case.case_id: case for case in baseline.cases}
    tasks = []
    for candidate_case in candidate.cases:
        baseline_case = baseline_by_id[candidate_case.case_id]
        tasks.append(
            {
                "task_id": candidate_case.case_id,
                "domain": "expense_state_verification",
                "split": candidate_case.split,
                "input": candidate_case.episode["task"],
                "redaction": {"applied": True},
                "baseline": {"passed": baseline_case.passed},
                "candidate": {"passed": candidate_case.passed},
                "human_review": {
                    "decision": "accepted" if candidate_case.passed else "rejected",
                    "reviewer_id": "controlled-reviewer",
                },
                "final_status": "resolved" if candidate_case.passed else "unresolved",
                "evidence": {"source_ref": f"expense://business_cases/{candidate_case.case_id}"},
            }
        )
    return {
        "schema_version": "business-pilot/v1",
        "project": "expense-controlled-pilot",
        "evidence_level": "controlled_fixture",
        "baseline_provenance": {
            "mode": "fault_injection",
            "profile": "no_action",
            "description": "故意不调用费用工具，用于验证失败基线和发布门禁。",
            "expected_scope": "all_tasks_fail",
        },
        "candidate_provenance": {
            "mode": "deterministic_reference_agent",
            "description": "调用费用状态工具并按固定政策完成决策。",
        },
        "baseline_version": baseline.agent_version,
        "candidate_version": candidate.agent_version,
        "tasks": tasks,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="评估脱敏业务任务的 baseline/candidate 闭环")
    parser.add_argument(
        "--dataset",
        type=Path,
        default=ROOT / "examples" / "fixtures" / "business_pilot_sample.json",
    )
    parser.add_argument(
        "--source",
        choices=("dataset", "expense"),
        default="dataset",
        help="读取脱敏 JSON，或实际运行 expense 业务集生成 controlled pilot 数据。",
    )
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()

    dataset = _load_expense_pilot() if args.source == "expense" else load_pilot_dataset(args.dataset)
    report = evaluate_pilot(dataset)
    report["evidence_level"] = dataset.get("evidence_level", "redacted_dataset")
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    print(rendered)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(rendered + "\n", encoding="utf-8")
    return 0 if report["decision"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
