"""把 GitHub 只读快照转换为人工审核队列（不会生成可执行任务）。"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from react_agent.eval.software_task_review import REQUIRED_REVIEW_FIELDS


def export_candidates(snapshot: str | Path, output: str | Path) -> int:
    raw = json.loads(Path(snapshot).read_text(encoding="utf-8"))
    repositories = ((raw.get("dataset") or {}).get("repositories") or [])
    cases = raw.get("cases") or []
    rows = []
    for case in cases:
        repo = case.get("repository")
        if not repo or repo not in repositories:
            continue
        rows.append({
            "repository": f"https://github.com/{repo}",
            "repository_name": repo,
            "case_id": case.get("case_id", ""),
            "split": case.get("split", "dev"),
            "source_url": case.get("source_url", f"https://github.com/{repo}/issues"),
            "status": "needs_manual_issue_review",
            "missing": list(REQUIRED_REVIEW_FIELDS),
        })
    payload = {
        "schema_version": "software-task-candidate/v1",
        "source_snapshot": str(snapshot),
        "source_type": "github_public_read_only_metadata",
        "disposition": "review_queue_only",
        "candidates": rows,
    }
    destination = Path(output)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return len(rows)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("snapshot")
    parser.add_argument("output")
    args = parser.parse_args()
    print(f"exported {export_candidates(args.snapshot, args.output)} review candidates")


if __name__ == "__main__":
    main()
