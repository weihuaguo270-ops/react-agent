"""EvaluationEpisode adapter for the Security Triage vertical application."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


EPISODE_SCHEMA_VERSION = "evaluation-episode/v1"


def _input_id(body: dict[str, Any]) -> str:
    digest = hashlib.sha256(
        json.dumps(body, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()[:16]
    return f"security-triage-{digest}"


def _primary_priority(case: dict[str, Any]) -> str | None:
    priorities = [
        str(item.get("priority"))
        for item in case.get("recommendations", [])
        if item.get("priority") != "required_review"
    ]
    if priorities:
        return priorities[0]
    if case.get("recommendations"):
        return str(case["recommendations"][0].get("priority"))
    return None


def _final_security_state(case: dict[str, Any], answer: str) -> dict[str, Any]:
    kev = [item.get("listed") for item in case.get("kev", [])]
    assets = [item.get("matched") for item in case.get("asset_matches", [])]
    citations = [str(item.get("id")) for item in case.get("citations", []) if item.get("id")]
    llm_report = case.get("llm_report") or {}
    return {
        "kev_listed": kev[0] if len(set(kev)) <= 1 and kev else any(value is True for value in kev),
        "asset_matched": any(value is True for value in assets),
        "priority": _primary_priority(case),
        "review_status": case.get("status"),
        "executed_actions": len(case.get("executed_actions", [])),
        "citations_present": all(
            item.get("citation_id")
            for item in [*case.get("cves", []), *case.get("kev", []), *case.get("iocs", [])]
        ),
        "citation_ids": citations,
        "answer": str(answer),
        "llm_report": {
            "fallback": bool(llm_report.get("fallback", True)),
            "failure": llm_report.get("failure"),
            "output_format": llm_report.get("output_format"),
        },
    }


def _expected_security_state(expected: dict[str, Any]) -> dict[str, Any]:
    state: dict[str, Any] = {}
    for key in ("kev_listed", "asset_matched"):
        if expected.get(key) is not None:
            state[key] = expected[key]
    if expected.get("priority") is not None:
        state["priority"] = expected["priority"]
    state["review_status"] = expected.get("review_status", "pending_review")
    state["executed_actions"] = expected.get("executed_actions", 0)
    state["citations_present"] = True
    return state


def _state_checks(expected: dict[str, Any], actual: dict[str, Any], path: str = "$") -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    for key, expected_value in expected.items():
        current_path = f"{path}.{key}"
        if isinstance(expected_value, dict):
            actual_value = actual.get(key) if isinstance(actual, dict) else None
            if not isinstance(actual_value, dict):
                checks.append({"path": current_path, "expected": expected_value, "actual": actual_value, "passed": False})
            else:
                checks.extend(_state_checks(expected_value, actual_value, current_path))
            continue
        actual_value = actual.get(key) if isinstance(actual, dict) else None
        checks.append({"path": current_path, "expected": expected_value, "actual": actual_value, "passed": actual_value == expected_value})
    return checks


def _feedback_actions(checks: list[dict[str, Any]], case: dict[str, Any]) -> list[dict[str, str]]:
    actions: list[dict[str, str]] = []
    targets = {
        "kev_listed": ("tool_schema", "Review KEV lookup normalization and evidence mapping."),
        "asset_matched": ("tool_schema", "Review asset/SBOM correlation input and tool output contract."),
        "priority": ("prompt", "Review risk-priority instructions and recommendation selection."),
        "review_status": ("workflow_guard", "Review human-review state transition and gate."),
        "executed_actions": ("workflow_guard", "Review read-only execution boundary and action guard."),
        "citations_present": ("validator", "Review citation collection and citation-bound validation."),
    }
    for check in checks:
        if check.get("passed"):
            continue
        leaf = str(check.get("path", "")).rsplit(".", 1)[-1]
        target, action = targets.get(leaf, ("validator", "Review the security state verifier and expected-state mapping."))
        actions.append({"signal": leaf, "target": target, "action": action})
    llm = case.get("llm_report") or {}
    if llm.get("fallback") and llm.get("failure") not in {None, "llm_disabled"}:
        actions.append(
            {
                "signal": "llm_fallback",
                "target": "report_node",
                "action": "Review structured report prompt, repair policy, or deterministic fallback reason.",
            }
        )
    unique: dict[tuple[str, str], dict[str, str]] = {}
    for item in actions:
        unique[(item["signal"], item["target"])] = item
    return list(unique.values())


def build_evaluation_episode(
    body: dict[str, Any],
    result: dict[str, Any],
    *,
    episode_id: str | None = None,
    split: str = "dev",
    expected: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a framework-neutral episode without importing llm-eval-engine."""
    case = result["case"]
    answer = str(result.get("answer") or "")
    final_security = _final_security_state(case, answer)
    expected_security = _expected_security_state(expected or {})
    checks = _state_checks(expected_security, final_security)
    feedback = _feedback_actions(checks, case)
    trace = case.get("trace") or []
    steps = []
    for index, node in enumerate(trace, start=1):
        node_name = str(node.get("node") or f"step_{index}")
        steps.append(
            {
                "step": index,
                "thought": f"Run security triage stage: {node_name}.",
                "action": {
                    "name": node_name,
                    "arguments": json.dumps({"status": node.get("status")}, ensure_ascii=False),
                },
                "observation": json.dumps(node, ensure_ascii=False, sort_keys=True),
            }
        )
    episode_id = episode_id or _input_id(body)
    expected_terms = list((expected or {}).get("required_terms") or [])
    forbidden_terms = list((expected or {}).get("forbidden_terms") or [])
    acceptance = [
        "security state matches the expected KEV, asset correlation, and priority outcome",
        "all recommendations remain not_executed and require human approval",
    ]
    if expected_terms:
        acceptance.append(f"report contains required evidence terms: {', '.join(map(str, expected_terms))}")
    if forbidden_terms:
        acceptance.append(f"report avoids forbidden safety assertions: {', '.join(map(str, forbidden_terms))}")
    return {
        "schema_version": EPISODE_SCHEMA_VERSION,
        "episode_id": str(episode_id),
        "task": str(body.get("message") or body.get("query") or "Security triage request"),
        "framework": "react-agent-security-triage",
        "agent_version": "security-triage-v1",
        "split": str(split),
        "acceptance_criteria": acceptance,
        "expected_state": {"security": expected_security} if expected is not None else {},
        "final_state": {"security": final_security},
        "state_verification": {
            "passed": bool(checks) and all(item["passed"] for item in checks),
            "checks": checks,
        },
        "trajectory": {
            "session_id": str(episode_id),
            "task_episode_id": str(episode_id),
            "query": str(body.get("message") or body.get("query") or "Security triage request"),
            "model": str((case.get("llm_report") or {}).get("model") or "deterministic-security-triage"),
            "steps": steps,
            "final_answer": answer,
        },
        "metadata": {
            "domain": "security_triage",
            "verifier": "security_state_subset",
            "required_terms": expected_terms,
            "forbidden_terms": forbidden_terms,
            "case_schema_version": case.get("schema_version"),
            "feedback_targets": sorted({item["target"] for item in feedback}),
            "failure_feedback": feedback,
        },
    }


def write_evaluation_episode(path: str | Path, episode: dict[str, Any]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(episode, ensure_ascii=False, sort_keys=True) + "\n")


def load_evaluation_episodes(path: str | Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]
