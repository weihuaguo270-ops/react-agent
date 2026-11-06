"""Independent expected-check policy used to audit the report-only selector."""

from __future__ import annotations

import fnmatch
import argparse
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path


FULL = (
    "pr-ready",
    "lint",
    "test",
    "test-windows",
    "typecheck",
    "security",
    "docker-smoke",
    "docs-eval",
)


def _matches(path: str, patterns: tuple[str, ...]) -> bool:
    normalized = path.replace("\\", "/")
    return any(
        normalized == pattern
        if "/" not in pattern and not any(char in pattern for char in "*?[]")
        else fnmatch.fnmatchcase(normalized, pattern)
        for pattern in patterns
    )


def _path_checks(path: str) -> tuple[set[str], str]:
    if _matches(path, (".github/workflows/**", ".codex/**", "scripts/ci/**", "pyproject.toml", "setup.py", "setup.cfg", "requirements*.txt")):
        return set(FULL), "cross_cutting"
    if _matches(path, ("Dockerfile*", "docker-compose*.yml", "docker-compose*.yaml")):
        return {"pr-ready", "lint", "security", "docker-smoke"}, "container_config"
    if path == "src/react_agent/apps/docs_troubleshoot/git_docs_corpus_baseline.json":
        return {"pr-ready", "docs-eval"}, "docs_corpus_baseline"
    if path == "tests/test_real_llm.py":
        return {"pr-ready"}, "real_llm_evidence"
    if _matches(
        path,
        (
            "eval/**",
            "experiments/**",
            "artifacts/**",
            "fixtures/**",
            "examples/eval/**",
            "examples/fixtures/**",
            "scripts/**",
            "demos/**",
            "schemas/**",
            "notes/**",
        ),
    ) and not _matches(path, ("scripts/ci/**", "scripts/ai_review/**")):
        checks = {"pr-ready"}
        if _matches(path, ("eval/**/Dockerfile*", "Dockerfile*", "docker-compose*.yml", "docker-compose*.yaml")):
            checks.update({"security", "docker-smoke"})
        return checks, "evaluation_evidence"
    if _matches(path, ("scripts/ai_review/**",)):
        return {"pr-ready", "test"}, "ai_review_tools"
    if _matches(path, ("docs/**", "README.md", "CONTRIBUTING.md")):
        return {"pr-ready", "docs-eval"}, "docs"
    if _matches(path, ("src/react_agent/apps/docs_troubleshoot/**", "tests/apps/docs_troubleshoot/**")):
        return {"pr-ready", "lint", "test", "docs-eval"}, "docs_troubleshoot"
    if path.startswith("tests/") and path.endswith(".py"):
        checks = {"pr-ready", "test"}
        if any(token in path for token in ("console", "portable_paths", "windows", "encoding")):
            checks.add("test-windows")
        return checks, "tests"
    if path.startswith("src/") and path.endswith(".py"):
        checks = {"pr-ready", "lint", "test", "typecheck"}
        if any(token in path for token in ("safety/", "auth", "permission", "github/")):
            checks.add("security")
        if any(token in path for token in ("console", "portable", "paths", "encoding")):
            checks.add("test-windows")
        return checks, "python_source"
    if path.startswith("tests/") and path.endswith((".json", ".yaml", ".yml")):
        return {"pr-ready", "test"}, "test_fixture"
    if path in {
        "AGENTS.md",
        ".gitignore",
        ".flake8",
        ".env.example",
        "Makefile",
        "cleanup.ps1",
        "CHANGELOG.md",
        "DOCS_REORGANIZATION_SUMMARY.md",
        "REORGANIZATION_SUMMARY.md",
        "P5_CHECKLIST.md",
        "examples/README.md",
        "llm_config.example.json",
    }:
        return {"pr-ready"}, "project_metadata"
    if path == "test_all.py":
        return {"pr-ready", "test"}, "test_entrypoint"
    return set(FULL), "unknown"


def expected_checks(changed_files: list[str]) -> dict:
    """Return a conservative minimum check set and its independent rationale.

    This policy intentionally has no import from ``pr-check-registry.json``.
    Unknown or cross-cutting paths require the complete deterministic suite.
    """
    paths = sorted({path.replace("\\", "/") for path in changed_files if path})
    if not paths:
        return {"checks": list(FULL), "class": "unknown", "reason": "empty change set"}

    per_path = {path: _path_checks(path) for path in paths}
    checks = set().union(*(value[0] for value in per_path.values()))
    classes = sorted({value[1] for value in per_path.values()})
    return {
        "checks": [check for check in FULL if check in checks],
        "class": "+".join(classes),
        "reason": "per-path independent policy; union of required checks",
    }


def _resolve_commit(ref: str) -> str:
    result = subprocess.run(
        ["git", "rev-parse", "--verify", f"{ref}^{{commit}}"],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _changed_files(base: str, head: str) -> tuple[list[str], str, str]:
    base_sha = _resolve_commit(base)
    head_sha = _resolve_commit(head)
    result = subprocess.run(
        ["git", "diff", "--name-only", f"{base_sha}...{head_sha}"],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.splitlines(), base_sha, head_sha


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", required=True)
    parser.add_argument("--head", default="HEAD")
    parser.add_argument("--pr-number", type=int)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    changed_files, base_sha, head_sha = _changed_files(args.base, args.head)
    policy = expected_checks(changed_files)
    report = {
        "schema_version": "ci-expected-pr-checks/v1",
        "mode": "report-only",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "base_sha": base_sha,
        "head_sha": head_sha,
        "pr_number": args.pr_number,
        "changed_files": sorted({item.replace("\\", "/") for item in changed_files if item}),
        "expected_checks": policy["checks"],
        "change_class": policy["class"],
        "reason": policy["reason"],
        "source": "scripts/ci/expected_pr_checks.py",
    }
    encoded = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded, encoding="utf-8")
    print(encoded, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
