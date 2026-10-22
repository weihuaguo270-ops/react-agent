from __future__ import annotations

import json
import sys
from pathlib import Path

SPEC_SKILL_SCRIPTS = Path(__file__).parents[1] / ".codex/skills/spec-progress-workflow/scripts"
sys.path.insert(0, str(SPEC_SKILL_SCRIPTS))
import spec_workflow


def _make_direction(tmp_path: Path, monkeypatch, *, child_status: str = "Complete"):
    monkeypatch.setattr(spec_workflow, "ROOT", tmp_path)
    monkeypatch.setattr(spec_workflow, "validate_registry", lambda _registry: [])
    (tmp_path / "docs/specs").mkdir(parents=True)
    (tmp_path / "docs/specs/goals").mkdir()
    (tmp_path / "docs/specs/main.md").write_text(
        "| Phase 0 baseline | Complete | frozen |\n", encoding="utf-8"
    )
    (tmp_path / "docs/specs/child.md").write_text(
        f"| Phase 0 baseline | {child_status} | details |\n", encoding="utf-8"
    )
    (tmp_path / "docs/specs/goals/work.md").write_text("# Goal\n", encoding="utf-8")
    (tmp_path / "gate-report.json").write_text("{}\n", encoding="utf-8")
    (tmp_path / "evidence.json").write_text("{}\n", encoding="utf-8")
    progress = {
        "source_spec": "docs/specs/main.md",
        "stages": {
            "P0": {
                "name": "baseline",
                "status": "complete",
                "gate_command": "python gate.py",
                "acceptance": [
                    {
                        "id": "P0-1",
                        "status": "complete",
                        "evidence": ["evidence.json"],
                    }
                ],
                "last_gate": {"status": "passed", "report": "gate-report.json"},
            }
        },
    }
    (tmp_path / "progress.json").write_text(json.dumps(progress), encoding="utf-8")
    entry = {
        "display_name": "Work",
        "goal": "docs/specs/goals/work.md",
        "progress_source": "progress.json",
        "source_spec": "docs/specs/main.md",
        "specs": ["docs/specs/main.md", "docs/specs/child.md"],
        "gate": {},
    }
    return {"directions": {"work": entry}}


def test_analyze_passes_when_registered_specs_and_progress_agree(tmp_path, monkeypatch):
    registry = _make_direction(tmp_path, monkeypatch)

    result = spec_workflow.analyze_direction(registry, "work")

    assert result["status"] == "pass"
    assert result["findings"] == []


def test_analyze_fails_when_registered_specs_disagree_on_phase(tmp_path, monkeypatch):
    registry = _make_direction(tmp_path, monkeypatch, child_status="Partial")

    result = spec_workflow.analyze_direction(registry, "work")

    assert result["status"] == "fail"
    assert any(item["code"] == "cross-spec-phase-status-conflict" for item in result["findings"])


def test_analyze_fails_when_complete_stage_has_pending_acceptance(tmp_path, monkeypatch):
    registry = _make_direction(tmp_path, monkeypatch)
    progress_path = tmp_path / "progress.json"
    progress = json.loads(progress_path.read_text(encoding="utf-8"))
    progress["stages"]["P0"]["acceptance"][0]["status"] = "in_progress"
    progress_path.write_text(json.dumps(progress), encoding="utf-8")

    result = spec_workflow.analyze_direction(registry, "work")

    assert result["status"] == "fail"
    assert any(item["code"] == "complete-stage-pending-acceptance" for item in result["findings"])


def test_analyze_reports_missing_historical_evidence_for_review(tmp_path, monkeypatch):
    registry = _make_direction(tmp_path, monkeypatch)
    progress_path = tmp_path / "progress.json"
    progress = json.loads(progress_path.read_text(encoding="utf-8"))
    progress["stages"]["P0"]["acceptance"][0]["evidence"] = ["missing.json"]
    progress_path.write_text(json.dumps(progress), encoding="utf-8")

    result = spec_workflow.analyze_direction(registry, "work")

    assert result["status"] == "pass"
    assert any(item["code"] == "missing-acceptance-evidence" for item in result["findings"])
