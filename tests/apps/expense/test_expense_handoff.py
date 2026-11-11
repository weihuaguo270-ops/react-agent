"""H0 freeze: pure routing contracts, deliberately no database or case API."""
from __future__ import annotations

import json
from dataclasses import FrozenInstanceError, replace
from pathlib import Path

import pytest

from react_agent.apps.expense.domain import Decision, Handoff
from react_agent.apps.expense.handoff import (
    CaseStatus,
    HandoffError,
    HandoffErrorCode,
    QueueId,
    ReasonCode,
    Role,
    RoutingConfig,
    load_routing_config,
    plan_handoff,
    reason_for_condition,
    validate_queue_access,
    validate_transition,
)
from react_agent.skills.registry import get_skill

FIXTURE = Path(__file__).resolve().parents[3] / "fixtures/expense/handoff_routing_v1.json"


@pytest.fixture
def config():
    return load_routing_config(FIXTURE)


def decision(reason="receipt_manual_verification", **overrides):
    values = dict(
        decision="needs_review", reasons=("verified structured handoff",),
        decision_source="rules", decision_model="expense-rules-v1", rule_result="matched",
        review_required=True, handoff=Handoff(reason, "medium", "100-500"),
        claim_id="clm-h0", claim_version=2, policy_version="expense-policy-sim-v1",
    )
    values.update(overrides)
    return Decision(**values)


def assert_error(code, call, *args, **kwargs):
    with pytest.raises(HandoffError) as caught:
        call(*args, **kwargs)
    assert caught.value.code == code


def test_state_machine_contract_all_edges():
    # Frozen business contract: every omitted edge, including self-transitions, must fail.
    allowed = {
        "queued": {"assigned", "cancelled", "escalated", "unrouted"},
        "assigned": {"in_progress", "queued", "escalated"},
        "in_progress": {"resolved", "rejected", "needs_applicant", "escalated", "queued"},
        "needs_applicant": {"queued", "cancelled"},
        "unrouted": {"queued", "escalated", "cancelled"},
        "escalated": {"queued", "unrouted", "cancelled"},
        "resolved": set(), "rejected": set(), "cancelled": set(),
    }
    assert set(CaseStatus) == set(allowed)
    for source in allowed:
        for target in allowed:
            if target in allowed[source]:
                assert validate_transition(source, target) == target
            else:
                assert_error("invalid_case_transition", validate_transition, source, target)


@pytest.mark.parametrize("source,target", [("approved", "queued"), ("queued", "approved"), (None, "queued")])
def test_unknown_states_are_contract_errors(source, target):
    assert_error("invalid_case_transition", validate_transition, source, target)


def test_every_existing_expense_skill_condition_has_an_exact_mapping():
    conditions = get_skill("expense_claim_review").boundary.human_handoff_conditions
    assert {condition: reason_for_condition(condition) for condition in conditions} == {
        "规则未覆盖费用类型": "policy_not_covered",
        "金额或凭证需要人工核验": "receipt_manual_verification",
        "需要持久化审批结果": "approval_record_required",
    }
    for token in ("policy_conflict", "policy_version_unknown", "automation_limit_exceeded",
                  "appeal_requested", "escalation_requested", "dependency_unavailable"):
        assert reason_for_condition(token) == token
    assert_error("unknown_handoff_condition", reason_for_condition, "大概需要人工处理")


