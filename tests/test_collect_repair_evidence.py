import importlib.util
import json
import shutil
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("collect_repair", ROOT / "examples/eval/collect_repair_evidence.py")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def seed(tmp_path):
    source = Path("artifacts/software-tasks")
    for name in ("runs/fastapi-15974-baseline.json", "runs/fastapi-15974-agent.json", "patches/fastapi-15974/agent.patch"):
        target = tmp_path / source / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / source / name, target)


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


def test_rejects_mismatched_baseline(tmp_path):
    seed(tmp_path)
    path = tmp_path / "artifacts/software-tasks/runs/fastapi-15974-agent.json"
    result = json.loads(path.read_text(encoding="utf-8"))
    result["base_commit"] = "different"
    path.write_text(json.dumps(result), encoding="utf-8")
    with pytest.raises(ValueError, match="Mismatched"):
        MODULE.collect(tmp_path)
    assert not (tmp_path / "artifacts/software-delivery/repair_then_pass/acceptance.json").exists()
