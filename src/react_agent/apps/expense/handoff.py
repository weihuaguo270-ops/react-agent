"""H0 contracts only: no case persistence, dispatch, approvals or Claim writes."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType

from .domain import ContractError, Decision, DecisionCode, StrEnum


class ReasonCode(StrEnum):
    RECEIPT_MANUAL_VERIFICATION = "receipt_manual_verification"
    POLICY_NOT_COVERED = "policy_not_covered"
    POLICY_CONFLICT = "policy_conflict"
    POLICY_VERSION_UNKNOWN = "policy_version_unknown"
    AUTOMATION_LIMIT_EXCEEDED = "automation_limit_exceeded"
    APPEAL_REQUESTED = "appeal_requested"
    ESCALATION_REQUESTED = "escalation_requested"
    DEPENDENCY_UNAVAILABLE = "dependency_unavailable"
    APPROVAL_RECORD_REQUIRED = "approval_record_required"


class QueueId(StrEnum):
    FINANCE_REVIEW = "finance_review"
    FINANCE_ADMIN = "finance_admin"
    EXPENSE_OPERATIONS = "expense_operations"


class Role(StrEnum):
    APPLICANT = "applicant"
    FINANCE_REVIEWER = "finance_reviewer"
    FINANCE_ADMIN = "finance_admin"
    EXPENSE_OPERATOR = "expense_operator"


class CaseStatus(StrEnum):
    QUEUED = "queued"
    ASSIGNED = "assigned"
    IN_PROGRESS = "in_progress"
    NEEDS_APPLICANT = "needs_applicant"
    ESCALATED = "escalated"
    UNROUTED = "unrouted"
    RESOLVED = "resolved"
    REJECTED = "rejected"
    CANCELLED = "cancelled"


class HandoffErrorCode(StrEnum):
    CASE_NOT_FOUND = "case_not_found"
    CASE_ALREADY_EXISTS = "case_already_exists"
    IDEMPOTENCY_CONFLICT = "idempotency_conflict"
    CASE_ALREADY_CLAIMED = "case_already_claimed"
    CASE_NOT_CLAIMABLE = "case_not_claimable"
    INVALID_CASE_TRANSITION = "invalid_case_transition"
    QUEUE_NOT_ALLOWED = "queue_not_allowed"
    QUEUE_UNAVAILABLE = "queue_unavailable"
    UNROUTED_CASE = "unrouted_case"
    CASE_VERSION_CONFLICT = "case_version_conflict"
    CLAIM_VERSION_MISMATCH = "claim_version_mismatch"
    APPROVAL_BINDING_MISMATCH = "approval_binding_mismatch"
    SLA_POLICY_UNAVAILABLE = "sla_policy_unavailable"
    NOTIFICATION_PENDING = "notification_pending"
    INVALID_HANDOFF = "invalid_handoff"
    INVALID_ROUTING_CONFIG = "invalid_routing_config"
    UNKNOWN_HANDOFF_CONDITION = "unknown_handoff_condition"


class HandoffError(ContractError):
    def __init__(self, code: HandoffErrorCode, message: str):
        super().__init__(message)
        self.code = code


TERMINAL_STATUSES = frozenset({CaseStatus.RESOLVED, CaseStatus.REJECTED, CaseStatus.CANCELLED})
TRANSITIONS = MappingProxyType({
    CaseStatus.QUEUED: frozenset({"assigned", "cancelled", "escalated", "unrouted"}),
    CaseStatus.ASSIGNED: frozenset({"in_progress", "queued", "escalated"}),
    CaseStatus.IN_PROGRESS: frozenset({"resolved", "rejected", "needs_applicant", "escalated", "queued"}),
    CaseStatus.NEEDS_APPLICANT: frozenset({"queued", "cancelled"}),
    CaseStatus.UNROUTED: frozenset({"queued", "escalated", "cancelled"}),
    CaseStatus.ESCALATED: frozenset({"queued", "unrouted", "cancelled"}),
    **{state: frozenset() for state in TERMINAL_STATUSES},
})

# Exact aliases only. A mapped condition is not, by itself, authorization to create a case.
CONDITION_REASONS = MappingProxyType({
    "规则未覆盖费用类型": ReasonCode.POLICY_NOT_COVERED,
    "金额或凭证需要人工核验": ReasonCode.RECEIPT_MANUAL_VERIFICATION,
    "需要持久化审批结果": ReasonCode.APPROVAL_RECORD_REQUIRED,
    "policy_conflict": ReasonCode.POLICY_CONFLICT,
    "policy_version_unknown": ReasonCode.POLICY_VERSION_UNKNOWN,
    "automation_limit_exceeded": ReasonCode.AUTOMATION_LIMIT_EXCEEDED,
    "appeal_requested": ReasonCode.APPEAL_REQUESTED,
    "escalation_requested": ReasonCode.ESCALATION_REQUESTED,
    "dependency_unavailable": ReasonCode.DEPENDENCY_UNAVAILABLE,
})
PRIORITIES = ("urgent", "high", "normal", "low")


def reason_for_condition(condition: str) -> ReasonCode:
    try:
        return CONDITION_REASONS[condition]
    except (KeyError, TypeError) as exc:
        raise HandoffError(HandoffErrorCode.UNKNOWN_HANDOFF_CONDITION, "unknown handoff condition") from exc


def validate_transition(source: str, target: str) -> CaseStatus:
    """Validate the static edge only; role/version/approval checks belong to H2/H3."""
    try:
        before, after = CaseStatus(source), CaseStatus(target)
        if after in TRANSITIONS[before]:
            return after
    except (ValueError, TypeError):
        pass
    raise HandoffError(HandoffErrorCode.INVALID_CASE_TRANSITION, f"invalid transition: {source} -> {target}")


def _text(value: str, name: str, code=HandoffErrorCode.INVALID_ROUTING_CONFIG) -> None:
    if not isinstance(value, str) or not value.strip():
        raise HandoffError(code, f"{name} must be non-empty")


@dataclass(frozen=True)
class SLAPolicy:
    sla_policy_version: str
    response_sla_seconds: int
    resolution_sla_seconds: int

    def __post_init__(self):
        code = HandoffErrorCode.SLA_POLICY_UNAVAILABLE
        _text(self.sla_policy_version, "sla_policy_version", code)
        values = (self.response_sla_seconds, self.resolution_sla_seconds)
        if any(type(value) is not int or value <= 0 for value in values) or values[0] > values[1]:
            raise HandoffError(code, "SLA requires 0 < response <= resolution in wall-clock seconds")


@dataclass(frozen=True)
class QueueDefinition:
    queue_id: QueueId
    display_name: str
    allowed_roles: tuple[Role, ...]
    priority_order: tuple[str, ...]
    sla: SLAPolicy
    escalate_to: QueueId
    available: bool = True

    def __post_init__(self):
        try:
            object.__setattr__(self, "queue_id", QueueId(self.queue_id))
            object.__setattr__(self, "escalate_to", QueueId(self.escalate_to))
        except (ValueError, TypeError) as exc:
            raise HandoffError(HandoffErrorCode.QUEUE_NOT_ALLOWED, "unknown queue") from exc
        try:
            roles = tuple(Role(role) for role in self.allowed_roles)
        except (ValueError, TypeError) as exc:
            raise HandoffError(HandoffErrorCode.QUEUE_NOT_ALLOWED, "unknown queue role") from exc
        if not roles or Role.APPLICANT in roles or len(set(roles)) != len(roles):
            raise HandoffError(HandoffErrorCode.QUEUE_NOT_ALLOWED, "queue needs distinct processing roles")
        object.__setattr__(self, "allowed_roles", roles)
        object.__setattr__(self, "priority_order", tuple(self.priority_order))
        _text(self.display_name, "display_name")
        if self.priority_order != PRIORITIES or type(self.available) is not bool:
            raise HandoffError(HandoffErrorCode.INVALID_ROUTING_CONFIG, "invalid priority order or availability")
        if not isinstance(self.sla, SLAPolicy):
            raise HandoffError(HandoffErrorCode.SLA_POLICY_UNAVAILABLE, "SLA policy is required")


@dataclass(frozen=True)
class RoutingRule:
    reason_code: ReasonCode
    queue_id: QueueId
    priority: str = "normal"

    def __post_init__(self):
        try:
            object.__setattr__(self, "reason_code", ReasonCode(self.reason_code))
        except (ValueError, TypeError) as exc:
            raise HandoffError(HandoffErrorCode.INVALID_ROUTING_CONFIG, "unknown routing reason") from exc
        try:
            object.__setattr__(self, "queue_id", QueueId(self.queue_id))
        except (ValueError, TypeError) as exc:
            raise HandoffError(HandoffErrorCode.QUEUE_NOT_ALLOWED, "unknown rule queue") from exc
        if self.priority not in PRIORITIES:
            raise HandoffError(HandoffErrorCode.INVALID_ROUTING_CONFIG, "unknown priority")


@dataclass(frozen=True)
class RoutingConfig:
    routing_rule_version: str
    queues: tuple[QueueDefinition, ...]
    rules: tuple[RoutingRule, ...]

    def __post_init__(self):
        _text(self.routing_rule_version, "routing_rule_version")
        object.__setattr__(self, "queues", tuple(self.queues))
        object.__setattr__(self, "rules", tuple(self.rules))
        ids = {queue.queue_id for queue in self.queues}
        if not ids or len(ids) != len(self.queues):
            raise HandoffError(HandoffErrorCode.INVALID_ROUTING_CONFIG, "missing or duplicate queues")
        if any(queue.escalate_to not in ids for queue in self.queues):
            raise HandoffError(HandoffErrorCode.QUEUE_NOT_ALLOWED, "escalation queue is undefined")
        if any(rule.queue_id not in ids for rule in self.rules):
            raise HandoffError(HandoffErrorCode.QUEUE_NOT_ALLOWED, "rule queue is undefined")
        if len({rule.reason_code for rule in self.rules}) != len(self.rules):
            raise HandoffError(HandoffErrorCode.INVALID_ROUTING_CONFIG, "duplicate reason rules")

    @classmethod
    def from_dict(cls, raw: dict) -> RoutingConfig:
        """Load trusted configuration; reject malformed or extra fields."""
        try:
            values = dict(raw)
            values["queues"] = tuple(QueueDefinition(
                **{**queue, "sla": SLAPolicy(**queue["sla"])}
            ) for queue in values["queues"])
            values["rules"] = tuple(RoutingRule(**rule) for rule in values["rules"])
            return cls(**values)
        except HandoffError:
            raise
        except (KeyError, TypeError, ValueError) as exc:
            raise HandoffError(HandoffErrorCode.INVALID_ROUTING_CONFIG, "malformed routing configuration") from exc


def load_routing_config(path: str | Path) -> RoutingConfig:
    """Explicit path; this H0 fixture is not wired into the running service."""
    return RoutingConfig.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))


def validate_queue_access(config: RoutingConfig, queue_id: str, role: str) -> QueueDefinition:
    queue = next((queue for queue in config.queues if queue.queue_id == queue_id), None)
    if queue is None or role not in queue.allowed_roles:
        raise HandoffError(HandoffErrorCode.QUEUE_NOT_ALLOWED, "queue or processing role is not allowed")
    if not queue.available:
        raise HandoffError(HandoffErrorCode.QUEUE_UNAVAILABLE, "queue is unavailable")
    return queue


@dataclass(frozen=True)
class HandoffPlan:
    """Routing snapshot, not a persisted case. H1 supplies case_id after atomic creation."""
    claim_id: str
    claim_version: int
    decision_hash: str
    reason_code: ReasonCode
    risk_level: str
    amount_band: str
    status: CaseStatus
    queue_id: QueueId | None
    priority: str
    routing_rule_version: str
    sla: SLAPolicy | None
    error_code: HandoffErrorCode | None = None
    case_id: str | None = None

    @property
    def idempotency_key(self) -> str:
        return f"handoff:{self.claim_id}:{self.claim_version}:{self.reason_code}"


def plan_handoff(
    decision: Decision, config: RoutingConfig, *, existing: HandoffPlan | None = None,
) -> HandoffPlan | None:
    """Preview controlled routing/reuse; no I/O, assignment, Claim changes or approval."""
    try:
        validated = Decision.from_dict(decision.to_dict())
    except (ContractError, TypeError, ValueError, AttributeError) as exc:
        raise HandoffError(HandoffErrorCode.INVALID_HANDOFF, "validated Decision is required") from exc
    required = (validated.review_required or validated.rule_result == "not_covered"
                or validated.decision in {DecisionCode.NEEDS_REVIEW, DecisionCode.ESCALATED})
    if not required:
        return None
    if not validated.claim_id or not validated.policy_version or not validated.decision_hash:
        raise HandoffError(HandoffErrorCode.INVALID_HANDOFF, "Claim/version/policy/hash binding is required")
    _text(validated.policy_version, "policy_version", HandoffErrorCode.INVALID_HANDOFF)
    handoff = validated.handoff
    try:
        reason = ReasonCode(handoff.reason_code)
    except (ValueError, TypeError) as exc:
        raise HandoffError(HandoffErrorCode.INVALID_HANDOFF, "controlled handoff reason is required") from exc
    if existing is not None:
        binding = (validated.claim_id, validated.claim_version, reason, validated.decision_hash)
        if binding != (existing.claim_id, existing.claim_version, existing.reason_code, existing.decision_hash):
            raise HandoffError(HandoffErrorCode.IDEMPOTENCY_CONFLICT, "existing case trigger or decision differs")
        try:
            status = CaseStatus(existing.status)
        except (TypeError, ValueError) as exc:
            raise HandoffError(HandoffErrorCode.INVALID_HANDOFF, "unknown existing case status") from exc
        if not isinstance(existing.case_id, str) or not existing.case_id.strip():
            raise HandoffError(HandoffErrorCode.INVALID_HANDOFF, "validated existing case snapshot is required")
        if status in TERMINAL_STATUSES:
            raise HandoffError(HandoffErrorCode.CASE_ALREADY_EXISTS, "terminal case cannot be reopened by replay")
        return existing  # Preserve original routing/SLA snapshots, even after config changes.
    rule = next((rule for rule in config.rules if rule.reason_code == reason), None)
    queue = next((queue for queue in config.queues if rule and queue.queue_id == rule.queue_id), None)
    error = (HandoffErrorCode.UNROUTED_CASE if queue is None else
             HandoffErrorCode.QUEUE_UNAVAILABLE if not queue.available else None)
    return HandoffPlan(
        claim_id=validated.claim_id, claim_version=validated.claim_version,
        decision_hash=validated.decision_hash, reason_code=reason,
        risk_level=handoff.risk_level, amount_band=handoff.amount_band,
        status=CaseStatus.UNROUTED if error else CaseStatus.QUEUED,
        queue_id=None if error else queue.queue_id,
        priority="high" if error else rule.priority,
        routing_rule_version=config.routing_rule_version,
        sla=None if error else queue.sla, error_code=error,
    )
