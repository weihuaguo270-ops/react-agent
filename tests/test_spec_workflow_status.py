from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / ".codex/skills/spec-progress-workflow/scripts/spec_workflow.py"
SPEC = importlib.util.spec_from_file_location("spec_workflow_under_test", SCRIPT)
assert SPEC and SPEC.loader
spec_workflow = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(spec_workflow)


def test_status_snapshot_uses_canonical_report_hash(tmp_path, monkeypatch):
    report_path = tmp_path / "gate.json"
    report_path.write_bytes(b'{"status":"blocked"}\r\n')
    progress_path = tmp_path / "progress.json"
    progress_path.write_text(
        json.dumps(
            {
                "stages": {"Phase 2": {"status": "in_progress"}},
                "last_gate": {"report": str(report_path)},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(spec_workflow, "repo_path", lambda value: Path(value))
    monkeypatch.setattr(spec_workflow, "relative_path", lambda path: path.as_posix())

    snapshot = spec_workflow.status_snapshot(
        {
            "directions": {
                "ci": {
                    "progress_source": str(progress_path),
                    "display_name": "CI",
                }
            }
        },
        "ci",
    )

    expected = hashlib.sha256(b'{"status":"blocked"}\n').hexdigest()
    assert snapshot["report"]["sha256"] == expected
    assert snapshot["report"]["sha256"] == spec_workflow.sha256_file(report_path)
