"""Shared domain contracts for the Expense decision and review workflow."""
from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, field
from datetime import date, datetime
try:
    from enum import StrEnum
except ImportError:  # Python 3.10 compatibility
    from enum import Enum

    class StrEnum(str, Enum):
        """Compatibility fallback for Python versions before 3.11."""

from typing import Any, Mapping

from .contracts import load_policy_facts, normalize_category, validate_claim


class ContractError(ValueError):
    """Raised when an Expense domain object violates its contract."""


class ErrorCode(StrEnum):
    INVALID_CLAIM = "invalid_claim"
    CLAIM_NOT_EDITABLE = "claim_not_editable"
    INVALID_STATE_TRANSITION = "invalid_state_transition"
    POLICY_UNAVAILABLE = "policy_unavailable"
    POLICY_PROFILE_UNAVAILABLE = "policy_profile_unavailable"
    REVIEW_REQUIRED = "review_required"
    APPROVAL_EXPIRED = "approval_expired"
    APPROVAL_VERSION_MISMATCH = "approval_version_mismatch"
    IDEMPOTENCY_CONFLICT = "idempotency_conflict"
    FORBIDDEN_CLAIM_ACCESS = "forbidden_claim_access"
    EXTERNAL_WRITE_NOT_SUPPORTED = "external_write_not_supported"
    CLAIM_NOT_FOUND = "claim_not_found"
    DECISION_INVALID = "decision_invalid"
    POLICY_NOT_COVERED = "policy_not_covered"


class DecisionCode(StrEnum):
    APPROVE_MANAGER = "approve_manager"
    APPROVE_FINANCE = "approve_finance"
    APPROVE_DIRECTOR = "approve_director"
    REJECT_NO_RECEIPT = "reject_no_receipt"
    REJECT_OVER_LIMIT = "reject_over_limit"
    REJECT_MISSING_PURCHASE_ORDER = "reject_missing_purchase_order"
    REJECT_POLICY = "reject_policy"
    NEEDS_REVIEW = "needs_review"
    ESCALATED = "escalated"


class ApprovalDecision(StrEnum):
    APPROVE = "approve"
    REJECT = "reject"
    ESCALATE = "escalate"


class ClaimStatus(StrEnum):
    DRAFT = "draft"
    SUBMITTED = "submitted"
    VALIDATING = "validating"
    NEEDS_CORRECTION = "needs_correction"
    UNDER_REVIEW = "under_review"
    APPROVED = "approved"
    REJECTED = "rejected"
    ESCALATED = "escalated"
    CANCELLED = "cancelled"


_CATEGORIES = {"meal", "transport", "lodging", "office_purchase"}
_DECISION_SOURCES = {"rules", "specialized_model", "human_review"}
_RULE_RESULTS = {"matched", "rejected", "not_covered"}
_ACTOR_TYPES = {"applicant", "agent", "manager", "finance", "director", "system"}


def _require_text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ContractError(f"{name} is required")
    return value.strip()


