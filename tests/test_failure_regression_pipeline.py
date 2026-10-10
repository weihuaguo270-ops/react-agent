"""P0 failure-regression pipeline requires trace-debugger + llm-eval-engine."""
from __future__ import annotations

import json
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "eval" / "failure" / "run_failure_regression_pipeline.py"
OUT_ROOT = ROOT / "artifacts" / "failure-regression" / "pytest-runs"

pytest.importorskip("trace_debugger")
pytest.importorskip("eval_engine")


def _out_dir(name: str) -> Path:
    path = OUT_ROOT / f"{name}-{uuid.uuid4().hex[:8]}"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _run(args: list[str], out: Path) -> dict:
    cmd = [
        sys.executable,
        str(SCRIPT),
        "--out",
        str(out),
        *args,
    ]
    proc = subprocess.run(
        cmd,
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    report_path = out / "pipeline_report.json"
    assert report_path.is_file(), proc.stdout + "\n" + proc.stderr
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert proc.returncode == 0, (
        f"exit={proc.returncode}\nstdout:\n{proc.stdout}\nstderr:\n{proc.stderr}\n"
        f"report={json.dumps(report, ensure_ascii=False)}"
    )
    return report


def test_pipeline_pass_mode():
    out = _out_dir("pass")
    report = _run(["--mode", "pass", "--expect-decision", "pass"], out)
    assert report["release_decision"] == "pass"
    assert report["failure_gate_decision"] == "pass"
    assert (out / "failures.json").is_file()
    assert (out / "release.json").is_file()
    assert (out / "findings.json").is_file()
    assert (out / "repair_feedback.json").is_file()
    assert report["repair_feedback"]["schema_version"] == "repair-feedback/v1"


def test_pipeline_hold_mode():
    out = _out_dir("hold")
    report = _run(["--mode", "hold", "--expect-decision", "hold"], out)
    assert report["release_decision"] == "hold"
    assert (out / "failures.json").is_file()
    assert report["repair_feedback"]["actionable"] is True
    assert report["repair_feedback"]["planner_safe"]["hard_failures"]


def test_pipeline_frozen_baseline_compare_green_and_red():
    green = _out_dir("baseline-green")
    green_report = _run(["--mode", "pass", "--expect-decision", "pass"], green)
    baseline = Path(green_report["artifacts"]["baseline_scan"])
    assert baseline.is_file()

    same = _out_dir("compare-green")
    same_report = _run(
        [
            "--mode",
            "pass",
            "--expect-decision",
            "pass",
            "--baseline-scan",
            str(baseline),
        ],
        same,
    )
    assert same_report["baseline_source"] == "provided"
    assert same_report["release_decision"] == "pass"
    assert same_report["failure_gate_decision"] == "pass"

    red = _out_dir("compare-red")
    red_report = _run(
        [
            "--mode",
            "hold",
            "--expect-decision",
            "hold",
            "--baseline-scan",
            str(baseline),
        ],
        red,
    )
    assert red_report["baseline_source"] == "provided"
    assert red_report["release_decision"] == "hold"
    assert red_report["repair_feedback"]["actionable"] is True


def test_pipeline_reverify_linkage():
    parent = _out_dir("parent-hold")
    child = _out_dir("child-pass")
    _run(["--mode", "hold", "--expect-decision", "hold"], parent)
    report = _run(
        [
            "--mode",
            "pass",
            "--expect-decision",
            "pass",
            "--reverify-from",
            str(parent),
        ],
        child,
    )
    assert report["reverify"]["parent_release_decision"] == "hold"
    assert report["reverify"]["improved_to_pass"] is True
    assert report["reverify"]["required"] is True


def test_pipeline_source_fail_closed_contract():
    text = SCRIPT.read_text(encoding="utf-8")
    assert "required siblings missing" in text
    assert "do not skip" in text
    assert "_require_siblings" in text
