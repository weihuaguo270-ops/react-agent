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
        "permission_contract": {
            "contents": "read",
            "actions": "read",
            "secrets": "not_requested",
        },
        "secret_observation": {
            "status": "not_observed",
            "reason": "The probe never receives or prints a secret; absence must be enforced by the pull_request event boundary.",
        },
        "conclusion_boundary": "This artifact proves fork metadata and SHA binding only. It is not proof of secret isolation unless produced by the trusted reusable workflow for an actual fork PR.",
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
