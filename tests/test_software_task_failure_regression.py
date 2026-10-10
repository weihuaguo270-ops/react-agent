"""Acceptance: FastAPI SoftwareTasks hang on the failure-regression pipeline."""
from __future__ import annotations

import json
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

pytest.importorskip("trace_debugger")
pytest.importorskip("eval_engine")

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "eval" / "failure" / "run_software_task_failure_regression.py"
FIXTURES = ROOT / "fixtures" / "software_tasks"
OUT_ROOT = ROOT / "artifacts" / "failure-regression" / "pytest-software-tasks"

REQUIRED = (
    "fastapi-15764-agent.json",
    "fastapi-15974-agent.json",
    "fastapi-16253-agent.json",
)


@pytest.fixture(scope="module")
def acceptance_summary() -> dict:
    missing = [name for name in REQUIRED if not (FIXTURES / name).is_file()]
    assert not missing, f"committed fixtures required (do not skip): {missing}"
    out = OUT_ROOT / f"run-{uuid.uuid4().hex[:8]}"
    proc = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--out",
            str(out),
            "--expect-all-pass-good",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    summary_path = out / "acceptance_summary.json"
    assert summary_path.is_file(), proc.stdout + "\n" + proc.stderr
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    assert proc.returncode == 0, proc.stdout + "\n" + proc.stderr
    return summary


def test_three_tasks_have_independent_gate_json(acceptance_summary):
    tasks = acceptance_summary["tasks"]
    assert len(tasks) == 3
    for item in tasks:
        good_dir = Path(item["good"]["out_dir"])
        for name in (
            "release.json",
            "findings.json",
            "process_quality.json",
            "repair_feedback.json",
            "failures.json",
        ):
            assert (good_dir / name).is_file(), f"{item['task_id']} missing {name}"
        assert item["good"]["release_decision"] == "pass"
        assert item["good"]["baseline_source"] == "provided"
        assert item["bad"]["release_decision"] == "hold"
        assert item["bad"]["repair_feedback_actionable"] is True
        gated = Path(item["gated_agent_run"])
        assert gated.is_file()
        payload = json.loads(gated.read_text(encoding="utf-8"))
        assert "failure_regression" in payload
        assert payload["failure_regression"]["release_decision"] == "pass"


def test_frozen_baseline_not_self_compare(acceptance_summary):
    baseline = Path(acceptance_summary["frozen_baseline"])
    assert baseline.is_file()
    for item in acceptance_summary["tasks"]:
        assert item["good"]["baseline_source"] == "provided"
        assert item["bad"]["baseline_source"] == "provided"


def test_reverify_playbook_improved_to_pass(acceptance_summary):
    play = acceptance_summary["reverify_playbook"]
    assert play["parent_release_decision"] == "hold"
    assert play["child_release_decision"] == "pass"
    assert play["improved_to_pass"] is True
    assert play["required"] is True
    assert Path(play["parent_hold"]).is_dir()
    assert Path(play["child_pass"]).is_dir()


def test_claim_and_boundaries(acceptance_summary):
    assert "夹具 + 3 条 SoftwareTask" in acceptance_summary["claim"]
    joined = " ".join(acceptance_summary["boundaries"])
    assert "production SLA" in joined
    assert "self-optimization" in joined


def test_script_fail_closed_contract():
    text = SCRIPT.read_text(encoding="utf-8")
    assert "required siblings missing" in text
    assert "do not skip" in text
    assert "improved_to_pass" in text
    assert "frozen_baseline" in text
    assert "FIXTURE_RUNS" in text
