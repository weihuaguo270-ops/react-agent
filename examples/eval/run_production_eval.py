"""Run docs_troubleshoot production blind-set eval (external corpus)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from react_agent.apps.docs_troubleshoot.eval_production import run_production_eval  # noqa: E402


def main():
    report = run_production_eval()
    print(json.dumps(report, ensure_ascii=False, indent=2))
    ok = report["passed"] == report["total"]
    metrics = report.get("metrics") or {}
    print(
        f"\nRESULT: {'PASS' if ok else 'FAIL'} "
        f"({report['passed']}/{report['total']}) corpus={report.get('corpus')}"
    )
    if metrics:
        print(
            "METRICS: "
            f"production_source_hit_rate={metrics.get('production_source_hit_rate')} "
            f"avg_evidence_sufficiency={metrics.get('avg_evidence_sufficiency')}"
        )
    raise SystemExit(0 if ok else 1)


if __name__ == "__main__":
    main()
