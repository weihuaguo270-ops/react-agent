"""Record trusted runtime context for an external fork pull request.

The probe is deliberately evidence-only. It does not read or print secrets and
it does not turn a same-repository run into proof of fork isolation. A passed
probe proves only that the reusable workflow observed a fork PR at a specific
head SHA under the declared read-only permission contract.
"""

from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path
from typing import Any


def _text(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def build_report(event: dict[str, Any], *, run_id: str | None = None) -> dict[str, Any]:
    repository = event.get("repository")
    pull_request = event.get("pull_request")
    if not isinstance(repository, dict) or not isinstance(pull_request, dict):
        return {
            "schema_version": "ci-r9-runtime-probe/v1",
            "status": "blocked",
            "reason": "event is not a pull_request payload",
        }

    base = pull_request.get("base")
    head = pull_request.get("head")
    base_repo = base.get("repo") if isinstance(base, dict) else None
    head_repo = head.get("repo") if isinstance(head, dict) else None
    base_sha = _text(base.get("sha")) if isinstance(base, dict) else None
    head_sha = _text(head.get("sha")) if isinstance(head, dict) else None
    base_full_name = _text(base_repo.get("full_name")) if isinstance(base_repo, dict) else None
    head_full_name = _text(head_repo.get("full_name")) if isinstance(head_repo, dict) else None
    is_fork = bool(base_full_name and head_full_name and base_full_name != head_full_name)
    return {
        "schema_version": "ci-r9-runtime-probe/v1",
        "status": "passed" if is_fork and head_sha and base_sha else "blocked",
        "head_sha": head_sha,
        "base_sha": base_sha,
        "repository": _text(repository.get("full_name")),
        "head_repository": head_full_name,
        "is_fork": is_fork,
        "run_id": run_id or os.getenv("GITHUB_RUN_ID"),
        "run_url": (
            f"https://github.com/{repository.get('full_name')}/actions/runs/{run_id or os.getenv('GITHUB_RUN_ID')}"
            if repository.get("full_name") and (run_id or os.getenv("GITHUB_RUN_ID"))
            else None
        ),
        "permission_contract": {
            "contents": "read",
            "secrets": "not_requested",
        },
        "secret_observation": {
            "status": "not_observed",
            "reason": "The probe never receives or prints a secret; absence must be enforced by the pull_request event boundary.",
        },
        "event_name": os.getenv("GITHUB_EVENT_NAME", "pull_request"),
        "trusted_workflow_ref": os.getenv("TRUSTED_WORKFLOW_REF"),
        "conclusion_boundary": "This artifact records a fork pull_request run and its read-only workflow contract. It does not expose or inspect secret values.",
    }


def validate_report(
    report: dict[str, Any], *, expected_head_sha: str, expected_base_sha: str
) -> dict[str, Any]:
    """Validate an artifact against the PR being gated without trusting its status alone."""
    errors: list[str] = []
    if report.get("schema_version") != "ci-r9-runtime-probe/v1":
        errors.append("runtime probe schema is missing or unsupported")
    if report.get("status") != "passed":
        errors.append("runtime probe did not pass")
    if report.get("is_fork") is not True:
        errors.append("runtime probe was not produced for an external fork")
    if report.get("event_name") != "pull_request":
        errors.append("runtime probe did not run for a pull_request event")
    if report.get("head_sha") != expected_head_sha:
        errors.append("runtime probe head_sha does not match the gated PR head")
    if report.get("base_sha") != expected_base_sha:
        errors.append("runtime probe base_sha does not match the gated PR base")
    if not report.get("run_id") or not report.get("run_url") or not report.get("trusted_workflow_ref"):
        errors.append("runtime probe is missing remote workflow provenance")
    trusted_ref = report.get("trusted_workflow_ref")
    if not isinstance(trusted_ref, str) or not re.fullmatch(
        r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+/\.github/workflows/r9-runtime-probe\.yml@[0-9a-f]{40}",
        trusted_ref,
    ):
        errors.append("runtime probe workflow source is not pinned to an immutable commit")
    if not report.get("repository") or report.get("repository") == report.get("head_repository"):
        errors.append("runtime probe repository identities do not prove a fork")
    contract = report.get("permission_contract")
    permission_values = (
        [value for key, value in contract.items() if key not in {"source", "secrets"}]
        if isinstance(contract, dict)
        else []
    )
    if (
        not isinstance(contract, dict)
        or contract.get("contents") != "read"
        or contract.get("secrets") != "not_requested"
        or not permission_values
        or any(value != "read" for value in permission_values)
    ):
        errors.append("runtime probe permission contract is not read-only")
    observation = report.get("secret_observation")
    if not isinstance(observation, dict) or observation.get("status") != "not_observed":
        errors.append("runtime probe secret observation is not fail-closed")
    return {
        "status": "passed" if not errors else "blocked",
        "errors": errors,
        "head_sha": report.get("head_sha"),
        "base_sha": report.get("base_sha"),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--event", type=Path, default=Path(os.environ.get("GITHUB_EVENT_PATH", "event.json")))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    event = json.loads(args.event.read_text(encoding="utf-8"))
    report = build_report(event)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "head_sha": report.get("head_sha"), "is_fork": report.get("is_fork", False)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
