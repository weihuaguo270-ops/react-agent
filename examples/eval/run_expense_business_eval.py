"""Run business-state evaluation and optionally export EvaluationEpisode files."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from react_agent.apps.expense.eval_business import (  # noqa: E402
    compare_business_runs,
    run_business_suite,
)


def _no_action_agent(case, ledger):
    """Fault-drill profile used to verify that release gates block regressions."""
    return "no action", [{"step": 1, "thought": "FINAL ANSWER: no action"}]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--split", choices=("dev", "golden", "held_out"))
    parser.add_argument("--agent-version", default="expense-agent-v1")
    parser.add_argument(
        "--profile",
        choices=("reference", "no_action"),
        default="reference",
        help="Reference policy executor or an injected regression for release drills.",
    )
    parser.add_argument("--episodes-out")
    parser.add_argument("--report-out")
    parser.add_argument("--compare-reference", action="store_true")
    args = parser.parse_args()

    agent_fn = _no_action_agent if args.profile == "no_action" else None
    result = run_business_suite(
        split=args.split,
        agent_version=args.agent_version,
        agent_fn=agent_fn,
    )
    report = result.to_dict()
    report["profile"] = args.profile
    if args.compare_reference:
        baseline = run_business_suite(split=args.split, agent_version="expense-agent-v1")
        report["comparison"] = compare_business_runs(baseline, result)
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    print(rendered)
    if args.report_out:
        output = Path(args.report_out)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered + "\n", encoding="utf-8")
    if args.episodes_out:
        output = Path(args.episodes_out)
        output.mkdir(parents=True, exist_ok=True)
        for case in result.cases:
            path = output / f"{case.case_id}.json"
            path.write_text(
                json.dumps(case.episode, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
    return 0 if result.pass_rate == 1.0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
