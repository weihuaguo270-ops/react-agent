"""Deterministic Expense decision Workflow (S3 vertical slice).

The Workflow owns orchestration and audit semantics while ``decide`` remains
the legacy rule function.  External purchase/quote facts are supplied through
an explicit simulation adapter; client-supplied verification flags are never
trusted directly by this path.
"""
from __future__ import annotations

import copy
import hashlib
import json
import threading
from typing import Any, Mapping

from react_agent.workflow.engine import Step, StepKind, WorkflowDef

from .contracts import PolicyContractError, limits_from_policy, load_policy_facts, validate_claim
from .domain import ContractError, LegacyClaimAdapter
from .offline_answer import _DECISION_ZH, decide

EXPENSE_WORKFLOW_NAME = "expense_claim_review@1"
DEFAULT_PURCHASE_ORDERS = {"PO-100": True, "PO-2026": True}

_AUDIT_LOCK = threading.Lock()
_DECISION_AUDIT: dict[str, dict[str, Any]] = {}


class SimulationEvidenceAdapter:
    """Versioned in-process evidence source used by the S3 Workflow.

    The adapter owns the simulated facts. Claim fields and HTTP payloads cannot
    mark a purchase order or quote as verified.
    """

    def __init__(
        self,
        *,
        purchase_orders: Mapping[str, bool] | None = None,
        market_prices: Mapping[str, float] | None = None,
        version: str = "expense-evidence-sim-v1",
    ) -> None:
        self.version = version
        self.purchase_orders = dict(DEFAULT_PURCHASE_ORDERS if purchase_orders is None else purchase_orders)
        self.market_prices = dict(market_prices or {})

    def verify_purchase_order(self, purchase_order_id: str) -> bool | None:
        return self.purchase_orders.get(str(purchase_order_id))

    def market_price(self, key: str) -> float | None:
        return self.market_prices.get(str(key))


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _claim_key(claim: Mapping[str, Any]) -> str:
    claim_id = str(claim.get("claim_id") or "legacy")
    version = claim.get("claim_version", claim.get("version", "1"))
    return f"{claim_id}:v{version}:decision"


def _set_failure(state: dict[str, Any], *, step: str, code: str, message: str) -> None:
    state.update(
        {
            "failed_step": step,
            "error_code": code,
            "error": message,
            "answer": message,
            "refused": True,
        }
    )


def _ingest_claim(state: dict[str, Any], **_: Any) -> dict[str, Any]:
    raw = state.get("claim")
    if not isinstance(raw, Mapping):
        return {
            "claim_valid": False,
            "error_code": "invalid_claim",
            "errors": ["claim must be an object"],
            "answer": "Claim 字段不完整或不合法。",
            "refused": True,
        }
    claim = copy.deepcopy(dict(raw))
    formal = bool(claim.get("claim_id") or claim.get("claim_version") or claim.get("occurred_on"))
    return {"claim": claim, "claim_valid": True, "formal": formal}


def _apply_adapter_facts(claim: dict[str, Any], adapter: SimulationEvidenceAdapter | None) -> tuple[dict[str, Any], dict[str, Any]]:
    """Apply adapter-owned facts, never client verification flags."""
    normalized = dict(claim)
    category = str(normalized.get("category") or "")
    evidence = adapter or SimulationEvidenceAdapter()
    adapter_result: dict[str, Any] = {"status": "not_required", "version": evidence.version}

    if category in {"office_purchase", "办公采购"}:
        normalized.pop("purchase_order_verified", None)
        verified = evidence.verify_purchase_order(str(normalized.get("purchase_order_id") or ""))
        if verified is not None:
            normalized["purchase_order_verified"] = bool(verified)
            adapter_result = {"status": "verified" if verified else "unverified", "source": "simulated_registry", "version": evidence.version}
        else:
            adapter_result = {"status": "unavailable", "source": "simulated_registry", "version": evidence.version}
    elif category in {"transport", "交通"} and normalized.get("transport_mode") == "flight":
        normalized.pop("market_price", None)
        price = evidence.market_price(str(normalized.get("claim_id") or ""))
        if price is not None:
            normalized["market_price"] = price
            adapter_result = {"status": "verified", "source": "simulated_quote", "version": evidence.version}
        else:
            adapter_result = {"status": "unavailable", "source": "simulated_quote", "version": evidence.version}
    elif category in {"lodging", "住宿"}:
        normalized.pop("market_price_per_night", None)
        price = evidence.market_price(str(normalized.get("claim_id") or ""))
        if price is not None:
            normalized["market_price_per_night"] = price
            adapter_result = {"status": "verified", "source": "simulated_quote", "version": evidence.version}
        else:
            adapter_result = {"status": "unavailable", "source": "simulated_quote", "version": evidence.version}
    return normalized, adapter_result


