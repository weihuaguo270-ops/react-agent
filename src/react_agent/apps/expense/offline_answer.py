"""Offline expense claim decision — policy RAG + rule engine (no LLM)."""
from __future__ import annotations

import json
import re
from typing import Any

from react_agent.apps.expense import LIMITS_DEFAULT

from .contracts import PolicyContractError, load_policy_facts, limits_from_policy, validate_claim
from .domain import ContractError, LegacyClaimAdapter

def _load_limits(profile: str | None = None) -> dict[str, float]:
    """Compatibility helper for the business evaluator."""
    return limits_from_policy(load_policy_facts(profile=profile))


def decide(claim: dict[str, Any], limits: dict[str, float]) -> str:
    """按收据、额度和预批状态返回稳定决策码。"""
    receipt_exception_approved = bool(
        claim.get("missing_receipt_affidavit") and claim.get("manager_approved_missing_receipt")
    )
    if not claim.get("has_receipt") and not receipt_exception_approved:
        return "reject_no_receipt"
    cat = str(claim.get("category") or "")
    amount = float(claim.get("amount") or 0)
    limit = float(limits.get(cat, 0))
    if limit and amount > limit and not claim.get("pre_approved"):
        return "reject_over_limit"
    if cat in {"meal", "餐饮"} and limit and amount > limit and claim.get("pre_approved"):
        return "approve_director"
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
        if "元" in m.group(0):
            claim["currency"] = "CNY"
    elif re.search(r"\bUSD\b|\$", msg, re.IGNORECASE):
        claim["currency"] = "USD"
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
    formal = bool(claim.get("claim_id") or claim.get("claim_version") or claim.get("occurred_on"))
    policy_profile = body.get("policy_profile") or claim.get("policy_profile")
    try:
        policy = load_policy_facts(profile=policy_profile)
        if not formal:
            # Normalize the compatibility envelope without inventing claim identity.
            # The following validation preserves the legacy review/error response shape.
            try:
                claim = LegacyClaimAdapter.normalize(claim, policy=policy).to_dict()
            except ContractError:
                pass
        if not formal and not claim.get("currency"):
            claim["currency"] = policy["currency"]
        validation = validate_claim(claim, formal=formal, policy=policy)
    except PolicyContractError as exc:
        error_code = "policy_profile_unavailable" if policy_profile else "policy_unavailable"
        return {
            "ok": False,
            "answer": "当前政策配置不可用，无法作出决策。",
            "refused": True,
            "error_code": error_code,
            "errors": [str(exc)],
            "claim": claim,
            "policy_profile": policy_profile or "project_simulation_v1",
            "app": "expense",
            "mode": "offline",
        }
    if not validation["valid"]:
        return {
            "ok": False,
            "answer": "Claim 字段不完整或不合法。",
            "refused": True,
            "error_code": validation["error_code"],
            "errors": validation["errors"],
            "claim": claim,
            "policy_profile": policy["selected_profile"],
            "policy_version": policy["policy_version"],
            "app": "expense",
            "mode": "offline",
        }
    claim = validation["claim"]
    if validation["review_required"]:
        reason = "; ".join(validation["errors"]) or "模拟规则要求复核"
        return {
            "ok": True,
            "answer": f"需要人工审核：{reason}",
            "refused": False,
            "decision": "needs_review",
            "error_code": "needs_review",
            "claim": claim,
            "policy_profile": policy["selected_profile"],
            "policy_version": policy["policy_version"],
            "review_required": True,
            "app": "expense",
            "mode": "offline",
        }
    if validation.get("policy_decision"):
        code = validation["policy_decision"]
        return {
            "ok": True,
            "answer": _DECISION_ZH.get(code, code),
            "refused": True,
            "decision": code,
            "error_code": code,
            "claim": claim,
            "policy_profile": policy["selected_profile"],
            "policy_version": policy["policy_version"],
            "app": "expense",
            "mode": "offline",
        }
    limits = limits_from_policy(policy)
    code = decide(claim, limits)
    answer = (
        f"{_DECISION_ZH.get(code, code)}\n"
        f"决策码: {code}\n"
        f"类目: {claim.get('category')} · 金额: {claim.get('amount')}\n"
        f"依据: {policy['selected_profile']} · {policy['policy_version']}"
    )
    return {
        "ok": True,
        "answer": answer,
        "refused": code.startswith("reject"),
        "decision": code,
        "claim": claim,
        "policy_profile": policy["selected_profile"],
        "policy_version": policy["policy_version"],
        "citations": [{"source": "expense_policy_v2.json", "policy_version": policy["policy_version"]}],
        "app": "expense",
        "mode": "offline",
    }
