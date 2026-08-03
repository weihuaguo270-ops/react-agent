"""Run docs_troubleshoot golden-set offline eval."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

os.environ["REACT_AGENT_APP"] = "docs_troubleshoot"
os.environ.setdefault("REACT_AGENT_RAG_MODE", "keyword")

from react_agent.apps.docs_troubleshoot.eval_golden import (  # noqa: E402
    eval_gate_ok,
    publish_golden_snapshot,
    run_golden_eval,
)


def main():
    parser = argparse.ArgumentParser(description="Docs/API troubleshoot golden eval")
    parser.add_argument(
        "--path",
        default="agent",
        choices=["agent", "workflow", "chat_offline"],
        help="eval path: agent (default) | workflow (legacy DAG) | chat_offline (alias)",
    )
    parser.add_argument(
        "--gate",
        default="all",
        choices=["all", "non_held_out"],
        help="pass gate: all tags or exclude held_out tier",
    )
    parser.add_argument(
        "--publish",
        action="store_true",
        help="write docs/snapshots + docs/reports markdown",
    )
    parser.add_argument("--stem", default="", help="snapshot stem (default: dated)")
    args = parser.parse_args()

    report = run_golden_eval(path=args.path)
    print(json.dumps(report, ensure_ascii=False, indent=2))

    ok = eval_gate_ok(report, gate=args.gate)
    print(
        f"\nRESULT: {'PASS' if ok else 'FAIL'} "
        f"({report['passed']}/{report['total']}) path={report.get('path')} "
        f"gate={args.gate} by_tag={report.get('by_tag')}"
    )

    if args.publish:
        archived, md = publish_golden_snapshot(report, stem=args.stem or None)
        print(f"Published: {archived}\n           {md}")

    raise SystemExit(0 if ok else 1)


if __name__ == "__main__":
    main()
