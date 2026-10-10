"""Validate the minimal five-task software delivery acceptance manifest."""
import json
from pathlib import Path

ROOT = next(p for p in Path(__file__).resolve().parents if (p / "pyproject.toml").is_file())
MANIFEST = ROOT / "fixtures/software_tasks/acceptance_task_set.json"
REQUIRED = {"pass", "repair", "hold", "approval_denied", "tool_timeout"}


def main() -> int:
    data = json.loads(MANIFEST.read_text(encoding="utf-8"))
    tasks = data.get("tasks", [])
    scenarios = {t.get("scenario") for t in tasks}
    if data.get("size") != 5 or len(tasks) != 5 or scenarios != REQUIRED:
        raise SystemExit(f"invalid acceptance suite: size={len(tasks)} scenarios={scenarios}")
    for task in tasks:
        fixture = ROOT / "fixtures/software_tasks" / task["fixture"]
        if not fixture.exists():
            fixture = ROOT / "fixtures/failure_regression" / task["fixture"]
        if not fixture.exists():
            raise SystemExit(f"missing fixture: {task['fixture']}")
    print(f"OK: {data['suite']} ({len(tasks)} tasks): {', '.join(sorted(scenarios))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
