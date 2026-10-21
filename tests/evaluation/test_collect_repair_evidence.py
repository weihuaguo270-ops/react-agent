import importlib.util
import hashlib
import json
import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from react_agent.harness.evaluation import build_repair_evidence

SPEC = importlib.util.spec_from_file_location("collect_repair", ROOT / "scripts/eval/failure/collect_repair_evidence.py")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
MATERIALIZE_SPEC = importlib.util.spec_from_file_location(
    "materialize_acceptance",
    ROOT / "scripts/eval/acceptance/materialize_acceptance_evidence.py",
)
MATERIALIZE_MODULE = importlib.util.module_from_spec(MATERIALIZE_SPEC)
MATERIALIZE_SPEC.loader.exec_module(MATERIALIZE_MODULE)

# `collect()` 读取 artifacts/software-tasks 下的真实 runner 产物；那些文件由 Docker +
# FastAPI checkout 的 SoftwareTaskRunner 生成，CI 无法产出（也不在版本库里），
# 所以同一份目录布局以紧凑夹具提交在下面。用例因此不依赖机器本地遗留产物。
FIXTURE_ROOT = ROOT / "fixtures" / "software_tasks" / "repair_evidence"
SEED_FILES = (
    "runs/fastapi-15974-baseline.json",
    "runs/fastapi-15974-agent.json",
    "patches/fastapi-15974/agent.patch",
)


def seed(tmp_path):
    for name in SEED_FILES:
        target = tmp_path / "artifacts" / "software-tasks" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(FIXTURE_ROOT / name, target)


def test_historical_collection_does_not_claim_reverification(tmp_path):
    seed(tmp_path)
    MODULE.collect(tmp_path)
    bundle = tmp_path / "artifacts/software-delivery/repair_then_pass"
    result = json.loads((bundle / "acceptance.json").read_text())
    assert result["decision"] == "review"
    assert result["reverified"] is False
    assert result["pre_repair"]["exit_code"] == 1
    assert result["post_repair"]["exit_code"] == 0
    assert "FAILED" in (bundle / "before/stdout.log").read_text(encoding="utf-8")
    manifest = result["fixture_manifest"]
    assert manifest["fixture_id"] == "software-repair:repair_then_pass"
    assert manifest["environment"]["dataset_status"] == "historical_evidence"
    assert result["batch_id"].startswith("repair-")
    episodes = result["evaluation_episodes"]
    assert [episode["episode_id"].rsplit(":", 1)[-1] for episode in episodes] == ["before", "after"]
    assert all(episode["batch_id"] == result["batch_id"] for episode in episodes)
    assert all(episode["fixture_manifest"] == manifest for episode in episodes)
    assert all(episode["environment"]["evidence_only"] is True for episode in episodes)
    for episode in episodes:
        artifact = next(a for a in episode["artifacts"] if a["id"].startswith("trajectory:"))
        trajectory = episode["trajectory"]
        encoded = json.dumps(trajectory, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        assert artifact["sha256"] == hashlib.sha256(encoded).hexdigest()
        assert artifact["metadata"]["format"] == "harness-trajectory/v1"
        assert trajectory["schema_version"]


def test_rejects_mismatched_baseline(tmp_path):
    seed(tmp_path)
    path = tmp_path / "artifacts/software-tasks/runs/fastapi-15974-agent.json"
    result = json.loads(path.read_text(encoding="utf-8"))
    result["base_commit"] = "different"
    path.write_text(json.dumps(result), encoding="utf-8")
    with pytest.raises(ValueError, match="Mismatched"):
        MODULE.collect(tmp_path)
    assert not (tmp_path / "artifacts/software-delivery/repair_then_pass/acceptance.json").exists()


def test_fixture_evidence_stays_out_of_execution_counts(tmp_path):
    source = tmp_path / "fixture.json"
    source.write_text('{"status":"pending"}', encoding="utf-8")
    evidence = build_repair_evidence(
        task_id="fixture-case",
        task={"id": "fixture-case", "split": "held_out"},
        records={"fixture": {"status": "pending"}},
        source_files={"fixture": source},
        phase="fixture_materialization",
        reverified=False,
        run_id="seed",
    )
    assert evidence["fixture_manifest"]["environment"]["dataset_status"] == "fixture_evidence"
    episode = evidence["evaluation_episodes"][0]
    assert episode["score"]["passed"] is None
    assert episode["environment"]["evidence_only"] is True
    assert episode["trajectory"]["metadata"]["execution_status"] == "not_run_by_adapter"


def test_acceptance_materializer_writes_shared_fixture_evidence(tmp_path, monkeypatch):
    fixture_root = tmp_path / "fixtures/software_tasks"
    fixture_root.mkdir(parents=True)
    (fixture_root / "case.json").write_text('{"fixture":true}', encoding="utf-8")
    manifest = fixture_root / "acceptance_task_set.json"
    manifest.write_text(json.dumps({"tasks": [{"id": "pending-case", "fixture": "case.json"}]}), encoding="utf-8")
    output = tmp_path / "artifacts/software-delivery"
    monkeypatch.setattr(MATERIALIZE_MODULE, "ROOT", tmp_path)
    monkeypatch.setattr(MATERIALIZE_MODULE, "MANIFEST", manifest)
    monkeypatch.setattr(MATERIALIZE_MODULE, "OUT", output)

    assert MATERIALIZE_MODULE.main() == 0
    result = json.loads((output / "pending-case/acceptance.json").read_text(encoding="utf-8"))
    assert result["reverified"] is False
    assert result["fixture_manifest"]["environment"]["dataset_status"] == "fixture_evidence"
    assert result["evaluation_episodes"][0]["score"]["passed"] is None

