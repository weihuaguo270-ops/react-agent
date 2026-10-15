"""Run the expanded Expense candidate fixture without changing the S1 runner."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = next(path for path in Path(__file__).resolve().parents if (path / "pyproject.toml").is_file())
sys.path.insert(0, str(ROOT / "src"))

from react_agent.apps.expense.candidate_eval import (  # noqa: E402
    CandidateFixtureError,
    run_candidate_suite,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--split", choices=("dev", "golden", "held_out"), required=True)
    parser.add_argument("--agent-version", default="expense-candidate-v1")
    parser.add_argument("--fixture", type=Path)
    parser.add_argument("--allow-held-out", action="store_true")
    parser.add_argument("--episodes-out", type=Path)
    parser.add_argument("--report-out", type=Path)
    args = parser.parse_args()
    try:
        kwargs = {"split": args.split, "agent_version": args.agent_version, "allow_held_out": args.allow_held_out}
        if args.fixture:
            kwargs["path"] = args.fixture
        result = run_candidate_suite(**kwargs)
    except CandidateFixtureError as exc:
        print(json.dumps({"ok": False, "error_code": "candidate_fixture_error", "error": str(exc)}, ensure_ascii=False))
        return 2
    report = result.to_dict()
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if args.report_out:
        args.report_out.parent.mkdir(parents=True, exist_ok=True)
        args.report_out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if args.episodes_out:
        args.episodes_out.mkdir(parents=True, exist_ok=True)
        for case in result.cases:
            (args.episodes_out / f"{case.case_id}.json").write_text(
                json.dumps(case.episode, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )
    return 0 if all(case.passed for case in result.cases) else 1


if __name__ == "__main__":
    raise SystemExit(main())
