"""Run business-state evaluation and optionally export EvaluationEpisode files."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from react_agent.apps.expense.eval_business import run_business_suite  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--split", choices=("dev", "golden", "held_out"))
    parser.add_argument("--agent-version", default="expense-agent-v1")
    parser.add_argument("--episodes-out")
    args = parser.parse_args()

    result = run_business_suite(split=args.split, agent_version=args.agent_version)
    print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
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
