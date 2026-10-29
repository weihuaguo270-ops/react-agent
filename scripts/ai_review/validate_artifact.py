"""Validate and aggregate an AI Review artifact without calling a model.

This is the A0/A1 execution skeleton. It only validates provenance and applies
the deterministic status rules from the AI Review Spec.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

VALID_STATUSES = {"pass", "review_required", "fail", "blocked"}
VALID_CHECK_STATUSES = {"pass", "fail", "blocked"}
VALID_FINDING_STATUSES = {"open", "fixed", "accepted", "false_positive", "review_required"}
REQUIRED_FINDING_FIELDS = {
    "id",
    "severity",
    "confidence",
    "category",
    "file",
    "trigger",
    "expected",
    "actual",
    "evidence",
    "recommendation",
    "status",
}


class ArtifactError(ValueError):
    """Raised when an artifact cannot be safely interpreted."""


def _require_text(payload: dict[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ArtifactError(f"{key} must be a non-empty string")
    return value


def _validate_check(payload: dict[str, Any], name: str, head_sha: str) -> str:
    check = payload.get(name)
    if not isinstance(check, dict):
        raise ArtifactError(f"{name} must be an object")
    status = _require_text(check, "status")
    if status not in VALID_CHECK_STATUSES:
        raise ArtifactError(f"{name}.status must be one of {sorted(VALID_CHECK_STATUSES)}")
    if check.get("head_sha") != head_sha:
        raise ArtifactError(f"{name}.head_sha does not match artifact head_sha")
    return status


def validate_artifact(payload: Any, *, base_sha: str | None = None, head_sha: str | None = None) -> dict[str, Any]:
    """Return a normalized deterministic result or raise ``ArtifactError``."""

    if not isinstance(payload, dict):
        raise ArtifactError("artifact must be a JSON object")
    if payload.get("schema_version") != "ai-review/v1":
        raise ArtifactError("schema_version must be ai-review/v1")

    actual_base = _require_text(payload, "base_sha")
    actual_head = _require_text(payload, "head_sha")
    if base_sha is not None and actual_base != base_sha:
        raise ArtifactError("base_sha does not match the expected SHA")
    if head_sha is not None and actual_head != head_sha:
        raise ArtifactError("head_sha does not match the expected SHA")

    if not isinstance(payload.get("pr_number"), int) or payload["pr_number"] < 1:
        raise ArtifactError("pr_number must be a positive integer")
    if payload.get("risk_level") not in {"low", "medium", "high", "critical"}:
        raise ArtifactError("risk_level is invalid")

    ci_status = _validate_check(payload, "ci", actual_head)
    security_status = _validate_check(payload, "security", actual_head)
    findings = payload.get("findings")
    if not isinstance(findings, list):
        raise ArtifactError("findings must be a list")

    open_blockers = []
    open_high = []
    review_required = []
    for finding in findings:
        if not isinstance(finding, dict) or not REQUIRED_FINDING_FIELDS.issubset(finding):
            raise ArtifactError("each finding must include the required fields")
        if finding["status"] not in VALID_FINDING_STATUSES:
            raise ArtifactError(f"finding {finding.get('id')} has an invalid status")
        if not isinstance(finding["evidence"], list) or not finding["evidence"]:
            raise ArtifactError(f"finding {finding.get('id')} must include evidence")
        if finding["status"] in {"open", "review_required"}:
            if finding["severity"] == "blocker":
                open_blockers.append(finding["id"])
            elif finding["severity"] == "high":
                open_high.append(finding["id"])
            if finding["status"] == "review_required" or finding["confidence"] == "low":
                review_required.append(finding["id"])

    if ci_status == "blocked" or security_status == "blocked":
        status = "blocked"
    elif ci_status == "fail" or security_status == "fail" or open_blockers or open_high:
        status = "fail"
    elif review_required:
        status = "review_required"
    else:
        status = "pass"

    return {
        "schema_version": "ai-review/v1",
        "base_sha": actual_base,
        "head_sha": actual_head,
        "status": status,
        "risk_level": payload["risk_level"],
        "findings": findings,
        "ci_status": ci_status,
        "security_status": security_status,
        "blocking_finding_ids": open_blockers + open_high,
        "review_required_finding_ids": review_required,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("artifact", type=Path)
    parser.add_argument("--base-sha")
    parser.add_argument("--head-sha")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)

    try:
        payload = json.loads(args.artifact.read_text(encoding="utf-8"))
        result = validate_artifact(payload, base_sha=args.base_sha, head_sha=args.head_sha)
    except (OSError, json.JSONDecodeError, ArtifactError) as exc:
        result = {"status": "blocked", "error": str(exc)}
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 3

    rendered = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return {"pass": 0, "review_required": 0, "fail": 2, "blocked": 3}[result["status"]]


if __name__ == "__main__":
    sys.exit(main())
