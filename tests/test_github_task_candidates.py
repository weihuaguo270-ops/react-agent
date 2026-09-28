from __future__ import annotations

import json

from scripts.export_github_task_candidates import export_candidates


def test_github_metadata_exports_review_queue_not_executable_task(tmp_path):
    snapshot = tmp_path / "snapshot.json"
    snapshot.write_text(json.dumps({
        "dataset": {"repositories": ["acme/widgets"]},
        "cases": [{
            "case_id": "github::acme/widgets::identity",
            "repository": "acme/widgets",
            "split": "golden",
            "source_url": "https://github.com/acme/widgets",
        }],
    }), encoding="utf-8")
    output = tmp_path / "queue.json"
    assert export_candidates(snapshot, output) == 1
    queue = json.loads(output.read_text(encoding="utf-8"))
    assert queue["disposition"] == "review_queue_only"
    assert queue["candidates"][0]["status"] == "needs_manual_issue_review"
    assert "base_commit" in queue["candidates"][0]["missing"]
