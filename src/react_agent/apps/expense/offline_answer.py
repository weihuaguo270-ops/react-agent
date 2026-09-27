"""Offline expense claim decision — policy RAG + rule engine (no LLM)."""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

from react_agent.apps.expense import LIMITS_DEFAULT

_REPO = Path(__file__).resolve().parents[4]
_FIXTURE = _REPO / "fixtures" / "business" / "expense_claims.json"
_POLICY = _REPO / "fixtures" / "rag_corpus" / "expense_policy.md"


def _load_limits() -> dict[str, float]:
    if _FIXTURE.is_file():
        data = json.loads(_FIXTURE.read_text(encoding="utf-8"))
        return {k: float(v) for k, v in (data.get("limits") or LIMITS_DEFAULT).items()}
    return {k: float(v) for k, v in LIMITS_DEFAULT.items()}


def decide(claim: dict[str, Any], limits: dict[str, float]) -> str:
    """按收据、额度和预批状态返回稳定决策码。"""
    if not claim.get("has_receipt"):
        return "reject_no_receipt"
    cat = str(claim.get("category") or "")
    amount = float(claim.get("amount") or 0)
    limit = float(limits.get(cat, 0))
    if limit and amount > limit and not claim.get("pre_approved"):
        return "reject_over_limit"
    if amount > 1000:
        return "approve_director"
    if amount > 200:
        return "approve_finance"
    return "approve_manager"


_DECISION_ZH = {
    "reject_no_receipt": "拒批：缺少有效发票/收据。",
    "reject_over_limit": "拒批：超出该类目额度且未事前审批。",
    "approve_director": "通过：需总监审批（金额较高）。",
    "approve_finance": "通过：需财务审批。",
    "approve_manager": "通过：主管审批即可。",
}


def _policy_snippet() -> str:
    os.environ.setdefault("REACT_AGENT_RAG_MODE", "keyword")
    try:
        from react_agent.rag import RAG

        rag = RAG(save_path="")
        rag.clear()
        if _POLICY.is_file():
            rag.ingest(str(_POLICY))
            hits = rag.query("报销 额度 审批", top_k=1)
            if hits:
                return hits[0].get("content", "")[:240]
    except Exception:
        pass
    if _POLICY.is_file():
        return _POLICY.read_text(encoding="utf-8")[:240]
    return ""


def _parse_claim(body: dict[str, Any]) -> dict[str, Any]:
    if isinstance(body.get("claim"), dict):
        return dict(body["claim"])
    msg = str(body.get("message") or body.get("query") or "").strip()
    if msg.startswith("{"):
        try:
            parsed = json.loads(msg)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            pass
    claim: dict[str, Any] = {}
    for cat in LIMITS_DEFAULT:
        if cat in msg:
            claim["category"] = cat
            break
    m = re.search(r"(\d+(?:\.\d+)?)\s*元?", msg)
    if m:
        claim["amount"] = float(m.group(1))
    claim["has_receipt"] = any(k in msg for k in ("有发票", "有收据", "has_receipt"))
    claim["pre_approved"] = any(k in msg for k in ("事前", "预批", "pre_approved"))
    return claim


def answer_offline(body: dict[str, Any]) -> dict[str, Any]:
    """解析费用请求并返回规则决策、引用和拒绝状态。"""
    claim = _parse_claim(body)
    if not claim.get("category") or claim.get("amount") is None:
        return {
            "ok": False,
            "answer": "请提供 claim 对象或包含类目/金额的消息，例如：{\"category\":\"餐饮\",\"amount\":128,\"has_receipt\":true}",
            "refused": True,
            "app": "expense",
        }
    limits = _load_limits()
    code = decide(claim, limits)
    policy = _policy_snippet()
    answer = (
        f"{_DECISION_ZH.get(code, code)}\n"
        f"决策码: {code}\n"
        f"类目: {claim.get('category')} · 金额: {claim.get('amount')}\n"
        f"依据: expense_policy.md"
    )
    if policy:
        answer += f"\n政策摘要: {policy[:180].replace(chr(10), ' ')}..."
    return {
        "ok": True,
        "answer": answer,
        "refused": code.startswith("reject"),
        "decision": code,
        "claim": claim,
        "citations": [{"source": "expense_policy.md"}],
        "app": "expense",
        "mode": "offline",
    }