def _canonical_json(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


@dataclass(frozen=True)
class Claim:
    """Versioned form Claim; legacy inputs must use ``LegacyClaimAdapter``."""

    claim_id: str
    version: int
    category: str
    amount: float
    currency: str
    occurred_on: str
    description: str
    has_receipt: bool
    receipt_refs: tuple[str, ...] = ()
    pre_approved: bool = False
    applicant_id: str | None = None
    merchant: str | None = None
    business_purpose: str | None = None
    status: str = "draft"
    idempotency_key: str | None = None
    attributes: Mapping[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any], *, policy: dict[str, Any] | None = None) -> "Claim":
        if not isinstance(raw, Mapping):
            raise ContractError("claim must be an object")
        claim_id = _require_text(raw.get("claim_id"), "claim_id")
        version = raw.get("version", raw.get("claim_version"))
        if isinstance(version, bool) or not isinstance(version, int) or version < 1:
            raise ContractError("version must be a positive integer")
        category = normalize_category(raw.get("category"), policy)
        if category not in _CATEGORIES:
            raise ContractError("category is missing or unknown")
        amount = raw.get("amount")
        if isinstance(amount, bool) or not isinstance(amount, (int, float)) or not math.isfinite(float(amount)) or amount < 0:
            raise ContractError("amount must be finite and non-negative")
        currency = _require_text(raw.get("currency"), "currency").upper()
        occurred_on = _require_text(raw.get("occurred_on"), "occurred_on")
        try:
            date.fromisoformat(occurred_on)
        except ValueError as exc:
            raise ContractError("occurred_on must be an ISO date") from exc
        description = _require_text(raw.get("description"), "description")
        if not isinstance(raw.get("has_receipt"), bool):
            raise ContractError("has_receipt must be boolean")
        if not isinstance(raw.get("pre_approved", False), bool):
            raise ContractError("pre_approved must be boolean")
        status = str(raw.get("status", ClaimStatus.DRAFT))
        if status not in {item.value for item in ClaimStatus}:
            raise ContractError("status is unknown")
        refs = raw.get("receipt_refs", ())
        if not isinstance(refs, (list, tuple)) or any(not isinstance(item, str) or not item.strip() for item in refs):
            raise ContractError("receipt_refs must be an array of non-empty strings")
        values = dict(raw)
        values["category"] = category
        values["claim_version"] = version
        values.setdefault("pre_approved", False)
        values.setdefault("business_purpose", raw.get("business_purpose") or description)
        values.setdefault("receipt_refs", list(refs))
        validation = validate_claim(values, formal=True, policy=policy or load_policy_facts())
        if not validation["valid"]:
            raise ContractError("; ".join(validation["errors"]))
        known = {
            "claim_id", "version", "claim_version", "category", "amount", "currency", "occurred_on",
            "description", "has_receipt", "receipt_refs", "pre_approved", "applicant_id", "merchant",
            "business_purpose", "status", "idempotency_key",
        }
        return cls(
            claim_id=claim_id,
            version=version,
            category=category,
            amount=float(amount),
            currency=currency,
            occurred_on=occurred_on,
            description=description,
            has_receipt=raw["has_receipt"],
            receipt_refs=tuple(refs),
            pre_approved=raw.get("pre_approved", False),
            applicant_id=raw.get("applicant_id"),
            merchant=raw.get("merchant"),
            business_purpose=raw.get("business_purpose"),
            status=status,
            idempotency_key=raw.get("idempotency_key"),
            attributes={key: value for key, value in raw.items() if key not in known},
        )

    def to_dict(self) -> dict[str, Any]:
        result = {
            "claim_id": self.claim_id,
            "version": self.version,
            "category": self.category,
            "amount": self.amount,
            "currency": self.currency,
            "occurred_on": self.occurred_on,
            "description": self.description,
            "has_receipt": self.has_receipt,
            "receipt_refs": list(self.receipt_refs),
            "pre_approved": self.pre_approved,
            "status": self.status,
        }
        for key in ("applicant_id", "merchant", "business_purpose", "idempotency_key"):
            value = getattr(self, key)
            if value is not None:
                result[key] = value
        result.update(self.attributes)
        return result


@dataclass(frozen=True)
class Handoff:
    reason_code: str
    risk_level: str
    amount_band: str
    decision_hash: str | None = None

    def __post_init__(self) -> None:
        for name in ("reason_code", "risk_level", "amount_band"):
            _require_text(getattr(self, name), name)
        if self.decision_hash is not None and not self.decision_hash.startswith("sha256:"):
            raise ContractError("handoff decision_hash must use sha256:<hex> format")

    def to_dict(self) -> dict[str, str]:
        result = {"reason_code": self.reason_code, "risk_level": self.risk_level, "amount_band": self.amount_band}
        if self.decision_hash:
            result["decision_hash"] = self.decision_hash
        return result


