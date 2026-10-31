"""Select deterministic PR checks from changed paths.

The selector is intentionally report-only in its first release.  It records
the smallest mapped set and falls back to the complete deterministic PR set
when any path is unmapped.  Evaluation/Harness long runs are never part of
this fallback set.
"""
from __future__ import annotations

import argparse
import fnmatch
import json
import re
import subprocess
from pathlib import Path
from datetime import datetime, timezone


ROOT = Path(__file__).resolve().parents[2]
REGISTRY = ROOT / "docs/specs/ci/pr-check-registry.json"
FALLBACK_CHECKS = [
    "pr-ready",
    "lint",
    "test",
    "test-windows",
    "typecheck",
    "security",
    "docker-smoke",
    "docs-eval",
]


def fallback_report(
    reason: str,
    *,
    base_sha: str | None = None,
    head_sha: str | None = None,
    changed_files: list[str] | None = None,
    pr_number: int | None = None,
    event_name: str | None = None,
    blocking: bool = True,
) -> dict:
    return {
        "schema_version": "ci-pr-check-scope/v1",
        "mode": "report-only",
        "status": "fallback",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "base_sha": base_sha,
        "head_sha": head_sha,
        "pr_number": pr_number,
        "event_name": event_name,
        "changed_files": sorted({item.replace("\\", "/") for item in (changed_files or []) if item}),
        "matched_rules": {},
        "unmapped_paths": [],
        "selection_error": reason,
        "selected_checks": FALLBACK_CHECKS,
        "selected_test_paths": ["tests/"],
        "fallback_scope": "deterministic_pr_ci",
        "excluded_workflows": ["evaluation.yml", "harness.yml", "daily-smoke.yml"],
        # A missing or mismatched input cannot be trusted by a future hard gate.
        # Unmapped paths use the normal selector path and remain report-only.
        "blocking": blocking,
    }