def _load_policy(state: dict[str, Any], **_: Any) -> dict[str, Any]:
    try:
        policy = load_policy_facts(profile=state.get("policy_profile"))
    except PolicyContractError as exc:
        code = "policy_profile_unavailable" if state.get("policy_profile") else "policy_unavailable"
        _set_failure(state, step="load_policy_facts", code=code, message="当前政策配置不可用，无法作出决策。")
        state["claim_valid"] = False
        state["errors"] = [str(exc)]
        raise RuntimeError("policy fixture unavailable") from exc
    claim, adapter = _apply_adapter_facts(state["claim"], state.get("evidence_adapter"))
    return {"policy_facts": policy, "claim": claim, "external_adapter": adapter}


def _decide(state: dict[str, Any], **_: Any) -> dict[str, Any]:
    claim = dict(state.get("claim") or {})
    policy = state["policy_facts"]
    formal = bool(state.get("formal"))
    try:
        if not formal:
            claim = LegacyClaimAdapter.normalize(claim, policy=policy).to_dict()
        validation = validate_claim(claim, formal=formal, policy=policy)
    except (ContractError, PolicyContractError, ValueError) as exc:
        return {
            "claim_valid": False,
            "error_code": "invalid_claim",
            "errors": [str(exc)],
            "answer": "Claim 字段不完整或不合法。",
            "refused": True,
        }

    if not validation["valid"]:
        code = validation.get("error_code") or "invalid_claim"
        return {
            "claim": validation.get("claim") or claim,
            "claim_valid": False,
            "error_code": code,
            "errors": validation.get("errors") or [],
            "answer": "Claim 字段不完整或不合法。",
            "refused": True,
        }

    normalized = validation["claim"]
    review_required = bool(validation.get("review_required"))
    if validation.get("policy_decision"):
        code = str(validation["policy_decision"])
        reasons = list(validation.get("errors") or [])
    elif review_required:
        code = "needs_review"
        reasons = list(validation.get("errors") or [])
    else:
        limits = limits_from_policy(policy)
        if policy["categories"].get(normalized["category"], {}).get("limit_basis") == "per_night":
            limits[normalized["category"]] = float("inf")
        code = decide(normalized, limits)
        reasons = ["rule_matched"]

    allowed = {
        "approve_manager", "approve_finance", "approve_director", "reject_no_receipt",
        "reject_over_limit", "reject_missing_purchase_order", "reject_policy", "needs_review",
    }
    if code not in allowed:
        _set_failure(state, step="decide", code="invalid_decision", message=f"unknown decision code: {code}")
        raise RuntimeError(f"unknown decision code: {code}")
    decision = {
        "decision": code,
        "reasons": reasons,
        "decision_source": "rules",
        "decision_model": "expense-rules-v1",
        "rule_result": "rejected" if code.startswith("reject") else ("not_covered" if code == "needs_review" else "matched"),
        "review_required": review_required or code == "needs_review",
        "risk_score": 0.0,
        "exception_suggested": False,
        "handoff": None,
        "policy_refs": [f"expense_policy_v2.json#{policy['policy_version']}"],
    }
    return {
        "claim": normalized,
        "claim_valid": True,
        "decision": decision,
        "decision_code": code,
        "decision_ready": True,
        "error_code": "needs_review" if code == "needs_review" else (code if code.startswith("reject") else ""),
        "refused": code.startswith("reject"),
    }


