"""脱敏业务试点的 baseline、复核和最终状态闭环。"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from react_agent.eval.business_metrics import business_scorecard, compare_scorecards


SCHEMA_VERSION = "business-pilot/v1"
_SENSITIVE_KEY = re.compile(
    r"(?:api[_-]?key|access[_-]?token|auth(?:orization)?|password|secret|cookie|^token$)",
    re.IGNORECASE,
)
_SENSITIVE_TEXT = re.compile(
    r"(?i)\b(api[_-]?key|access[_-]?token|token|password|secret)\s*[:=]\s*[^\s,;]+"
)
_EMAIL = re.compile(r"\b([A-Za-z0-9._%+-]+)@([A-Za-z0-9.-]+\.[A-Za-z]{2,})\b")
_VALID_SPLITS = {"dev", "golden", "held_out"}


def redact_payload(value: Any) -> Any:
    """递归脱敏任务载荷中的凭据和邮箱，返回不修改原对象的副本。"""
    if isinstance(value, Mapping):
        return {
            key: "<REDACTED>" if _SENSITIVE_KEY.search(str(key)) else redact_payload(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact_payload(item) for item in value]
    if isinstance(value, tuple):
        return [redact_payload(item) for item in value]
    if isinstance(value, str):
        scrubbed = _SENSITIVE_TEXT.sub(lambda match: f"{match.group(1)}=<REDACTED>", value)
        return _EMAIL.sub("<REDACTED_EMAIL>", scrubbed)
    return value


def load_pilot_dataset(path: Path) -> dict[str, Any]:
    """加载并脱敏试点数据；原始文件不会被覆盖。"""
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or not isinstance(payload.get("tasks"), list):
        raise ValueError("pilot dataset must be an object with a tasks list")
    scrubbed = redact_payload(payload)
    scrubbed.setdefault("schema_version", SCHEMA_VERSION)
    return scrubbed


def evaluate_pilot(dataset: Mapping[str, Any]) -> dict[str, Any]:
    """评估候选版本并生成可审计的试点报告。

    baseline 只比较 Agent 执行和最终状态；candidate 还必须有 accepted 的人工
    复核。缺少最终状态、来源或复核结论时直接进入 ``hold``，不把缺失证据算成失败率。
    """
    # 评估函数也做一次脱敏，避免调用方绕过 load_pilot_dataset 时把敏感值写入报告。
    scrubbed_dataset = redact_payload(dataset)
    if not isinstance(scrubbed_dataset, Mapping):
        raise ValueError("pilot dataset must be a mapping")
    tasks = list(scrubbed_dataset.get("tasks") or [])
    if not tasks:
        return _empty_report(scrubbed_dataset)

    seen: set[str] = set()
    baseline_rows: list[dict[str, Any]] = []
    candidate_rows: list[dict[str, Any]] = []
    row_reports: list[dict[str, Any]] = []
    quality_issues: list[dict[str, str]] = []
    review_counts = {"accepted": 0, "rejected": 0, "pending": 0, "missing": 0}

    for index, raw_task in enumerate(tasks, start=1):
        task = raw_task if isinstance(raw_task, Mapping) else {}
        if not isinstance(raw_task, Mapping):
            quality_issues.append({"task_id": f"<row-{index}>", "issue": "task_not_object"})
        task_id = str(task.get("task_id") or "")
        if not task_id or task_id in seen:
            quality_issues.append({"task_id": task_id or "<missing>", "issue": "duplicate_or_missing_task_id"})
        seen.add(task_id)
        baseline = task.get("baseline") or {}
        candidate = task.get("candidate") or {}
        review = task.get("human_review") or {}
        if not isinstance(review, Mapping):
            review = {}
        review_decision = str(review.get("decision") or "missing").lower()
        review_counts[review_decision if review_decision in review_counts else "missing"] += 1
        final_status = str(task.get("final_status") or "")
        split = str(task.get("split") or "")
        evidence = task.get("evidence") or {}
        if not isinstance(evidence, Mapping):
            evidence = {}
        source_ref = str(evidence.get("source_ref") or "")
        redaction = task.get("redaction") or {}
        if not isinstance(redaction, Mapping):
            redaction = {}

        if split not in _VALID_SPLITS:
            quality_issues.append({"task_id": task_id, "issue": "missing_or_invalid_split"})
        if not isinstance(baseline, Mapping) or "passed" not in baseline:
            quality_issues.append({"task_id": task_id, "issue": "baseline_result_missing"})
            baseline = {}
        if not isinstance(candidate, Mapping) or "passed" not in candidate:
            quality_issues.append({"task_id": task_id, "issue": "candidate_result_missing"})
            candidate = {}
        if final_status not in {"resolved", "needs_review", "unresolved"}:
            quality_issues.append({"task_id": task_id, "issue": "missing_or_invalid_final_status"})
        if not source_ref:
            quality_issues.append({"task_id": task_id, "issue": "missing_source_ref"})
        if redaction.get("applied") is not True:
            quality_issues.append({"task_id": task_id, "issue": "redaction_not_confirmed"})
        if redaction.get("human_verified") is False:
            quality_issues.append({"task_id": task_id, "issue": "redaction_human_review_incomplete"})
        if review_decision not in {"accepted", "rejected"}:
            quality_issues.append({"task_id": task_id, "issue": "human_review_incomplete"})

        baseline_passed = bool(baseline.get("passed")) and final_status == "resolved"
        candidate_passed = (
            bool(candidate.get("passed"))
            and final_status == "resolved"
            and review_decision == "accepted"
        )
        baseline_rows.append({"passed": baseline_passed, "duration_ms": baseline.get("duration_ms")})
        candidate_rows.append(
            {
                "passed": candidate_passed,
                "human_handoff": final_status == "needs_review" or review_decision == "rejected",
                "duration_ms": candidate.get("duration_ms"),
            }
        )
        row_reports.append(
            {
                "task_id": task_id,
                "split": split or "unknown",
                "baseline_passed": baseline_passed,
                "candidate_passed": candidate_passed,
                "review_decision": review_decision,
                "final_status": final_status or None,
                "source_ref": source_ref or None,
            }
        )

    baseline_metrics = business_scorecard(baseline_rows, duration_key="duration_ms")
    candidate_metrics = business_scorecard(
        candidate_rows,
        human_handoff_key="human_handoff",
        duration_key="duration_ms",
    )
    comparison = compare_scorecards(baseline_metrics, candidate_metrics)
    if quality_issues or comparison["decision"] == "hold":
        decision = "hold"
    else:
        decision = "pass"

    return {
        "schema_version": SCHEMA_VERSION,
        "project": scrubbed_dataset.get("project"),
        "baseline_version": scrubbed_dataset.get("baseline_version"),
        "candidate_version": scrubbed_dataset.get("candidate_version"),
        "baseline_provenance": scrubbed_dataset.get("baseline_provenance"),
        "candidate_provenance": scrubbed_dataset.get("candidate_provenance"),
        "decision": decision,
        "evidence_status": "complete" if not quality_issues else "incomplete",
        "metrics": {"baseline": baseline_metrics, "candidate": candidate_metrics},
        "comparison": comparison,
        "review": {"counts": review_counts},
        "data_quality": {"issues": quality_issues, "issue_count": len(quality_issues)},
        "tasks": row_reports,
    }


def _empty_report(dataset: Mapping[str, Any]) -> dict[str, Any]:
    """统一处理空数据集；空集不能通过业务发布门禁。"""
    empty = business_scorecard([])
    return {
        "schema_version": SCHEMA_VERSION,
        "project": dataset.get("project"),
        "baseline_version": dataset.get("baseline_version"),
        "candidate_version": dataset.get("candidate_version"),
        "baseline_provenance": dataset.get("baseline_provenance"),
        "candidate_provenance": dataset.get("candidate_provenance"),
        "decision": "hold",
        "evidence_status": "incomplete",
        "metrics": {"baseline": empty, "candidate": empty},
        "comparison": compare_scorecards(empty, empty),
        "review": {"counts": {"accepted": 0, "rejected": 0, "pending": 0, "missing": 0}},
        "data_quality": {"issues": [{"task_id": "<dataset>", "issue": "empty_tasks"}], "issue_count": 1},
        "tasks": [],
    }


__all__ = ["SCHEMA_VERSION", "evaluate_pilot", "load_pilot_dataset", "redact_payload"]