def resolve_commit(ref: str) -> str:
    result = subprocess.run(
        ["git", "rev-parse", "--verify", f"{ref}^{{commit}}"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    sha = result.stdout.strip()
    if not re.fullmatch(r"[0-9a-f]{40}", sha):
        raise ValueError(f"ref did not resolve to a full commit SHA: {ref}")
    return sha


def collect_changed_files(base_ref: str, head_ref: str) -> tuple[list[str], str, str]:
    base_sha = resolve_commit(base_ref)
    head_sha = resolve_commit(head_ref)
    result = subprocess.run(
        ["git", "diff", "--name-only", f"{base_sha}...{head_sha}"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.splitlines(), base_sha, head_sha


def load_registry(path: Path = REGISTRY) -> dict:
    payload = json.loads(path.read_text(encoding="utf-8"))
    required = {"schema_version", "deterministic_pr_checks", "rules"}
    missing = required - payload.keys()
    if missing:
        raise ValueError(f"registry missing keys: {', '.join(sorted(missing))}")
    checks = payload["deterministic_pr_checks"]
    if len(checks) != len(set(checks)):
        raise ValueError("deterministic_pr_checks must be unique")
    if set(checks) != set(FALLBACK_CHECKS):
        raise ValueError("deterministic_pr_checks must match the complete fallback check set")
    check_set = set(checks)
    rule_ids: set[str] = set()
    for rule in payload["rules"]:
        if rule["id"] in rule_ids:
            raise ValueError(f"duplicate rule id: {rule['id']}")
        rule_ids.add(rule["id"])
        unknown = set(rule["checks"]) - check_set
        if unknown:
            raise ValueError(f"{rule['id']} references unknown checks: {', '.join(sorted(unknown))}")
        if not rule.get("paths") or any(not isinstance(path, str) for path in rule["paths"]):
            raise ValueError(f"{rule['id']} must define string path patterns")
        if any(not isinstance(path, str) for path in rule.get("pytest_paths", [])):
            raise ValueError(f"{rule['id']} pytest_paths must contain strings")
    return payload


def path_matches(path: str, pattern: str) -> bool:
    normalized = path.replace("\\", "/")
    while normalized.startswith("./"):
        normalized = normalized[2:]
    if pattern.endswith("/**"):
        prefix = pattern[:-3].rstrip("/")
        return normalized == prefix or normalized.startswith(prefix + "/")
    return fnmatch.fnmatchcase(normalized, pattern)


def select_checks(
    changed_files: list[str],
    registry: dict | None = None,
    *,
    base_sha: str | None = None,
    head_sha: str | None = None,
    pr_number: int | None = None,
    event_name: str | None = None,
) -> dict:
    registry = registry or load_registry()
    rules = registry["rules"]
    matched_rules: dict[str, list[str]] = {}
    unmapped: list[str] = []
    selected: set[str] = {"pr-ready"}
    selected_tests: set[str] = set()

    for path in sorted({item.replace("\\", "/") for item in changed_files if item}):
        path_rules = [rule for rule in rules if any(path_matches(path, glob) for glob in rule["paths"])]
        if not path_rules:
            if path.startswith("tests/") and path.endswith(".py") and not path.endswith("conftest.py"):
                selected_tests.add(path)
                selected.add("test")
            else:
                unmapped.append(path)
            continue
        ids = [rule["id"] for rule in path_rules]
        matched_rules[path] = ids
        for rule in path_rules:
            selected.update(rule["checks"])
            selected_tests.update(rule.get("pytest_paths", []))

    fallback = bool(unmapped)
    if fallback:
        selected = set(registry["deterministic_pr_checks"])
        selected_tests = {"tests/"}

    return {
        "schema_version": "ci-pr-check-scope/v1",
        "mode": registry.get("mode", "report-only"),
        "status": "fallback" if fallback else "mapped",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "base_sha": base_sha,
        "head_sha": head_sha,
        "pr_number": pr_number,
        "event_name": event_name,
        "changed_files": sorted({item.replace("\\", "/") for item in changed_files if item}),
        "matched_rules": matched_rules,
        "unmapped_paths": unmapped,
        "selected_checks": [check for check in registry["deterministic_pr_checks"] if check in selected],
        "selected_test_paths": sorted(selected_tests),
        "fallback_scope": "deterministic_pr_ci" if fallback else None,
        "excluded_workflows": ["evaluation.yml", "harness.yml", "daily-smoke.yml"],
        "blocking": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", help="base ref used to enumerate changed paths")
    parser.add_argument("--head", default="HEAD", help="head ref used to enumerate changed paths")
    parser.add_argument("--expected-head-sha", help="event head SHA that the checked out commit must match")
    parser.add_argument("--pr-number", type=int, help="pull request number for evidence correlation")
    parser.add_argument("--event-name", help="GitHub event name for evidence correlation")
    parser.add_argument("--changed-file", action="append", dest="changed_files")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    changed_files = args.changed_files
    base_sha = None
    head_sha = None
    try:
        if changed_files is None:
            if not args.base:
                raise ValueError("base ref is required to enumerate changed paths")
            changed_files, base_sha, head_sha = collect_changed_files(args.base, args.head)
        else:
            if not args.base:
                raise ValueError("base ref is required to validate changed paths")
            base_sha = resolve_commit(args.base)
            head_sha = resolve_commit(args.head)
        if args.expected_head_sha:
            expected_head_sha = args.expected_head_sha.lower()
            if not re.fullmatch(r"[0-9a-f]{40}", expected_head_sha):
                raise ValueError("expected head SHA must be a full 40-character commit SHA")
            if head_sha != expected_head_sha:
                raise ValueError(
                    f"checked out head SHA mismatch: expected {expected_head_sha}, resolved {head_sha}"
                )
        report = select_checks(
            changed_files,
            base_sha=base_sha,
            head_sha=head_sha,
            pr_number=args.pr_number,
            event_name=args.event_name,
        )
    except (OSError, ValueError, subprocess.CalledProcessError, KeyError, TypeError) as exc:
        report = fallback_report(
            str(exc),
            base_sha=base_sha,
            head_sha=head_sha,
            changed_files=changed_files,
            pr_number=args.pr_number,
            event_name=args.event_name,
        )
    encoded = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded, encoding="utf-8")
    print(encoded, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
