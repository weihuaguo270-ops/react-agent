"""Run docs_troubleshoot simulated fault-case eval."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

os.environ["REACT_AGENT_APP"] = "docs_troubleshoot"
os.environ.setdefault("REACT_AGENT_RAG_MODE", "keyword")

from react_agent.apps.docs_troubleshoot.eval_fault import run_fault_eval  # noqa: E402


def main():
    report = run_fault_eval()
    print(json.dumps(report, ensure_ascii=False, indent=2))
    ok = report["passed"] == report["total"]
    print(
        f"\nRESULT: {'PASS' if ok else 'FAIL'} "
        f"({report['passed']}/{report['total']}) by_tag={report.get('by_tag')}"
    )
    metrics = report.get("metrics") or {}
    if metrics:
        print(
            "METRICS: "
            f"root_cause_hit_rate={metrics.get('root_cause_hit_rate')} "
            f"evidence_sufficiency_rate={metrics.get('evidence_sufficiency_rate')} "
            f"evidence_n={metrics.get('evidence_sufficiency_sample_size')} "
            f"wrong_suggestion_rate={metrics.get('wrong_suggestion_rate')}"
        )
    raise SystemExit(0 if ok else 1)


if __name__ == "__main__":
    main()
