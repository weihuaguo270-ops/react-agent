"""Import full historical runner evidence without claiming a fresh re-run."""
import hashlib
import json
from pathlib import Path

ROOT = next(p for p in Path(__file__).resolve().parents if (p / "pyproject.toml").is_file())
def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def collect(root=ROOT):
    source = root / "artifacts/software-tasks"
    output = root / "artifacts/software-delivery/repair_then_pass"
    current = output / "acceptance.json"
    if current.exists() and json.loads(current.read_text(encoding="utf-8")).get("reverified"):
        raise ValueError("Refusing to replace reverified evidence with historical records")
    records = {}
    provenance = {}
    for stage, suffix in (("before", "baseline"), ("after", "agent")):
        path = source / f"runs/fastapi-15974-{suffix}.json"
        records[stage] = json.loads(path.read_text(encoding="utf-8"))
        provenance[stage] = {"source": str(path.relative_to(root)),
                             "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
    before, after = records["before"], records["after"]
    for key in ("task_id", "task_hash", "base_commit"):
        if not before.get(key) or before[key] != after.get(key):
            raise ValueError(f"Mismatched task identity: {key}")
    if before.get("exit_code") != 1 or before.get("hidden_test", {}).get("status") != "failed":
        raise ValueError("Missing actual pre-repair test failure")
    if after.get("exit_code") != 0 or after.get("unauthorized_paths") != []:
        raise ValueError("Invalid post-repair result")
    for phase in ("public_test", "hidden_test"):
        if after.get(phase, {}).get("status") != "passed":
            raise ValueError("Post-repair tests did not pass")
    patch = source / "patches/fastapi-15974/agent.patch"
    if not patch.read_bytes() or Path(after.get("patch_path", "")).name != patch.name:
        raise ValueError("Missing linked agent patch")
    for stage, record in records.items():
        if not record.get("stdout"):
            raise ValueError(f"Missing raw stdout: {stage}")
        write_json(output / stage / "trajectory.json", record)
        write_json(output / stage / "test-result.json", {
            **record, "evidence_kind": "historical_runner_execution",
            "provenance": provenance[stage],
        })
        (output / stage / "stdout.log").write_text(record["stdout"], encoding="utf-8")
    repair = output / "repair"
    repair.mkdir(exist_ok=True)
    (repair / "patch.diff").write_bytes(patch.read_bytes())
    write_json(repair / "repair-result.json", {
        "status": "historical_patch_collected", "patch_kind": after.get("patch_kind"),
        "source": str(patch.relative_to(root)),
        "sha256": hashlib.sha256(patch.read_bytes()).hexdigest(),
        "changed_paths": after["changed_paths"], "applied_this_run": False,
    })
    write_json(output / "task.json", {
        "id": "repair_then_pass", "scenario": "repair",
        **{key: before[key] for key in ("task_id", "task_hash", "base_commit")},
        "evidence_kind": "historical_runner_execution", "provenance": provenance,
        "trajectory_format": "raw SoftwareTaskRunner result, not Format B",
        "legacy_root_files": "Superseded; use before/ and after/ only",
    })
    write_json(current, {
        "status": "historical_evidence_collected", "decision": "review",
        "pre_repair": {"test_status": "failed", "exit_code": 1, "log": "before/test-result.json"},
        "post_repair": {"test_status": "passed", "exit_code": 0, "log": "after/test-result.json"},
        "reverified": False, "provenance": provenance,
        "remaining": "Fresh baseline and patched execution required; Docker daemon unavailable at collection time",
    })
    print(f"Collected historical before/repair/after evidence: {output}")


if __name__ == "__main__":
    collect()
