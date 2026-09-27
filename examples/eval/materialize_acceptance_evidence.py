"""Materialize per-task evidence bundles from the acceptance manifest."""
import json, shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "examples/fixtures/software_tasks/acceptance_task_set.json"
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
        fixture = ROOT / "examples/fixtures/software_tasks" / task["fixture"]
        if not fixture.exists(): fixture = ROOT / "examples/fixtures/failure_regression" / task["fixture"]
        shutil.copyfile(fixture, d / "trajectory.json")
        (d / "task.json").write_text(json.dumps(task, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
        (d / "test-result.json").write_text(json.dumps({"status":"pending","reason":"fixture materialization; execute task runner for real result"}, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
        (d / "acceptance.json").write_text(json.dumps({"status":"pending","decision":"pending","evidence":"fixture_only"}, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    print(f"materialized {len(manifest['tasks'])} evidence bundles under {OUT}")
    return 0
if __name__ == "__main__": raise SystemExit(main())
