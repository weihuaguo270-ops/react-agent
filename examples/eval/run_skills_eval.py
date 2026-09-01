"""Run the dependency-light business Skill evaluation."""
from __future__ import annotations

import json

from react_agent.skills.evaluation import run_skill_evaluation


def main() -> int:
    report = run_skill_evaluation()
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
