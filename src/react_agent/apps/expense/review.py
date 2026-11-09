"""Expense review routing and human resolution for the deployable prototype.

The store is intentionally process-local until the PostgreSQL Expense store is
introduced.  The API and invariants are domain-owned here so the later store
can replace persistence without changing the approval contract.
"""
from __future__ import annotations

import copy
import threading
import uuid
from datetime import datetime, timezone
from typing import Any, Mapping

from react_agent.safety.permission_gate import permission_block_message

from .domain import (
    ApprovalDecision,
    ApprovalRecord,
    AuditEvent,
    Claim,
    ClaimStatus,
    Decision,
    DecisionCode,
    ErrorCode,
    Handoff,
)


class ReviewError(ValueError):
    """Structured domain error returned by the Expense review API."""

    def __init__(self, code: str | ErrorCode, message: str, *, status_code: int = 409, details: Mapping[str, Any] | None = None):
        self.code = str(code)
        self.status_code = status_code
        self.details = dict(details or {})
        super().__init__(message)


_LOCK = threading.RLock()
_REVIEWS: dict[str, dict[str, Any]] = {}
_IDEMPOTENCY: dict[str, tuple[str, str]] = {}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _event(*, claim_id: str, version: int, event_type: str, actor_type: str, actor_id: str, request_id: str, idempotency_key: str, metadata: Mapping[str, Any]) -> dict[str, Any]:
    return AuditEvent(
        event_id="evt_" + uuid.uuid4().hex,
        claim_id=claim_id,
        claim_version=version,
        event_type=event_type,
        actor_type=actor_type,
        actor_id=actor_id,
        request_id=request_id or "expense-review",
        idempotency_key=idempotency_key or "expense-review",
        created_at=_now(),
        metadata=dict(metadata),
    ).to_dict()


def _as_decision(raw: Decision | Mapping[str, Any], claim: Claim) -> Decision:
    if isinstance(raw, Decision):
        decision = raw
    else:
        data = dict(raw)
        data.setdefault("claim_id", claim.claim_id)
        data.setdefault("claim_version", claim.version)
        data.setdefault("policy_version", "expense-policy-sim-v1")
        if data.get("handoff") is None and (
            data.get("review_required")
            or data.get("decision") in {"approve_manager", "approve_finance", "approve_director", "needs_review", "escalated"}
        ):
            data["handoff"] = Handoff(
                reason_code=str((data.get("reasons") or ["manual_review"])[0]),
                risk_level="medium",
                amount_band="0-1000",
            )
        decision = Decision.from_dict(data)
    if decision.claim_id != claim.claim_id or decision.claim_version != claim.version:
        raise ReviewError(ErrorCode.APPROVAL_VERSION_MISMATCH, "decision is not bound to this claim version")
    return decision


def route_review(
    claim: Claim | Mapping[str, Any],
    decision: Decision | Mapping[str, Any],
    *,
    request_id: str = "",
    idempotency_key: str = "",
) -> dict[str, Any]:
    """Route a validated decision without granting human approval."""
    canonical_claim = claim if isinstance(claim, Claim) else Claim.from_dict(claim)
    canonical_decision = _as_decision(decision, canonical_claim)
    code = DecisionCode(canonical_decision.decision)
    idem = idempotency_key or f"review:{canonical_claim.claim_id}:{canonical_claim.version}:{canonical_decision.decision_hash}"
    fingerprint = f"{canonical_claim.claim_id}:{canonical_claim.version}:{canonical_decision.decision_hash}:{code}"
    with _LOCK:
        existing_key = _IDEMPOTENCY.get(idem)
        if existing_key and existing_key[1] != fingerprint:
            raise ReviewError(ErrorCode.IDEMPOTENCY_CONFLICT, "idempotency key conflicts with an existing review route")
        if existing_key:
            return copy.deepcopy(_REVIEWS[existing_key[0]])

        if code in {DecisionCode.REJECT_NO_RECEIPT, DecisionCode.REJECT_OVER_LIMIT, DecisionCode.REJECT_MISSING_PURCHASE_ORDER, DecisionCode.REJECT_POLICY}:
            result = {
                "claim_id": canonical_claim.claim_id,
                "claim_version": canonical_claim.version,
                "status": ClaimStatus.REJECTED.value,
                "approval_id": None,
                "decision": canonical_decision.to_dict(),
                "events": [_event(claim_id=canonical_claim.claim_id, version=canonical_claim.version, event_type="claim_rejected", actor_type="agent", actor_id="expense-router", request_id=request_id, idempotency_key=idem, metadata={"decision_hash": canonical_decision.decision_hash, "decision_code": str(code)})],
            }
        elif canonical_decision.review_required or code in {
            DecisionCode.APPROVE_MANAGER,
            DecisionCode.APPROVE_FINANCE,
            DecisionCode.APPROVE_DIRECTOR,
            DecisionCode.NEEDS_REVIEW,
            DecisionCode.ESCALATED,
        }:
            approval_id = "apr_" + uuid.uuid4().hex
            status = ClaimStatus.ESCALATED.value if code == DecisionCode.ESCALATED else ClaimStatus.UNDER_REVIEW.value
            result = {
                "claim_id": canonical_claim.claim_id,
                "claim_version": canonical_claim.version,
                "status": status,
                "approval_id": approval_id,
                "approval_status": "pending",
                "decision": canonical_decision.to_dict(),
                "events": [_event(claim_id=canonical_claim.claim_id, version=canonical_claim.version, event_type="review_routed", actor_type="agent", actor_id="expense-router", request_id=request_id, idempotency_key=idem, metadata={"approval_id": approval_id, "decision_hash": canonical_decision.decision_hash, "handoff": canonical_decision.handoff.to_dict() if canonical_decision.handoff else None})],
            }
        else:
            # A positive decision is only a recommendation.  The parent form
            # remains submitted until a separate policy-defined side effect.
            result = {
                "claim_id": canonical_claim.claim_id,
                "claim_version": canonical_claim.version,
                "status": ClaimStatus.SUBMITTED.value,
                "approval_id": None,
                "decision": canonical_decision.to_dict(),
                "events": [_event(claim_id=canonical_claim.claim_id, version=canonical_claim.version, event_type="decision_routed", actor_type="agent", actor_id="expense-router", request_id=request_id, idempotency_key=idem, metadata={"decision_hash": canonical_decision.decision_hash})],
            }
        _REVIEWS[result.get("approval_id") or f"route:{idem}"] = copy.deepcopy(result)
        _IDEMPOTENCY[idem] = (result.get("approval_id") or f"route:{idem}", fingerprint)
        return copy.deepcopy(result)