def test_frozen_fixture_routes_all_reasons_and_snapshots_validated_decision(config):
    expected = {
        "receipt_manual_verification": ("finance_review", "normal"),
        "policy_not_covered": ("finance_review", "normal"),
        "policy_conflict": ("finance_admin", "high"),
        "policy_version_unknown": ("expense_operations", "high"),
        "automation_limit_exceeded": ("finance_admin", "high"),
        "appeal_requested": ("finance_review", "normal"),
        "escalation_requested": ("finance_admin", "high"),
        "dependency_unavailable": ("expense_operations", "high"),
        "approval_record_required": ("finance_review", "normal"),
    }
    assert set(ReasonCode) == set(expected)
    for reason, (queue, priority) in expected.items():
        value = decision(reason)
        before = value.to_dict()
        plan = plan_handoff(value, config)
        assert (plan.queue_id, plan.priority, plan.status) == (queue, priority, "queued")
        assert (plan.claim_id, plan.claim_version, plan.decision_hash) == ("clm-h0", 2, value.decision_hash)
        assert (plan.risk_level, plan.amount_band) == ("medium", "100-500")
        assert plan.routing_rule_version == "expense-routing-v1"
        assert plan.sla.sla_policy_version == "expense-sla-v1"
        assert plan.case_id is None and plan.error_code is None
        assert value.to_dict() == before


@pytest.mark.parametrize("queue,role", [
    ("agent_queue", "finance_admin"), ("finance_admin", "finance_reviewer"),
    ("finance_review", "applicant"), ("expense_operations", "finance_admin"),
    ("finance_review", "superuser"),
])
def test_illegal_queue_or_role_fails_closed(config, queue, role):
    assert_error("queue_not_allowed", validate_queue_access, config, queue, role)


def test_controlled_queue_roles_and_unavailable_queue(config):
    assert set(Role) == {"applicant", "finance_reviewer", "finance_admin", "expense_operator"}
    assert set(QueueId) == {"finance_review", "finance_admin", "expense_operations"}
    for queue in config.queues:
        for role in queue.allowed_roles:
            assert validate_queue_access(config, queue.queue_id, role) is queue
    queues = tuple(replace(queue, available=False) for queue in config.queues)
    unavailable = replace(config, queues=queues)
    assert_error("queue_unavailable", validate_queue_access, unavailable, "finance_review", "finance_reviewer")
    plan = plan_handoff(decision(), unavailable)
    assert (plan.status, plan.queue_id, plan.error_code, plan.sla) == ("unrouted", None, "queue_unavailable", None)


def test_unmatched_route_stays_unrouted_without_a_default_assignee(config):
    config = replace(config, rules=())
    plan = plan_handoff(decision(), config)
    assert (plan.status, plan.queue_id, plan.error_code, plan.sla) == ("unrouted", None, "unrouted_case", None)
    assert plan.priority == "high"
    assert plan.routing_rule_version == "expense-routing-v1"


@pytest.mark.parametrize("status", ["queued", "assigned", "in_progress", "needs_applicant", "escalated", "unrouted"])
def test_duplicate_trigger_reuses_active_case_and_original_routing_sla(config, status):
    value = decision()
    existing = replace(plan_handoff(value, config), case_id="case-h0", status=CaseStatus(status))
    changed = replace(config, routing_rule_version="expense-routing-v2", rules=(), queues=tuple(
        replace(queue, sla=replace(queue.sla, sla_policy_version="expense-sla-v2")) for queue in config.queues
    ))
    assert existing.idempotency_key == "handoff:clm-h0:2:receipt_manual_verification"
    assert plan_handoff(value, changed, existing=existing) is existing
    assert existing.sla.sla_policy_version == "expense-sla-v1"


@pytest.mark.parametrize("changes", [
    {"claim_id": "other"}, {"claim_version": 3}, {"policy_version": "policy-v2"},
    {"reason": "policy_not_covered"}, {"reasons": ("changed decision",)},
])
def test_duplicate_binding_or_fingerprint_conflict(config, changes):
    existing = replace(plan_handoff(decision(), config), case_id="case-h0")
    assert_error("idempotency_conflict", plan_handoff, decision(**changes), config, existing=existing)


@pytest.mark.parametrize("status", ["resolved", "rejected", "cancelled"])
def test_terminal_case_is_not_reopened_by_duplicate_trigger(config, status):
    existing = replace(plan_handoff(decision(), config), case_id="case-h0", status=CaseStatus(status))
    assert_error("case_already_exists", plan_handoff, decision(), config, existing=existing)


