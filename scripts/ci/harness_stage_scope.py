"""Run the Harness P4 gate only when a PR declares P4 complete."""
from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PROGRESS_PATH = "progress.yaml"


def read_progress(ref: str) -> dict:
    result = subprocess.run(
        ["git", "show", f"{ref}:{PROGRESS_PATH}"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return json.loads(result.stdout)


def declares_stage_completion(base_progress: dict, head_progress: dict, stage: str) -> bool:
    before = base_progress.get("stages", {}).get(stage, {}).get("status")
    after = head_progress.get("stages", {}).get(stage, {}).get("status")
    return before != "complete" and after == "complete"


def inspect_stage_completion(base_ref: str, head_ref: str, stage: str) -> dict:
    changed: list[str] = []
    try:
        changed = subprocess.run(
            ["git", "diff", "--name-only", f"{base_ref}...{head_ref}"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        ).stdout.splitlines()
        if PROGRESS_PATH not in changed:
            return {"stage": stage, "run": False, "reason": "progress.yaml unchanged"}
        before = read_progress(base_ref)
        after = read_progress(head_ref)
        run = declares_stage_completion(before, after, stage)
        return {
            "stage": stage,
            "run": run,
            "reason": "stage status changed to complete" if run else "no new completion declaration",
        }
    except (OSError, ValueError, subprocess.CalledProcessError, json.JSONDecodeError) as exc:
        return {
            "stage": stage,
            "run": False,
            "blocked": True,
            "reason": f"unable to verify progress declaration: {exc}",
        }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", required=True)
    parser.add_argument("--head", required=True)
    parser.add_argument("--stage", required=True)
    parser.add_argument("--github-output", type=Path)
    args = parser.parse_args()

    report = inspect_stage_completion(args.base, args.head, args.stage)
    print(json.dumps(report, ensure_ascii=False))
    if report.get("blocked"):
        return 1
    if args.github_output:
        with args.github_output.open("a", encoding="utf-8") as stream:
            stream.write(f"run_harness_stage={'true' if report['run'] else 'false'}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
