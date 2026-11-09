from __future__ import annotations

import json
from pathlib import Path


def test_expense_demo_persists_and_replays_auditable_trajectory():
    from demos.demo_expense_workflow import _review_claim, run_claim

    claim = _review_claim()
    trajectory_dir = Path("artifacts/expense/test_demo_trajectory")
    trajectory_dir.mkdir(parents=True, exist_ok=True)
    result, trajectory_path, replayed = run_claim(
        claim, label="test", trajectory_dir=trajectory_dir
    )

    assert result.ok is True
    assert result.state["decision_code"] == "needs_review"
    assert result.state["decision"]["review_required"] is True
    assert trajectory_path.is_file()

    trajectory = json.loads(trajectory_path.read_text(encoding="utf-8"))
    assert trajectory["query"] == "报销办理：DEMO-REVIEW-001"
    assert trajectory["final_answer"] == result.answer
    assert trajectory["metadata"]["approval_event"] == "human_review_required"
    assert trajectory["metadata"]["business_terminal_state"] == "awaiting_human_review"
    assert replayed["final_answer"] == trajectory["final_answer"]
