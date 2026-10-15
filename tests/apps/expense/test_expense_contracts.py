from __future__ import annotations

from react_agent.apps.expense.contracts import (
    PolicyContractError,
    limits_from_policy,
    load_policy_facts,
    validate_claim,
)
from react_agent.apps.expense.offline_answer import answer_offline, decide


def _formal_claim(category: str, **fields):
    return {
        "claim_id": "C-T01",
        "claim_version": 1,
        "category": category,
        "amount": 100,
        "currency": "USD",
        "occurred_on": "2026-10-12",
        "description": "business expense",
        "business_purpose": "client meeting",
        "has_receipt": True,
        "receipt_refs": ["receipt-1"],
        "pre_approved": False,
        **fields,
    }


def test_policy_v2_is_versioned_and_limits_preserve_legacy_names():
    policy = load_policy_facts()
    limits = limits_from_policy(policy)

    assert policy["policy_version"] == "expense-policy-sim-v1"
    assert limits["meal"] == limits["餐饮"] == 200
    assert limits["office_purchase"] == limits["办公采购"] == 1000


def test_default_profile_is_the_project_simulation_and_legacy_cny_profile_is_unavailable():
    policy = load_policy_facts()
    assert policy["selected_profile"] == "project_simulation_v1"
    try:
        load_policy_facts(profile="cny_candidate")
    except PolicyContractError as exc:
        assert "unavailable" in str(exc)
    else:
        raise AssertionError("reference-only profile must not be executable")


def test_formal_contract_accepts_category_specific_claims():
    cases = [
        _formal_claim("meal", expense_type="business_meal", business_purpose="client meeting", participants=["A"]),
        _formal_claim("transport", transport_mode="train", route_scope="inter_city", seat_class="second_class"),
        _formal_claim("lodging", city_code="CN-SH", city_tier="tier1", check_in="2026-10-12", check_out="2026-10-14", nights=2),
        _formal_claim("office_purchase", purchase_order_id="PO-1", item_type="stationery"),
    ]

    results = [validate_claim(claim) for claim in cases]
    assert all(result["valid"] for result in results)
    assert results[0]["claim"]["category"] == "meal"
    assert results[2]["error_code"] == "needs_review"
    assert results[2]["review_required"]


def test_formal_contract_rejects_missing_or_unknown_category_fields():
    missing_po = validate_claim(_formal_claim("office_purchase", item_type="stationery"))
    unknown_mode = validate_claim(
        _formal_claim("transport", transport_mode="scooter", route_scope="intra_city", seat_class="standard")
    )
    bad_nights = validate_claim(
        _formal_claim("lodging", city_code="CN-SH", city_tier="tier1", check_in="2026-10-12", check_out="2026-10-14", nights=1)
    )

    assert missing_po["error_code"] == "reject_missing_purchase_order"
    assert missing_po["policy_decision"] == "reject_missing_purchase_order"
    assert unknown_mode["error_code"] == "invalid_claim"
    assert "transport_mode" in " ".join(unknown_mode["errors"])
    assert bad_nights["error_code"] == "invalid_claim"


def test_transport_policy_combination_outside_candidate_matrix_requires_review():
    result = validate_claim(
        _formal_claim("transport", transport_mode="flight", route_scope="inter_city", seat_class="business")
    )

    assert result["valid"]
    assert result["error_code"] == "needs_review"
    assert result["review_required"]


def test_office_purchase_with_po_stays_in_review_without_external_verification():
    result = validate_claim(_formal_claim("office_purchase", purchase_order_id="PO-2", item_type="equipment"))

    assert result["valid"]
    assert result["error_code"] == "needs_review"
    assert result["review_required"]


def test_weekend_entertainment_is_not_automatically_rejected():
    result = validate_claim(
        _formal_claim(
            "meal",
            expense_type="entertainment",
            business_purpose="client event",
            participants=["A", "B"],
            occurred_on="2026-10-17",
        )
    )

    assert result["valid"]
    assert result["error_code"] == "needs_review"
    assert result["review_required"]


def test_non_cny_claim_is_routed_to_manual_review():
    claim = _formal_claim(
        "office_purchase", currency="EUR", purchase_order_id="PO-2", item_type="equipment"
    )
    result = validate_claim(claim)

    assert result["valid"]
    assert result["error_code"] == "needs_review"
    assert result["review_required"]


