"""Run the offline Security Triage golden set and emit replayable metrics."""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

from react_agent.apps.security_triage.episode import write_evaluation_episode
from react_agent.apps.security_triage.replay import write_replay
from react_agent.apps.security_triage.workflow import run_triage

_REPO_ROOT = Path(__file__).resolve().parents[2]


def _resolve_dataset(path: str) -> Path:
    candidate = Path(path)
    if candidate.is_file():
        return candidate
    rooted = _REPO_ROOT / candidate
    if rooted.is_file():
        return rooted
    raise FileNotFoundError(f"security triage dataset not found: {path}")


def _check(case: dict[str, Any], expect: dict[str, Any], answer: str = "") -> dict[str, bool]:
    cves = case["cves"]
    kev_values = [item["listed"] for item in case["kev"]]
    matched_values = [item["matched"] for item in case["asset_matches"]]
    priorities = [item["priority"] for item in case["recommendations"]]
    answer = str(answer).lower()
    required_terms = [str(term).lower() for term in expect.get("required_terms", [])]
    forbidden_terms = [str(term).lower() for term in expect.get("forbidden_terms", [])]

    def forbidden_assertion(term: str) -> bool:
        if term in {"safe", "unaffected"}:
            pattern = (
                rf"\b(?:is|appears|confirmed|considered|deemed)\s+{re.escape(term)}\b"
                if term == "unaffected"
                else rf"\b(?:is|appears|confirmed|considered|deemed)\s+safe\b|\bsafe\s+to\b"
            )
            for match in re.finditer(pattern, answer):
                prefix = answer[max(0, match.start() - 45) : match.start()]
                if re.search(r"\b(?:not|no|without|absence\s+of|does\s+not|doesn't|cannot|can't|never)\b[^.!?]*$", prefix):
                    continue
                return True
            return False
        if term == "malicious=true":
            return bool(re.search(r"\bmalicious\s*=\s*true\b", answer))
        return term in answer

    return {
        "kev_listed": expect.get("kev_listed") is None or expect.get("kev_listed") in kev_values,
        "asset_matched": expect.get("asset_matched") is None or expect.get("asset_matched") in matched_values,
        "priority": expect["priority"] in priorities,
        "review_status": case["status"] == expect.get("review_status", "pending_review"),
        "executed_actions": len(case["executed_actions"]) == expect.get("executed_actions", 0),
        "citations_present": all(item.get("citation_id") for item in [*cves, *case["kev"], *case["iocs"]]),
        "fact_consistency": all(term in answer for term in required_terms)
        and not any(forbidden_assertion(term) for term in forbidden_terms),
    }


def run(
    dataset_path: str,
    replay_path: str | None = None,
    episodes_path: str | None = None,
) -> dict[str, Any]:
    resolved_dataset = _resolve_dataset(dataset_path)
    dataset = json.loads(resolved_dataset.read_text(encoding="utf-8"))
    rows = []
    feedback_queue = []
    for item in dataset:
        result = run_triage(
            item["input"],
            episode_id=item["id"],
            split=str(item.get("split") or "golden"),
            expected=item["expect"],
        )
        case = result["case"]
        checks = _check(case, item["expect"], result.get("answer", ""))
        if replay_path:
            write_replay(replay_path, item["input"], result)
        if episodes_path:
            write_evaluation_episode(episodes_path, result["episode"])
        rows.append({"id": item["id"], "category": item.get("category", "uncategorized"), "checks": checks, "ok": all(checks.values())})
        if result["episode"].get("metadata", {}).get("failure_feedback"):
            feedback_queue.append(
                {
                    "id": item["id"],
                    "category": item.get("category", "uncategorized"),
                    "feedback": result["episode"]["metadata"]["failure_feedback"],
                }
            )
    passed = sum(row["ok"] for row in rows)
    return {
        "schema_version": "security-triage-evaluation/v2",
        "dataset": str(resolved_dataset),
        "cases": len(rows),
        "passed": passed,
        "accuracy": passed / len(rows) if rows else 1.0,
        "citation_support_rate": sum(row["checks"]["citations_present"] for row in rows) / len(rows) if rows else 1.0,
        "fact_consistency_rate": sum(row["checks"]["fact_consistency"] for row in rows) / len(rows) if rows else 1.0,
        "false_safe_assertions": sum(
            1 for row in rows if not row["checks"]["fact_consistency"] and row["category"] in {"unknown_cve", "ioc_unknown", "ioc_conflict"}
        ),
        "feedback_queue": feedback_queue,
        "rows": rows,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", default="examples/fixtures/security_triage_goldens.json")
    parser.add_argument("--replay-out", default="")
    parser.add_argument("--episodes-out", default="")
    args = parser.parse_args()
    print(json.dumps(run(args.dataset, args.replay_out or None, args.episodes_out or None), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
