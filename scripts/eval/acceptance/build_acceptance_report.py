"""Build an auditable report for the five-task acceptance manifest."""
import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = next(p for p in Path(__file__).resolve().parents if (p / "pyproject.toml").is_file())
MANIFEST = ROOT / "fixtures/software_tasks/acceptance_task_set.json"
OUT = ROOT / "artifacts/software_delivery_acceptance_v1.json"


def main() -> int:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    results = []
    for task in manifest["tasks"]:
        fixture = ROOT / "fixtures/software_tasks" / task["fixture"]
        if not fixture.exists():
            fixture = ROOT / "fixtures/failure_regression" / task["fixture"]
        evidence = "fixture_available" if fixture.exists() else "missing_fixture"
        results.append({**task, "evidence_status": evidence, "fixture_path": str(fixture.relative_to(ROOT))})
    report = {
        "suite": manifest["suite"],
        "size": len(results),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "scope": "minimal software delivery acceptance; fixture-backed, not production SLA",
        "tasks": results,
        "next_evidence": ["real trajectory", "test output", "repair/reverify record"],
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {OUT} ({len(results)} tasks)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