@pytest.mark.parametrize("changes", [{"case_id": None}, {"status": "approved"}])
def test_duplicate_requires_an_existing_case_id_and_valid_status(config, changes):
    existing = replace(plan_handoff(decision(), config), case_id="case-h0")
    existing = replace(existing, **changes)
    assert_error("invalid_handoff", plan_handoff, decision(), config, existing=existing)


@pytest.mark.parametrize("code,rule_result", [("approve_manager", "matched"), ("reject_policy", "rejected")])
def test_condition_mapping_does_not_turn_normal_approval_or_hard_rejection_into_cases(config, code, rule_result):
    value = decision("approval_record_required", decision=code, rule_result=rule_result, review_required=False)
    assert plan_handoff(value, config) is None


@pytest.mark.parametrize("changes", [
    {"decision": "approve_finance", "review_required": True},
    {"decision": "reject_policy", "rule_result": "rejected", "review_required": True},
    {"reason": "policy_not_covered", "review_required": False, "rule_result": "not_covered"},
    {"reason": "escalation_requested", "decision": "escalated", "review_required": False},
])
def test_explicit_review_or_uncovered_or_escalated_decision_remains_nonterminal(config, changes):
    assert plan_handoff(decision(**changes), config).status == "queued"


@pytest.mark.parametrize("changes", [
    {"reason": "free text"}, {"claim_id": None, "claim_version": None},
    {"policy_version": None}, {"policy_version": " "}, {"policy_version": 42},
])
def test_invalid_handoff_binding_is_not_inferred_from_prose(config, changes):
    assert_error("invalid_handoff", plan_handoff, decision(**changes), config)


@pytest.mark.parametrize("field,value,code", [
    ("queue_id", "random_queue", "queue_not_allowed"),
    ("allowed_roles", ["applicant"], "queue_not_allowed"),
    ("allowed_roles", ["superuser"], "queue_not_allowed"),
    ("escalate_to", "random_queue", "queue_not_allowed"),
    ("available", "true", "invalid_routing_config"),
    ("priority_order", ["normal"], "invalid_routing_config"),
])
def test_malformed_queue_config_is_rejected(field, value, code):
    raw = json.loads(FIXTURE.read_text(encoding="utf-8"))
    raw["queues"][0][field] = value
    assert_error(code, RoutingConfig.from_dict, raw)


@pytest.mark.parametrize("seconds", [0, -1, True, "14400", 100000])
def test_sla_format_requires_positive_integer_seconds_and_order(seconds):
    raw = json.loads(FIXTURE.read_text(encoding="utf-8"))
    raw["queues"][0]["sla"]["response_sla_seconds"] = seconds
    assert_error("sla_policy_unavailable", RoutingConfig.from_dict, raw)


def test_routing_and_sla_versions_and_unambiguous_rules_are_required(config):
    assert_error("invalid_routing_config", replace, config, routing_rule_version="")
    assert_error("sla_policy_unavailable", replace, config.queues[0].sla, sla_policy_version="")
    assert_error("invalid_routing_config", replace, config, rules=config.rules + (config.rules[0],))
    assert_error("queue_not_allowed", replace, config, queues=(config.queues[0],))
    with pytest.raises(FrozenInstanceError):
        config.routing_rule_version = "changed"


def test_error_vocabulary_covers_future_case_boundary_without_implementing_it():
    assert {str(code) for code in HandoffErrorCode} == {
        "case_not_found", "case_already_exists", "idempotency_conflict", "case_already_claimed",
        "case_not_claimable", "invalid_case_transition", "queue_not_allowed", "queue_unavailable",
        "unrouted_case", "case_version_conflict", "claim_version_mismatch", "approval_binding_mismatch",
        "sla_policy_unavailable", "notification_pending", "invalid_handoff", "invalid_routing_config",
        "unknown_handoff_condition",
    }
