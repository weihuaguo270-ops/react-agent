"""Run docs_troubleshoot Git-tracked docs held-out eval."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from react_agent.apps.docs_troubleshoot.eval_git_docs import (  # noqa: E402
    refresh_corpus_baseline,
    run_git_docs_eval,
)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--refresh-baseline",
        action="store_true",
        help="把当前 docs/ 状态记录为语料基线（确认断言仍有效后使用）",
    )
    parser.add_argument(
        "--strict-corpus",
        action="store_true",
        help="语料相对基线有变化时直接失败（默认只报告）",
    )
    args = parser.parse_args()

    if args.refresh_baseline:
        payload = refresh_corpus_baseline()
        print(f"已刷新语料基线：{len(payload['files'])} 个文件")
        raise SystemExit(0)

    report = run_git_docs_eval(strict_corpus=args.strict_corpus)
    drift = report.get("corpus") or {}
    if drift.get("status") == "changed":
        print(
            f"[corpus] 警告：docs/ 有 {drift.get('changed_count')} 个文件相对基线变化；"
            f"受影响用例={drift.get('affected_cases')}",
            file=sys.stderr,
        )
        print(f"[corpus] {drift.get('hint')}", file=sys.stderr)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    ok = report["passed"] == report["total"]
    print(
        f"\nRESULT: {'PASS' if ok else 'FAIL'} "
        f"({report['passed']}/{report['total']}) git={report.get('git_root')} "
        f"corpus={drift.get('status')}"
    )
    raise SystemExit(0 if ok else 1)


if __name__ == "__main__":
    main()
