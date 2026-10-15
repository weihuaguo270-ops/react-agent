"""业务多步 Demo：报销政策检索 + 规则裁决（离线，无 LLM）。

演示 Agent 应用向能力：语料 → 检索 → 结构化规则 → 审批结论。
不是完整 ReAct 循环，而是可口述的「业务落点」骨架。

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

from react_agent.rag import RAG
from react_agent.apps.expense.workflow import EXPENSE_WORKFLOW_NAME
from react_agent.workflow import run_workflow


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

    # Step 2–3: 逐单调用注册 Workflow（demo 不复制规则实现）
    print("\n=== Step2–3 多单裁决 ===")
    ok = 0
    for claim in fixture["claims"]:
        result = run_workflow(
            EXPENSE_WORKFLOW_NAME,
            {"claim": claim, "idempotency_key": f"demo:{claim['id']}:decision"},
        )
        got = result.state.get("decision_code") or result.state.get("error_code")
        exp = claim["expect"]
        # fixture expect 与简化规则对齐：C-004 有事前申请且 >1000 → director
        mark = "OK" if got == exp else "DIFF"
        if got == exp:
            ok += 1
        print(
            f"  [{mark}] {claim['id']} {claim['category']} CNY {claim['amount']} "
            f"-> {got} (expect {exp}) | {claim['note']}"
        )

    print(f"\n匹配 {ok}/{len(fixture['claims'])}")
    print("口述要点: RAG 取政策 → 结构化字段 → expense_claim_review@1 → 审计轨迹。")


if __name__ == "__main__":
    main()
