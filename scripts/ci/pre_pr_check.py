#!/usr/bin/env python3
"""Pre-PR submission checks to catch common CI failures locally.

Run this before creating a PR to ensure:
- Conventional commit format
- No untracked files affecting tests
- Git-docs baseline is current
- Core tests pass locally
- No trailing whitespace or conflicts

Usage:
    python scripts/ci/pre_pr_check.py
    python scripts/ci/pre_pr_check.py --fix  # Auto-fix issues where possible
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class CheckResult:
    def __init__(self, name: str, passed: bool, message: str, fix_cmd: str = None):
        self.name = name
        self.passed = passed
        self.message = message
        self.fix_cmd = fix_cmd


def run_cmd(cmd: list[str], check: bool = False) -> subprocess.CompletedProcess:
    """Run command and return result."""
    return subprocess.run(cmd, capture_output=True, text=True, check=check, cwd=ROOT)


def check_git_status() -> CheckResult:
    """Check for uncommitted changes."""
    result = run_cmd(["git", "status", "--porcelain"])
    uncommitted = result.stdout.strip()

    if not uncommitted:
        return CheckResult("Git Status", True, "No uncommitted changes")

    return CheckResult(
        "Git Status",
        False,
        f"Uncommitted changes detected:\n{uncommitted[:500]}",
        "git add <files> && git commit -m '...'"
    )


def check_conventional_commit() -> CheckResult:
    """Check if HEAD commit follows conventional commit format."""
    result = run_cmd(["git", "log", "-1", "--pretty=%s"])
    commit_msg = result.stdout.strip()

    conventional_types = [
        "feat", "fix", "docs", "style", "refactor",
        "perf", "test", "build", "ci", "chore", "revert"
    ]

    if any(commit_msg.startswith(f"{t}:") or commit_msg.startswith(f"{t}(")
           for t in conventional_types):
        return CheckResult(
            "Conventional Commit",
            True,
            f"Commit follows convention: '{commit_msg[:60]}'"
        )

    return CheckResult(
        "Conventional Commit",
        False,
        f"HEAD commit doesn't follow conventional format: '{commit_msg}'",
        "git commit --amend -m 'feat: your message here'"
    )


def check_trailing_whitespace() -> CheckResult:
    """Check for trailing whitespace."""
    result = run_cmd(["git", "diff", "--check", "HEAD"])

    if result.returncode == 0:
        return CheckResult("Trailing Whitespace", True, "No trailing whitespace")

    return CheckResult(
        "Trailing Whitespace",
        False,
        f"Trailing whitespace found:\n{result.stdout[:500]}",
        "git diff --check and manually fix"
    )


def check_untracked_docs() -> CheckResult:
    """Check for untracked doc files that could affect git-docs baseline."""
    result = run_cmd(["git", "ls-files", "--others", "--exclude-standard"])
    untracked = result.stdout.strip().split('\n') if result.stdout.strip() else []

    untracked_docs = [f for f in untracked if f.startswith('docs/') and f.endswith('.md')]

    if not untracked_docs:
        return CheckResult("Untracked Docs", True, "No untracked doc files")

    return CheckResult(
        "Untracked Docs",
        False,
        f"Found {len(untracked_docs)} untracked doc files:\n" +
        "\n".join(f"  - {f}" for f in untracked_docs[:10]),
        "git add docs/*.md  # or: git clean -fd docs/"
    )


def check_git_docs_baseline() -> CheckResult:
    """Check if git-docs baseline matches current corpus."""
    baseline_path = ROOT / "src/react_agent/apps/docs_troubleshoot/git_docs_corpus_baseline.json"

    if not baseline_path.exists():
        return CheckResult(
            "Git-Docs Baseline",
            False,
            "Baseline file not found",
            "python scripts/eval/docs/run_git_docs_eval.py --refresh-baseline"
        )

    # Run drift detection test
    result = run_cmd([
        sys.executable, "-m", "pytest",
        "tests/test_git_docs_corpus_drift.py::test_drift_clean_when_matching_baseline",
        "-xvs"
    ])

    if result.returncode == 0:
        return CheckResult("Git-Docs Baseline", True, "Baseline matches current corpus")

    return CheckResult(
        "Git-Docs Baseline",
        False,
        "Baseline out of sync with current docs corpus",
        "python scripts/eval/docs/run_git_docs_eval.py --refresh-baseline"
    )


def check_core_tests() -> CheckResult:
    """Run quick core tests."""
    # Run a subset of fast tests
    result = run_cmd([
        sys.executable, "-m", "pytest",
        "tests/test_harness_contracts.py",
        "tests/evaluation/test_execution_episode_integration.py",
        "tests/evaluation/test_eval_runner_episode_integration.py",
        "-q", "--tb=short"
    ])

    if result.returncode == 0:
        return CheckResult("Core Tests", True, "Core tests passed")

    return CheckResult(
        "Core Tests",
        False,
        f"Core tests failed:\n{result.stdout[-500:]}",
        "pytest tests/ -x  # Run tests to identify failures"
    )


def check_lint() -> CheckResult:
    """Check code formatting."""
    result = run_cmd([sys.executable, "-m", "ruff", "check", "src/", "tests/"])

    if result.returncode == 0:
        return CheckResult("Lint", True, "Linting passed")

    return CheckResult(
        "Lint",
        False,
        f"Linting issues found:\n{result.stdout[:500]}",
        "ruff check --fix src/ tests/"
    )


def auto_fix_baseline() -> bool:
    """Auto-fix git-docs baseline."""
    print("  -> Running baseline refresh...")
    result = run_cmd([
        sys.executable,
        "scripts/eval/docs/run_git_docs_eval.py",
        "--refresh-baseline"
    ])

    if result.returncode == 0:
        print("  [OK] Baseline refreshed successfully")
        return True

    print(f"  [FAIL] Baseline refresh failed: {result.stderr}")
    return False


def auto_fix_lint() -> bool:
    """Auto-fix linting issues."""
    print("  -> Running ruff fix...")
    result = run_cmd([sys.executable, "-m", "ruff", "check", "--fix", "src/", "tests/"])

    if result.returncode == 0:
        print("  [OK] Linting issues fixed")
        return True

    print(f"  [FAIL] Some linting issues couldn't be auto-fixed")
    return False


def main():
    parser = argparse.ArgumentParser(description="Pre-PR submission checks")
    parser.add_argument("--fix", action="store_true", help="Auto-fix issues where possible")
    parser.add_argument("--quick", action="store_true", help="Skip slow tests")
    args = parser.parse_args()

    print("=" * 70)
    print("Pre-PR Submission Checks")
    print("=" * 70)
    print()

    checks = [
        ("Git Status", check_git_status),
        ("Conventional Commit", check_conventional_commit),
        ("Trailing Whitespace", check_trailing_whitespace),
        ("Untracked Docs", check_untracked_docs),
        ("Git-Docs Baseline", check_git_docs_baseline),
    ]

    if not args.quick:
        checks.extend([
            ("Lint", check_lint),
            ("Core Tests", check_core_tests),
        ])

    results = []

    for name, check_fn in checks:
        print(f"Checking: {name}...", end=" ", flush=True)
        result = check_fn()
        results.append(result)

        if result.passed:
            print("[PASS]")
        else:
            print("[FAIL]")
            print(f"  {result.message}")

            if args.fix and result.fix_cmd:
                print(f"  Fix suggestion: {result.fix_cmd}")

                # Auto-fix specific issues
                if args.fix:
                    if name == "Git-Docs Baseline":
                        auto_fix_baseline()
                    elif name == "Lint":
                        auto_fix_lint()

        print()

    # Summary
    passed = sum(1 for r in results if r.passed)
    total = len(results)

    print("=" * 70)
    print(f"Summary: {passed}/{total} checks passed")
    print("=" * 70)

    if passed == total:
        print("[OK] All checks passed! Ready to create PR.")
        return 0

    print("[FAIL] Some checks failed. Please fix issues before creating PR.")
    print()
    print("Quick fixes:")
    for result in results:
        if not result.passed and result.fix_cmd:
            print(f"  - {result.name}: {result.fix_cmd}")

    return 1


if __name__ == "__main__":
    sys.exit(main())
