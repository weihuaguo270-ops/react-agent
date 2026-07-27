"""Run docs_troubleshoot Git-tracked docs held-out eval."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from react_agent.apps.docs_troubleshoot.eval_git_docs import run_git_docs_eval  # noqa: E402


def main():
    report = run_git_docs_eval()
    print(json.dumps(report, ensure_ascii=False, indent=2))
    ok = report["passed"] == report["total"]
    print(
        f"\nRESULT: {'PASS' if ok else 'FAIL'} "
        f"({report['passed']}/{report['total']}) git={report.get('git_root')}"
    )
    raise SystemExit(0 if ok else 1)


if __name__ == "__main__":
    main()
