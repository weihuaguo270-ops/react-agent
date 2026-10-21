"""Materialize per-task evidence bundles from the acceptance manifest."""
import json
import shutil
import sys
from pathlib import Path

ROOT = next(p for p in Path(__file__).resolve().parents if (p / "pyproject.toml").is_file())
sys.path.insert(0, str(ROOT / "src"))

from react_agent.harness.evaluation import build_repair_evidence


MANIFEST = ROOT / "fixtures/software_tasks/acceptance_task_set.json"
OUT = ROOT / "artifacts/software-delivery"

def main() -> int:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    for task in manifest["tasks"]:
        d = OUT / task["id"]
        d.mkdir(parents=True, exist_ok=True)
        existing = d / "acceptance.json"
        if existing.exists():
            try:
                if json.loads(existing.read_text(encoding="utf-8")).get("status") not in {"pending", "fixture_only"}:
                    continue
            except json.JSONDecodeError:
                pass
        fixture = ROOT / "fixtures/software_tasks" / task["fixture"]
        if not fixture.exists():
            fixture = ROOT / "fixtures/failure_regression" / task["fixture"]
        shutil.copyfile(fixture, d / "trajectory.json")
        (d / "task.json").write_text(
            json.dumps(task, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        pending = {
            "status": "pending",
            "reason": "fixture materialization; execute task runner for real result",
        }
        (d / "test-result.json").write_text(
            json.dumps(pending, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        shared = build_repair_evidence(
            task_id=task["id"],
            task=task,
            records={"fixture": pending},
            source_files={"fixture": fixture},
            phase="fixture_materialization",
            reverified=False,
            run_id="acceptance-fixture",
        )
        acceptance = {
            "status": "pending",
            "decision": "review",
            "evidence": "fixture_only",
            **shared,
        }
        (d / "acceptance.json").write_text(
            json.dumps(acceptance, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    print(f"materialized {len(manifest['tasks'])} evidence bundles under {OUT}")
    return 0
if __name__ == "__main__": raise SystemExit(main())
