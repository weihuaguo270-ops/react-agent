"""Read-only checks for a commit or pull request before delivery.

The command deliberately does not stage files, modify baselines, rebase,
merge, push, or delete anything. Use ``--ci`` in a pull-request workflow and
``--pr`` for the final remote PR state check before merging.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

FORBIDDEN_PATHS = {
    ".env",
    "mcp_servers.json",
    "llm_config.json",
}
CONVENTIONAL_COMMIT = re.compile(r"^(feat|fix|docs|test|ci|refactor|chore|perf|build|revert)(\(.+\))?!?:\s+\S")


def run(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=check,
    )


def git(*args: str, check: bool = True) -> str:
    result = run("git", *args, check=check)
    return result.stdout.strip()


def fail(message: str, failures: list[str]) -> None:
    failures.append(message)
    print(f"FAIL: {message}", file=sys.stderr)


def changed_files(base: str | None) -> list[str]:
    if not base:
        return []
    result = run("git", "diff", "--name-only", f"{base}...HEAD", check=False)
    if result.returncode:
        return []
    return [line for line in result.stdout.splitlines() if line]


def check_corpus(failures: list[str], *, strict: bool) -> None:
    try:
        from react_agent.apps.docs_troubleshoot.eval_git_docs import corpus_drift

        drift = corpus_drift()
    except Exception as exc:  # pragma: no cover - environment/import diagnostic
        fail(f"unable to inspect docs corpus baseline: {exc}", failures)
        return
    status = drift.get("status")
    if status != "clean":
        files = ", ".join(drift.get("changed_files") or []) or "none"
        dirty_docs = bool(run("git", "status", "--porcelain", "--", "docs").stdout.strip())
        message = f"docs corpus baseline is {status} (changed: {files})"
        if strict or not dirty_docs:
            fail(message, failures)
        else:
            print(f"WARN: {message}; existing uncommitted docs changes are preserved")
    else:
        print("PASS: docs corpus baseline is clean")


def check_remote_pr(number: int, repo: str, failures: list[str]) -> None:
    result = run(
        "gh",
        "pr",
        "view",
        str(number),
        "--repo",
        repo,
        "--json",
        "state,baseRefName,headRefName,headRefOid,mergeable,mergeStateStatus",
        check=False,
    )
    if result.returncode:
        fail(f"cannot inspect PR #{number}: {result.stderr.strip()}", failures)
        return
    try:
        pr = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        fail(f"invalid GitHub PR response: {exc}", failures)
        return

    if pr.get("state") != "OPEN":
        fail(f"PR #{number} is {pr.get('state')}, not OPEN", failures)
    if pr.get("baseRefName") != "main":
        fail(f"PR #{number} targets {pr.get('baseRefName')}, not main", failures)
    if pr.get("mergeable") == "CONFLICTING" or pr.get("mergeStateStatus") == "DIRTY":
        fail(
            f"PR #{number} is not mergeable: "
            f"mergeable={pr.get('mergeable')} state={pr.get('mergeStateStatus')}",
            failures,
        )
    elif pr.get("mergeable") == "UNKNOWN":
        fail(f"PR #{number} mergeability is UNKNOWN; recheck before merging", failures)
    else:
        print(
            f"PASS: PR #{number} targets main and reports "
            f"mergeable={pr.get('mergeable')} state={pr.get('mergeStateStatus')}"
        )

    checks = run("gh", "pr", "checks", str(number), "--repo", repo, check=False)
    if checks.returncode:
        fail(f"required PR checks are not all passing for #{number}", failures)
        if checks.stdout.strip():
            print(checks.stdout.strip())
    else:
        print(f"PASS: required PR checks pass for #{number}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", help="local base ref for changed-file and ancestry checks")
    parser.add_argument("--base-sha", help="base SHA supplied by a pull-request workflow")
    parser.add_argument("--pr", type=int, help="GitHub PR number to inspect")
    parser.add_argument("--repo", help="GitHub owner/name; required with --pr")
    parser.add_argument("--ci", action="store_true", help="fail on a dirty worktree and stale base")
    parser.add_argument("--allow-revert", action="store_true", help="allow revert commits")
    args = parser.parse_args(argv)

    failures: list[str] = []
    status = git("status", "--short", "--branch")
    print(status or "(clean worktree)")
    if args.ci and git("status", "--porcelain"):
        fail("CI worktree is dirty", failures)

    diff_check = run("git", "diff", "--check", check=False)
    if diff_check.returncode:
        fail("git diff --check found whitespace errors", failures)
        print(diff_check.stdout + diff_check.stderr, file=sys.stderr)
    else:
        print("PASS: git diff --check")
    staged_check = run("git", "diff", "--cached", "--check", check=False)
    if staged_check.returncode:
        fail("git diff --cached --check found whitespace errors", failures)
        print(staged_check.stdout + staged_check.stderr, file=sys.stderr)
    else:
        print("PASS: git diff --cached --check")

    head_message = git("log", "-1", "--pretty=%s")
    # Allow revert commits if flag is set
    if args.allow_revert and head_message.startswith("Revert "):
        print(f"PASS: revert commit allowed ({head_message})")
    elif not CONVENTIONAL_COMMIT.match(head_message):
        fail(f"HEAD commit is not conventional: {head_message!r}", failures)
    else:
        print(f"PASS: conventional HEAD commit ({head_message})")

    requested_base = args.base_sha or args.base
    base_refs = [requested_base] if requested_base else []
    if args.ci:
        remote_main = git("rev-parse", "--verify", "refs/remotes/origin/main", check=False)
        if remote_main:
            base_refs.insert(0, remote_main)

    base = base_refs[0] if base_refs else None
    files = changed_files(base)
    if files:
        print(f"Changed files against {base}: {len(files)}")
        forbidden = sorted({Path(name).name for name in files} & FORBIDDEN_PATHS)
        if forbidden:
            fail(f"forbidden credential/config files changed: {', '.join(forbidden)}", failures)
        if args.ci:
            for base_ref in base_refs:
                ancestry = run("git", "merge-base", "--is-ancestor", base_ref, "HEAD", check=False)
                if ancestry.returncode:
                    fail(f"HEAD does not contain base {base_ref}; update the PR branch", failures)
                else:
                    print(f"PASS: PR head contains base {base_ref}")
        docs_changed = any(name == "docs" or name.startswith("docs/") for name in files)
        baseline_changed = any(name.endswith("git_docs_corpus_baseline.json") for name in files)
        if docs_changed or baseline_changed:
            check_corpus(failures, strict=args.ci)
    elif base:
        print(f"WARN: unable to enumerate changes against {base}")
    else:
        check_corpus(failures, strict=args.ci)

    if args.pr is not None:
        if not args.repo:
            parser.error("--repo is required with --pr")
        check_remote_pr(args.pr, args.repo, failures)

    if failures:
        print(f"\nPR READY: FAIL ({len(failures)} blocker(s))", file=sys.stderr)
        return 1
    print("\nPR READY: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