@dataclass(frozen=True)
class Decision:
    decision: DecisionCode | str
    reasons: tuple[str, ...]
    decision_source: str
    decision_model: str
    rule_result: str
    review_required: bool = False
    risk_score: float = 0.0
    exception_suggested: bool = False
    handoff: Handoff | None = None
    policy_refs: tuple[str, ...] = ()
    claim_id: str | None = None
    claim_version: int | None = None
    policy_version: str | None = None
    decision_hash: str | None = None

    def __post_init__(self) -> None:
        try:
            code = DecisionCode(self.decision)
        except ValueError as exc:
            raise ContractError(f"unknown decision: {self.decision}") from exc
        object.__setattr__(self, "decision", code)
        if self.decision_source not in _DECISION_SOURCES:
            raise ContractError("decision_source is unknown")
        if self.rule_result not in _RULE_RESULTS:
            raise ContractError("rule_result is unknown")
        _require_text(self.decision_model, "decision_model")
        if not isinstance(self.review_required, bool) or not isinstance(self.exception_suggested, bool):
            raise ContractError("review_required and exception_suggested must be boolean")
        if isinstance(self.risk_score, bool) or not isinstance(self.risk_score, (int, float)) or not math.isfinite(float(self.risk_score)) or not 0 <= self.risk_score <= 1:
            raise ContractError("risk_score must be between 0 and 1")
        if any(not isinstance(reason, str) or not reason.strip() for reason in self.reasons):
            raise ContractError("reasons must contain non-empty strings")
        requires_handoff = self.review_required or self.rule_result == "not_covered" or code in {DecisionCode.NEEDS_REVIEW, DecisionCode.ESCALATED}
        if requires_handoff and self.handoff is None:
            raise ContractError("review decisions require handoff details")
        if (self.claim_id is None) != (self.claim_version is None):
            raise ContractError("claim_id and claim_version must be provided together")
        if self.claim_id is not None:
            _require_text(self.claim_id, "claim_id")
            if isinstance(self.claim_version, bool) or not isinstance(self.claim_version, int) or self.claim_version < 1:
                raise ContractError("claim_version must be a positive integer")
            expected = self.compute_hash()
            if self.decision_hash is not None and self.decision_hash != expected:
                raise ContractError("decision_hash does not match decision payload")
            object.__setattr__(self, "decision_hash", expected)
        elif self.decision_hash is not None:
            raise ContractError("decision_hash requires claim identity")
        if self.handoff and self.handoff.decision_hash not in (None, self.decision_hash):
            raise ContractError("handoff decision_hash does not match decision_hash")
        if self.handoff and self.handoff.decision_hash is None and self.decision_hash:
            object.__setattr__(self, "handoff", Handoff(**{**self.handoff.to_dict(), "decision_hash": self.decision_hash}))

    def _hash_payload(self) -> dict[str, Any]:
        handoff = self.handoff.to_dict() if self.handoff else None
        if handoff is not None:
            handoff.pop("decision_hash", None)
        payload = {
            "claim_id": self.claim_id,
            "claim_version": self.claim_version,
            "policy_version": self.policy_version,
            "decision": str(self.decision),
            "reasons": list(self.reasons),
            "decision_model": self.decision_model,
            "rule_result": self.rule_result,
            "handoff": handoff,
        }
        return payload

    def compute_hash(self) -> str:
        return "sha256:" + hashlib.sha256(_canonical_json(self._hash_payload())).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        result = {
            "decision": str(self.decision), "reasons": list(self.reasons),
            "decision_source": self.decision_source, "decision_model": self.decision_model,
            "rule_result": self.rule_result, "review_required": self.review_required,
            "risk_score": float(self.risk_score), "exception_suggested": self.exception_suggested,
            "handoff": self.handoff.to_dict() if self.handoff else None, "policy_refs": list(self.policy_refs),
        }
        if self.claim_id is not None:
            result.update(claim_id=self.claim_id, claim_version=self.claim_version, policy_version=self.policy_version, decision_hash=self.decision_hash)
        return result

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "Decision":
        if not isinstance(raw, Mapping):
            raise ContractError("decision must be an object")
        data = dict(raw)
        handoff = data.get("handoff")
        if handoff is not None and not isinstance(handoff, Handoff):
            if not isinstance(handoff, Mapping):
                raise ContractError("handoff must be an object or null")
            data["handoff"] = Handoff(**handoff)
        data["reasons"] = tuple(data.get("reasons", ()))
        data["policy_refs"] = tuple(data.get("policy_refs", ()))
        return cls(**data)


