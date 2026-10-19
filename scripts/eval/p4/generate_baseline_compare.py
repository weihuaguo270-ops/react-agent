"""Generate baseline compare report for repair evidence."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src"))

from react_agent.harness.evaluation.baseline_compare import compare_repair_evidence


def main():
    # Compare repair_then_pass evidence
    repair_dir = ROOT / "artifacts" / "software-delivery" / "repair_then_pass"
    output_dir = ROOT / "artifacts" / "harness"
    output_path = output_dir / "baseline-compare-latest.json"

    if not repair_dir.exists():
        print(f"ERROR: Repair evidence directory not found: {repair_dir}")
        return 1

    print(f"Comparing repair evidence: {repair_dir}")
    report = compare_repair_evidence(repair_dir)

    # Write report
    output_dir.mkdir(parents=True, exist_ok=True)
    import json
    output_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8"
    )

    print(f"Baseline compare report generated: {output_path}")
    print(f"Status: {report.get('summary', {}).get('status', 'unknown')}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