def _persist_decision(state: dict[str, Any], **_: Any) -> dict[str, Any]:
    claim = dict(state["claim"])
    key = str(state.get("idempotency_key") or _claim_key(claim))
    decision = dict(state["decision"])
    fingerprint = hashlib.sha256(_canonical({"claim": claim, "decision": decision}).encode("utf-8")).hexdigest()
    with _AUDIT_LOCK:
        existing = _DECISION_AUDIT.get(key)
        if existing is not None:
            if existing["fingerprint"] != fingerprint:
                _set_failure(state, step="persist_decision", code="idempotency_conflict", message="idempotency key conflicts with an existing decision")
                raise RuntimeError("idempotency key conflict")
            replay = copy.deepcopy(existing["result"])
            replay["idempotent_replay"] = True
            return {"decision_audit": replay, "idempotent_replay": True}
        result = {
            "claim_id": str(claim.get("claim_id") or "legacy"),
            "decision": decision["decision"],
            "idempotency_key": key,
            "policy_version": state["policy_facts"]["policy_version"],
            "idempotent_replay": False,
        }
        _DECISION_AUDIT[key] = {"fingerprint": fingerprint, "result": copy.deepcopy(result)}
    return {"decision_audit": result, "idempotency_key": key, "idempotent_replay": False}


def _finalize(state: dict[str, Any], **_: Any) -> dict[str, Any]:
    if not state.get("claim_valid", True):
        return {"answer": state.get("answer") or "Claim 字段不完整或不合法。", "done": True}
    decision = dict(state.get("decision") or {})
    code = str(decision.get("decision") or "")
    claim = state.get("claim") or {}
    answer = _DECISION_ZH.get(code, code)
    if code:
        answer = f"{answer}\n决策码: {code}\n类目: {claim.get('category')} · 金额: {claim.get('amount')}"
    return {
        "answer": answer,
        "refused": code.startswith("reject"),
        "citations": [{"source": "expense_policy_v2.json", "policy_version": state["policy_facts"]["policy_version"]}],
        "done": True,
    }


def build_expense_workflow() -> WorkflowDef:
    return WorkflowDef(
        name=EXPENSE_WORKFLOW_NAME,
        version="1",
        description="Expense policy decision Workflow with auditable validation, rules and idempotent decision audit",
        handlers={
            "ingest_claim": _ingest_claim,
            "load_policy_facts": _load_policy,
            "decide": _decide,
            "persist_decision": _persist_decision,
            "finalize": _finalize,
        },
        steps=[
            Step(id="ingest_claim", kind=StepKind.POLICY, handler="ingest_claim", description="parse structured claim"),
            Step(id="load_policy_facts", kind=StepKind.POLICY, handler="load_policy_facts", depends_on=["ingest_claim"], when="$claim_valid", description="load versioned policy and trusted adapter facts"),
            Step(id="decide", kind=StepKind.POLICY, handler="decide", depends_on=["load_policy_facts"], when="$policy_facts", description="validate claim and apply deterministic rules"),
            Step(id="persist_decision", kind=StepKind.POLICY, handler="persist_decision", depends_on=["decide"], when="$decision_ready", description="append or replay decision audit"),
            Step(id="finalize", kind=StepKind.FINAL, handler="finalize", depends_on=["persist_decision"], description="render workflow result"),
        ],
    )


def run_expense_workflow(initial_state: Mapping[str, Any] | None = None) -> Any:
    """Run the registered Expense workflow without importing generic tools."""
    from react_agent.workflow.registry import run_workflow

    return run_workflow(EXPENSE_WORKFLOW_NAME, dict(initial_state or {}))


def reset_decision_audit() -> None:
    """Clear the process-local S3 audit adapter for isolated tests."""
    with _AUDIT_LOCK:
        _DECISION_AUDIT.clear()


__all__ = [
    "EXPENSE_WORKFLOW_NAME", "SimulationEvidenceAdapter", "build_expense_workflow",
    "reset_decision_audit", "run_expense_workflow",
]
