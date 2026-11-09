"""企业内部工作助手的报销办理闭环 Demo（离线，无 LLM）。

演示现有 ``expense_claim_review@1`` Workflow 的真实路径：政策检索、
结构化表单校验、规则决策、必要时转人工复核、审计记录和轨迹回放。
人工审批的 ``resolve_review`` 后置流程仍属于后续阶段；本 Demo 只展示
Workflow 已经落盘的 ``needs_review`` 闸门，不把它包装成已完成的审批 API。

用法:
  python demos/demo_expense_workflow.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = next(p for p in Path(__file__).resolve().parents if (p / "pyproject.toml").is_file())
sys.path.insert(0, str(ROOT / "src"))

import os

os.environ.setdefault("REACT_AGENT_RAG_MODE", "keyword")
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from react_agent.rag import RAG
from react_agent.apps.expense.workflow import EXPENSE_WORKFLOW_NAME
from react_agent.harness import Replay
from react_agent.workflow import run_workflow


DEMO_TRAJECTORY_DIR = ROOT / "artifacts" / "expense" / "demo_trajectories"


def _review_claim() -> dict[str, object]:
    """Structured claim that deterministically enters the human-review gate."""
    return {
        "claim_id": "DEMO-REVIEW-001",
        "claim_version": 1,
        "category": "meal",
        "amount": 128,
        "currency": "EUR",
        "occurred_on": "2026-10-12",
        "description": "cross-border client meeting",
        "business_purpose": "client meeting",
        "has_receipt": True,
        "receipt_refs": ["receipt-review-1"],
        "pre_approved": False,
        "expense_type": "business_meal",
        "participants": ["employee-1"],
    }


def _terminal_state(result) -> str:
    code = str(result.state.get("decision_code") or result.state.get("error_code") or "unknown")
    if code == "needs_review":
        return "awaiting_human_review"
    if code.startswith("reject"):
        return "rejected"
    if code.startswith("approve"):
        return "approval_routed"
    return code


def run_claim(claim: dict[str, object], *, label: str, trajectory_dir: Path = DEMO_TRAJECTORY_DIR):
    """Run one claim, persist its canonical trajectory, and replay it."""
    query = f"报销办理：{claim.get('claim_id') or claim.get('id')}"
    result = run_workflow(
        EXPENSE_WORKFLOW_NAME,
        {
            "claim": claim,
            "query": query,
            "idempotency_key": f"demo:{claim.get('claim_id') or claim.get('id')}:decision",
        },
    )
    trajectory_dir.mkdir(parents=True, exist_ok=True)
    trajectory_path = trajectory_dir / f"traj_{result.run_id}.json"
    trajectory = result.to_trajectory()
    decision = result.state.get("decision") or {}
    decision_code = result.state.get("decision_code") or result.state.get("error_code")
    trajectory.setdefault("metadata", {}).update(
        {
            "business_terminal_state": _terminal_state(result),
            "decision_code": decision_code,
            "review_required": bool(decision.get("review_required")),
            "approval_event": (
                "human_review_required"
                if decision_code == "needs_review"
                else "no_human_review_gate"
            ),
        }
    )
    trajectory_path.write_text(
        json.dumps(trajectory, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    audit = result.state.get("decision_audit") or {}
    print(f"\n[{label}] 员工提交: {query}")
    print(
        "  表单校验: "
        f"claim_valid={result.state.get('claim_valid')} "
        f"policy={result.state.get('policy_facts', {}).get('policy_version', 'n/a')}"
    )
    print(
        "  决策: "
        f"{result.state.get('decision_code') or result.state.get('error_code')} "
        f"review_required={decision.get('review_required', False)}"
    )
    if result.state.get("decision_code") == "needs_review":
        print("  人工审批边界: 已进入人工复核队列；当前原型不自动批准。")
    print(f"  业务终态（本 Workflow）: {_terminal_state(result)}")
    print(f"  审计记录: {json.dumps(audit, ensure_ascii=False)}")
    print(f"  answer={result.answer}")
    print(f"  trajectory_id={result.run_id} saved={trajectory_path.exists()} path={trajectory_path}")
    print("  replay:")
    replayed = Replay().play(str(trajectory_path))
    return result, trajectory_path, replayed


def main():
    fixture = json.loads(
        (ROOT / "fixtures" / "expense" / "expense_claims.json").read_text(encoding="utf-8")
    )
    # Step 1: 政策语料入索引（模拟 rag_query）
    demo_rag_path = ROOT / "artifacts" / "expense" / "demo_rag.json"
    demo_rag_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        rag = RAG(save_path=str(demo_rag_path))
        rag.clear()
        rag.ingest(str(ROOT / "fixtures" / "expense" / "expense_policy.md"))
        policy = rag.query("报销 额度 审批", top_k=2)
        print("=== Step1 政策检索 ===")
        for h in policy:
            print(f"  {h['source']}: {h['content'][:100].replace(chr(10), ' ')}...")
    finally:
        demo_rag_path.unlink(missing_ok=True)

    # Step 2–4: 逐单调用注册 Workflow（demo 不复制规则实现）
    print("\n=== Step2–4 表单校验、决策与审计 ===")
    ok = 0
    for claim in fixture["claims"]:
        result, _, _ = run_claim(claim, label=claim["id"])
        got = result.state.get("decision_code") or result.state.get("error_code")
        exp = claim["expect"]
        mark = "OK" if got == exp else "DIFF"
        if got == exp:
            ok += 1
        print(f"  fixture check: [{mark}] {claim['id']} -> {got} (expect {exp})")

    run_claim(_review_claim(), label="人工复核")
    print(f"\nfixture 匹配 {ok}/{len(fixture['claims'])}")
    print("口述要点: 政策检索 → 表单校验 → 决策/人工复核闸门 → 审计终态 → 轨迹回放。")


if __name__ == "__main__":
    main()
