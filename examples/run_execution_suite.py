"""跑 Execution-based 离线任务集并可选发布 docs 快照。

用法：
  python examples/run_execution_suite.py
  python examples/run_execution_suite.py --publish
  python examples/run_execution_suite.py --stem execution_snapshot_20260715
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from react_agent.eval.execution_scorer import (  # noqa: E402
    report_to_markdown,
    run_execution_suite,
)


def _git_sha() -> str:
    try:
        return (
            subprocess.check_output(
                ["git", "rev-parse", "--short", "HEAD"],
                cwd=ROOT,
                stderr=subprocess.DEVNULL,
            )
            .decode()
            .strip()
        )
    except Exception:
        return "unknown"


def main() -> int:
    parser = argparse.ArgumentParser(description="Execution-based offline suite")
    parser.add_argument(
        "--dataset",
        default=None,
        help="execution_dataset.json 路径（默认内置）",
    )
    parser.add_argument(
        "--publish",
        action="store_true",
        help="写入 docs/*.md + docs/snapshots/*.json",
    )
    parser.add_argument(
        "--stem",
        default=None,
        help="快照文件名 stem（默认 execution_snapshot_YYYYMMDD）",
    )
    args = parser.parse_args()

    report = run_execution_suite(args.dataset)
    s = report["summary"]
    print("=" * 55)
    print("  Execution Suite (offline_tools)")
    print(f"  {s['passed']}/{s['total']}  pass_rate={s['pass_rate']}%")
    print("=" * 55)
    for r in report["results"]:
        icon = "OK" if r["passed"] else ("SKIP" if r.get("skipped") else "FAIL")
        print(f"  [{icon}] {r['id']}: {r.get('reason', '')}")

    if args.publish:
        stem = args.stem or f"execution_snapshot_{datetime.now().strftime('%Y%m%d')}"
        docs = ROOT / "docs"
        snap_dir = docs / "snapshots"
        docs.mkdir(exist_ok=True)
        snap_dir.mkdir(exist_ok=True)
        json_path = snap_dir / f"{stem}.json"
        md_path = docs / f"{stem}.md"
        report["meta"] = {
            "git": _git_sha(),
            "reproduce_cmd": "python examples/run_execution_suite.py --publish",
        }
        json_path.write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        notes = [
            f"git: `{_git_sha()}`",
            f"archived_json: `docs/snapshots/{json_path.name}`",
            "reproduce: `python examples/run_execution_suite.py --publish`",
        ]
        md = report_to_markdown(report, title=f"Execution 公开快照（{stem}）")
        # inject notes after title block
        parts = md.split("\n", 2)
        extra = "\n".join(f"- {n}" for n in notes) + "\n"
        if len(parts) >= 3:
            md = parts[0] + "\n\n" + extra + parts[2]
        else:
            md = md + "\n" + extra
        md_path.write_text(md, encoding="utf-8")
        print(f"\nPublished:\n  {md_path}\n  {json_path}")

    return 0 if s["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