def resolve_review(
    approval_id: str,
    *,
    decision: str | ApprovalDecision,
    approver_id: str,
    claim_id: str,
    expected_version: int,
    decision_hash: str,
    request_id: str = "",
    idempotency_key: str = "",
    comment: str = "",
) -> dict[str, Any]:
    """Apply an authenticated human decision to a pending Expense review."""
    blocked = permission_block_message("resolve_review", {"approval_id": approval_id, "claim_id": claim_id, "decision": str(decision)})
    if blocked:
        raise ReviewError("permission_denied", blocked, status_code=403)
    if not approver_id.strip():
        raise ReviewError("permission_denied", "approver_id is required", status_code=403)
    try:
        action = ApprovalDecision(decision)
    except ValueError as exc:
        raise ReviewError("invalid_decision", "decision must be approve, reject, or escalate") from exc
    idem = idempotency_key or f"approval:{approval_id}:{expected_version}:{action.value}"
    with _LOCK:
        record = _REVIEWS.get(approval_id)
        if record is None or not record.get("approval_id"):
            raise ReviewError(ErrorCode.CLAIM_NOT_FOUND, "expense approval not found", status_code=404)
        if record["claim_id"] != claim_id:
            raise ReviewError(ErrorCode.FORBIDDEN_CLAIM_ACCESS, "approval is not bound to this claim", status_code=403)
        if record["claim_version"] != expected_version:
            raise ReviewError(ErrorCode.APPROVAL_VERSION_MISMATCH, "approval claim version does not match")
        expected_hash = record["decision"].get("decision_hash")
        if decision_hash != expected_hash:
            raise ReviewError(ErrorCode.DECISION_INVALID, "decision_hash does not match the routed decision")
        prior = record.get("resolution")
        if prior:
            if record.get("idempotency_key") == idem and prior.get("decision") == action.value and prior.get("approver_id") == approver_id:
                return copy.deepcopy(record)
            raise ReviewError("approval_not_pending", "expense approval has already been resolved")

        permission_fingerprint = f"{approval_id}:{claim_id}:{expected_version}:{decision_hash}:{action.value}"
        prior_idem = _IDEMPOTENCY.get(idem)
        if prior_idem and prior_idem[1] != permission_fingerprint:
            raise ReviewError(ErrorCode.IDEMPOTENCY_CONFLICT, "idempotency key conflicts with an existing resolution")
        status = {ApprovalDecision.APPROVE: ClaimStatus.APPROVED.value, ApprovalDecision.REJECT: ClaimStatus.REJECTED.value, ApprovalDecision.ESCALATE: ClaimStatus.ESCALATED.value}[action]
        approval = ApprovalRecord(approval_id=approval_id, claim_id=claim_id, claim_version=expected_version, decision_hash=decision_hash, decision=action, approver_id=approver_id, created_at=_now(), comment=comment).to_dict()
        record["status"] = status
        record["approval_status"] = "resolved"
        record["resolution"] = approval
        record["idempotency_key"] = idem
        record["events"].append(_event(claim_id=claim_id, version=expected_version, event_type="review_resolved", actor_type="manager", actor_id=approver_id, request_id=request_id, idempotency_key=idem, metadata={"approval_id": approval_id, "decision": action.value, "decision_hash": decision_hash, "comment": comment}))
        _IDEMPOTENCY[idem] = (approval_id, permission_fingerprint)
        return copy.deepcopy(record)


def list_reviews() -> list[dict[str, Any]]:
    with _LOCK:
        return [copy.deepcopy(item) for item in _REVIEWS.values() if item.get("approval_id")]


def reset_reviews() -> None:
    with _LOCK:
        _REVIEWS.clear()
        _IDEMPOTENCY.clear()


__all__ = ["ReviewError", "list_reviews", "reset_reviews", "resolve_review", "route_review"]