@dataclass(frozen=True)
class ApprovalRecord:
    approval_id: str
    claim_id: str
    claim_version: int
    decision_hash: str
    decision: ApprovalDecision | str
    approver_id: str
    created_at: str
    comment: str = ""

    def __post_init__(self) -> None:
        for name in ("approval_id", "claim_id", "approver_id"):
            _require_text(getattr(self, name), name)
        try:
            object.__setattr__(self, "decision", ApprovalDecision(self.decision))
        except ValueError as exc:
            raise ContractError("approval decision must be approve, reject, or escalate") from exc
        if isinstance(self.claim_version, bool) or not isinstance(self.claim_version, int) or self.claim_version < 1:
            raise ContractError("claim_version must be a positive integer")
        if not self.decision_hash.startswith("sha256:"):
            raise ContractError("decision_hash must use sha256:<hex> format")
        try:
            datetime.fromisoformat(self.created_at.replace("Z", "+00:00"))
        except (ValueError, AttributeError) as exc:
            raise ContractError("created_at must be an ISO timestamp") from exc

    def to_dict(self) -> dict[str, Any]:
        return {"approval_id": self.approval_id, "claim_id": self.claim_id, "claim_version": self.claim_version,
                "decision_hash": self.decision_hash, "decision": str(self.decision), "approver_id": self.approver_id,
                "comment": self.comment, "created_at": self.created_at}


@dataclass(frozen=True)
class AuditEvent:
    event_id: str
    claim_id: str
    claim_version: int
    event_type: str
    actor_type: str
    actor_id: str
    request_id: str
    idempotency_key: str
    created_at: str
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for name in ("event_id", "claim_id", "event_type", "actor_id", "request_id", "idempotency_key"):
            _require_text(getattr(self, name), name)
        if self.actor_type not in _ACTOR_TYPES:
            raise ContractError("actor_type is unknown")
        if isinstance(self.claim_version, bool) or not isinstance(self.claim_version, int) or self.claim_version < 1:
            raise ContractError("claim_version must be a positive integer")
        if not isinstance(self.metadata, Mapping):
            raise ContractError("metadata must be an object")
        try:
            datetime.fromisoformat(self.created_at.replace("Z", "+00:00"))
        except (ValueError, AttributeError) as exc:
            raise ContractError("created_at must be an ISO timestamp") from exc
        _canonical_json(self.metadata)

    def to_dict(self) -> dict[str, Any]:
        return {"event_id": self.event_id, "claim_id": self.claim_id, "claim_version": self.claim_version,
                "event_type": self.event_type, "actor_type": self.actor_type, "actor_id": self.actor_id,
                "request_id": self.request_id, "idempotency_key": self.idempotency_key,
                "created_at": self.created_at, "metadata": dict(self.metadata)}


@dataclass(frozen=True)
class LegacyClaim:
    """Normalized compatibility input without fabricated form identity/version."""

    category: str
    amount: float
    currency: str
    has_receipt: bool
    pre_approved: bool
    source: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {**dict(self.source), "category": self.category, "amount": self.amount, "currency": self.currency,
                "has_receipt": self.has_receipt, "pre_approved": self.pre_approved}


class LegacyClaimAdapter:
    """Normalize supported legacy claim shapes while preserving their old semantics."""

    @staticmethod
    def normalize(raw: Mapping[str, Any], *, policy: dict[str, Any] | None = None) -> LegacyClaim:
        if not isinstance(raw, Mapping):
            raise ContractError("claim must be an object")
        facts = policy or load_policy_facts()
        result = validate_claim(dict(raw), formal=False, policy=facts)
        if not result["valid"]:
            raise ContractError("; ".join(result["errors"]))
        normalized = result["claim"]
        return LegacyClaim(
            category=normalized["category"], amount=float(normalized["amount"]),
            currency=str(normalized["currency"]).upper(), has_receipt=normalized["has_receipt"],
            pre_approved=bool(normalized.get("pre_approved", False)),
            source={key: value for key, value in normalized.items() if key not in {"category", "amount", "currency", "has_receipt", "pre_approved"}},
        )


__all__ = [
    "ApprovalDecision", "ApprovalRecord", "AuditEvent", "Claim", "ContractError", "Decision",
    "ClaimStatus", "DecisionCode", "ErrorCode", "Handoff", "LegacyClaim", "LegacyClaimAdapter",
]
