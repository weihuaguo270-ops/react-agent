"""Run docs_troubleshoot golden-set offline eval."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

os.environ["REACT_AGENT_APP"] = "docs_troubleshoot"
os.environ.setdefault("REACT_AGENT_RAG_MODE", "keyword")

from react_agent.apps.docs_troubleshoot.eval_golden import run_golden_eval


def main():
    report = run_golden_eval()
    print(json.dumps(report, ensure_ascii=False, indent=2))
    # Production gate: require full pass on golden set (Workflow path, no leakage)
    ok = report["passed"] == report["total"]
    print(
        f"\nRESULT: {'PASS' if ok else 'FAIL'} "
        f"({report['passed']}/{report['total']}) path={report.get('path')} "
        f"by_tag={report.get('by_tag')}"
    )
    raise SystemExit(0 if ok else 1)


if __name__ == "__main__":
    main()
