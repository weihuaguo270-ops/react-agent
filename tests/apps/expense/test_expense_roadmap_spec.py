from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
ROADMAP = ROOT / "docs" / "spec" / "EXPENSE_IMPLEMENTATION_ROADMAP_SPEC.md"


def test_expense_roadmap_defines_all_cross_spec_stages_and_sources():
    text = ROADMAP.read_text(encoding="utf-8")
    for stage in range(9):
        assert f"S{stage}：" in text
    for source in (
        "EXPENSE_POLICY_BOUNDARY_SPEC.md",
        "EXPENSE_WORKFLOW_DECISION_SPEC.md",
        "EXPENSE_FORM_WORKFLOW_SPEC.md",
        "EXPENSE_HUMAN_HANDOFF_SPEC.md",
    ):
        assert source in text
    assert "不是任一单独 SPEC 的内部批次编号" in text


def test_roadmap_preserves_approval_handoff_and_held_out_dependencies():
    text = ROADMAP.read_text(encoding="utf-8")
    assert "S5：审批闭环" in text and "S4" in text
    assert "S6：人工接管" in text and "工单关闭不等于 Claim 批准" in text
    assert "S8 的 held_out 是冻结后的验收数据，不用于调参" in text
    assert "S3：决策 Workflow" in text
    assert "采购验证 known gap" in text
