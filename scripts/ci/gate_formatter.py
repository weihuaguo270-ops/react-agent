#!/usr/bin/env python3
"""Enhanced gate output formatter - wraps harness_stage_gate.py with friendly output.

This wrapper runs the actual gate and formats the output in a more user-friendly way,
showing clear status for each acceptance item and providing actionable next steps.
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PROGRESS = ROOT / "progress.yaml"

# Simple ASCII symbols for Windows compatibility
SYMBOLS = {
    "complete": "[OK]",
    "partial": "[~]",
    "in_progress": "[->]",
    "not_started": "[X]",
    "pass": "[+]",
    "fail": "[-]",
}


def print_header(title: str):
    """Print section header."""
    print(f"\n{'=' * 70}")
    print(f"{title}")
    print(f"{'=' * 70}")


def print_acceptance_item(item: dict, evidence: dict):
    """Print acceptance item status with visual indicators."""
    item_id = item["id"]
    status = item.get("status", "unknown")
    title = item.get("title", item_id)

    # Determine symbol
    symbol = SYMBOLS.get(status, "[?]")

    print(f"\n{symbol} {item_id}: {title} ({status})")

    # Show evidence
    evidence_paths = item.get("evidence", [])
    if evidence_paths:
        print(f"  Evidence:")
        for path in evidence_paths:
            path_obj = ROOT / path
            if path_obj.exists():
                print(f"    [+] {path}")
            else:
                print(f"    [-] {path} (MISSING)")

    # Show notes if present
    notes = item.get("notes")
    if notes:
        print(f"  Note: {notes}")

    # Show missing evidence from gate report
    if evidence and not evidence.get("passed"):
        missing = evidence.get("missing", [])
        if missing:
            print(f"  Missing:")
            for m in missing:
                print(f"    - {m}")


def format_gate_output(stage: str, returncode: int):
    """Format gate output in a friendly way."""
    # Load progress to get acceptance items
    progress = json.loads(PROGRESS.read_text(encoding="utf-8"))
    stage_data = progress["stages"].get(stage, {})
    stage_name = stage_data.get("name", stage)
    stage_status = stage_data.get("status", "unknown")

    print_header(f"{stage}: {stage_name} - {stage_status.upper()}")

    # Load gate report
    report_path = ROOT / "artifacts" / "harness" / "stage-gates" / f"{stage.lower()}-latest.json"
    if report_path.exists():
        report = json.loads(report_path.read_text(encoding="utf-8"))

        # Show test results summary
        print(f"\nTest Results:")
        if report["test_exit_code"] == 0:
            # Extract test summary from stdout
            stdout = report.get("test_stdout", "")
            if "passed" in stdout:
                # Parse pytest output
                lines = stdout.split("\n")
                for line in lines:
                    if "passed" in line or "failed" in line:
                        print(f"  [+] {line.strip()}")
                        break
            else:
                print(f"  [+] All tests passed")
        else:
            print(f"  [-] Tests failed (exit code {report['test_exit_code']})")

        # Show acceptance items
        print(f"\nAcceptance Items:")
        acceptance_items = stage_data.get("acceptance", [])
        acceptance_evidence = {item["id"]: item for item in report.get("acceptance_evidence", [])}

        completed = 0
        total = len(acceptance_items)

        for item in acceptance_items:
            item_id = item["id"]
            evidence = acceptance_evidence.get(item_id, {})
            print_acceptance_item(item, evidence)
            if item.get("status") == "complete":
                completed += 1

        # Show progress
        print(f"\nProgress: {completed}/{total} acceptance items complete")

        # Show next steps
        pending = [item for item in acceptance_items if item.get("status") != "complete"]
        if pending:
            print(f"\nNext Steps:")
            for i, item in enumerate(pending[:3], 1):  # Show top 3
                print(f"  {i}. Complete {item['id']}: {item.get('title', '')}")
                # Show what's missing
                evidence = acceptance_evidence.get(item["id"], {})
                missing = evidence.get("missing", [])
                if missing:
                    for m in missing:
                        print(f"     -> Create {m}")

        # Show gate status
        print_header("Gate Status")
        if report["passed"]:
            print(f"[OK] PASSED - All requirements met")
        else:
            print(f"[~] NOT PASSED - {len(pending)} items remaining")
            print(f"\nTo complete this stage:")
            print(f"  1. Address the items listed above")
            print(f"  2. Re-run: python scripts/ci/harness_stage_gate.py --stage {stage}")

    else:
        print(f"\n[-] Gate report not found")

    return returncode


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", required=True, help="Stage to test (P0, P1, P2, P3, P4, P5)")
    parser.add_argument("--raw", action="store_true", help="Show raw output instead of formatted")
    args = parser.parse_args()

    # Run the actual gate
    cmd = [sys.executable, str(ROOT / "scripts/ci/harness_stage_gate.py"), "--stage", args.stage]

    if args.raw:
        # Just pass through
        result = subprocess.run(cmd, cwd=ROOT)
        return result.returncode
    else:
        # Capture and format
        result = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)

        # Show formatted output
        returncode = format_gate_output(args.stage, result.returncode)

        # Show raw output at the end if there were errors
        if result.returncode != 0 and result.stderr:
            print(f"\nRaw Error Output:")
            print(result.stderr)

        return returncode


if __name__ == "__main__":
    sys.exit(main())
