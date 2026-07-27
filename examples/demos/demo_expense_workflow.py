"""业务多步 Demo：报销政策检索 + 规则裁决（离线，无 LLM）。

演示 Agent 应用向能力：语料 → 检索 → 结构化规则 → 审批结论。
不是完整 ReAct 循环，而是可口述的「业务落点」骨架。

用法:
  python examples/demos/demo_expense_workflow.py
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

import os

os.environ.setdefault("REACT_AGENT_RAG_MODE", "keyword")

from react_agent.rag import RAG


LIMITS_DEFAULT = {
    "餐饮": 200,
    "交通": 500,
    "住宿": 600,
    "办公采购": 1000,
}


def decide(claim: dict, limits: dict) -> str:
    if not claim.get("has_receipt"):
        return "reject_no_receipt"
    cat = claim.get("category", "")
    amount = float(claim.get("amount", 0))
    limit = float(limits.get(cat, 0))
    if limit and amount > limit and not claim.get("pre_approved"):
        return "reject_over_limit"
    if amount > 1000:
        return "approve_director"
    if amount > 200:
        return "approve_finance"
    return "approve_manager"


def main():
    fixture = json.loads(
        (ROOT / "fixtures" / "business" / "expense_claims.json").read_text(encoding="utf-8")
    )
    limits = fixture.get("limits") or LIMITS_DEFAULT

    # Step 1: 政策语料入索引（模拟 rag_query）
    with tempfile.TemporaryDirectory() as td:
        rag = RAG(save_path=str(Path(td) / "biz.json"))
        rag.clear()
        rag.ingest(str(ROOT / "fixtures" / "rag_corpus" / "expense_policy.md"))
        policy = rag.query("报销 额度 审批", top_k=2)
        print("=== Step1 政策检索 ===")
        for h in policy:
            print(f"  {h['source']}: {h['content'][:100].replace(chr(10), ' ')}...")

    # Step 2–3: 逐单裁决（模拟工具链 / 规则引擎）
    print("\n=== Step2–3 多单裁决 ===")
    ok = 0
    for claim in fixture["claims"]:
        got = decide(claim, limits)
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
    print("口述要点: RAG 取政策 → 结构化字段 → 规则/工具裁决 → 可写轨迹 Format B。")
    print("接 ReAct: 把 decide 换成 tool，由模型填 category/amount/has_receipt。")


if __name__ == "__main__":
    main()