def test_policy_fixture_corruption_fails_closed():
    class BrokenPolicyPath:
        def read_text(self, encoding):
            raise FileNotFoundError("broken policy fixture")

    try:
        load_policy_facts(BrokenPolicyPath())
    except PolicyContractError:
        pass
    else:
        raise AssertionError("broken policy must fail closed")


def test_legacy_chat_claim_remains_compatible_and_uses_v2_policy():
    result = answer_offline(
        {"claim": {"category": "餐饮", "amount": 128, "has_receipt": True}}
    )

    assert result["ok"]
    assert result["claim"]["category"] == "meal"
    assert result["decision"] == "approve_manager"
    assert result["claim"]["currency"] == "USD"


def test_legacy_amount_explicitly_in_cny_is_routed_to_review():
    result = answer_offline({"message": "餐饮 128元 有发票"})
    assert result["decision"] == "needs_review"


def test_explicit_unknown_profile_is_reported_as_unavailable():
    result = answer_offline(
        {
            "policy_profile": "cny_candidate",
            "claim": {"category": "餐饮", "amount": 128, "has_receipt": True},
        }
    )
    assert result["error_code"] == "policy_profile_unavailable"
    assert result["policy_profile"] == "cny_candidate"


def test_project_simulation_dynamic_flight_price_routes_to_review():
    result = validate_claim(
        _formal_claim(
            "transport",
            currency="USD",
            transport_mode="flight",
            route_scope="inter_city",
            seat_class="economy",
            market_price=100,
            amount=121,
        )
    )
    assert result["error_code"] == "needs_review"
    assert result["review_required"]


def test_project_simulation_lodging_uses_market_directory_and_nightly_limit():
    accepted = validate_claim(
        _formal_claim(
            "lodging",
            currency="USD",
            amount=300,
            city_code="US-NYC",
            city_tier="market_high",
            check_in="2026-10-12",
            check_out="2026-10-13",
            nights=1,
            market_price_per_night=250,
        )
    )
    assert accepted["valid"]
    assert not accepted["review_required"]
    over_limit = validate_claim(
        _formal_claim(
            "lodging",
            currency="USD",
            amount=301,
            city_code="US-NYC",
            city_tier="market_high",
            check_in="2026-10-12",
            check_out="2026-10-13",
            nights=1,
            market_price_per_night=300,
        )
    )
    assert over_limit["error_code"] == "reject_over_limit"


def test_project_simulation_verified_purchase_order_can_leave_review():
    result = validate_claim(
        _formal_claim(
            "office_purchase",
            currency="USD",
            purchase_order_id="PO-2026",
            item_type="equipment",
            purchase_order_verified=True,
        )
    )
    assert result["valid"]
    assert not result["review_required"]


def test_project_simulation_monthly_threshold_routes_to_review():
    result = validate_claim(
        _formal_claim("meal", currency="USD", expense_type="business_meal", participants=["A"], monthly_reimbursement_total=10001)
    )
    assert result["error_code"] == "needs_review"
    assert result["review_required"]


def test_missing_receipt_affidavit_requires_manager_approval():
    limits = limits_from_policy()
    claim = {"category": "meal", "amount": 100, "has_receipt": False}
    assert decide(claim, limits) == "reject_no_receipt"
    claim.update(missing_receipt_affidavit=True, manager_approved_missing_receipt=True)
    assert decide(claim, limits) == "approve_manager"


def test_business_critical_trip_requires_preapproval():
    result = validate_claim(
        _formal_claim("meal", currency="USD", expense_type="business_meal", participants=["A"], business_critical_trip=True)
    )
    assert result["error_code"] == "needs_review"
    assert result["review_required"]


def test_e_group_uses_higher_monthly_review_threshold():
    below = validate_claim(
        _formal_claim(
            "meal", currency="USD", expense_type="business_meal", participants=["A"],
            member_group="e_group", monthly_reimbursement_total=15000,
        )
    )
    assert not below["review_required"]


def test_meal_over_limit_requires_preapproval_and_then_director():
    limits = limits_from_policy()

    assert decide({"category": "meal", "amount": 260, "has_receipt": True}, limits) == "reject_over_limit"
    assert decide(
        {"category": "meal", "amount": 260, "has_receipt": True, "pre_approved": True}, limits
    ) == "approve_director"
