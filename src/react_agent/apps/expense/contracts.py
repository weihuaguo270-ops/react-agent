"""Versioned Expense claim and policy contracts.

This module validates the shape of a claim before the legacy rule function is
called.  It intentionally does not pretend to verify external receipts,
cities, calendars, purchase orders, or exchange rates.
"""
from __future__ import annotations

import json
import math
import re
from datetime import date
from pathlib import Path
from typing import Any

_REPO = Path(__file__).resolve().parents[4]
POLICY_PATH = _REPO / "fixtures" / "expense" / "expense_policy_v2.json"

CATEGORY_ALIASES = {
    "餐饮": "meal",
    "交通": "transport",
    "住宿": "lodging",
    "办公采购": "office_purchase",
}


class PolicyContractError(ValueError):
    """Raised when the versioned policy fixture is malformed."""


def load_policy_facts(path: Path = POLICY_PATH, profile: str | None = None) -> dict[str, Any]:
    """Load the selected policy profile and minimally validate its facts.

    The top-level fixture is the published project simulation profile. Legacy
    callers may still pass ``default`` as an alias.
    """
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PolicyContractError(f"policy fixture unavailable: {path}") from exc
    if not isinstance(data, dict) or not str(data.get("policy_version", "")):
        raise PolicyContractError("policy_version is required")
    selected = str(profile or "project_simulation_v1")
    if selected not in {"project_simulation_v1", "default"}:
        raise PolicyContractError(f"policy profile unavailable: {selected}")
    data["selected_profile"] = "project_simulation_v1"
    categories = data.get("categories")
    if not isinstance(categories, dict) or not categories:
        raise PolicyContractError("categories are required")
    for category, facts in categories.items():
        if not isinstance(facts, dict) or not isinstance(facts.get("limit_amount"), (int, float)):
            raise PolicyContractError(f"invalid category facts: {category}")
        if float(facts["limit_amount"]) < 0:
            raise PolicyContractError(f"negative category limit: {category}")
        if not isinstance(facts.get("required_fields"), list):
            raise PolicyContractError(f"required_fields are required: {category}")
    return data


def normalize_category(value: Any, policy: dict[str, Any] | None = None) -> str:
    """Return the stable category identifier, accepting legacy display names."""
    candidate = str(value or "").strip()
    if candidate in CATEGORY_ALIASES:
        return CATEGORY_ALIASES[candidate]
    facts = policy or load_policy_facts()
    if candidate in facts.get("categories", {}):
        return candidate
    return ""


def limits_from_policy(policy: dict[str, Any] | None = None) -> dict[str, float]:
    """Expose policy limits under stable ids and legacy display names."""
    facts = policy or load_policy_facts()
    limits: dict[str, float] = {}
    for category, values in facts["categories"].items():
        amount = float(values["limit_amount"])
        limits[category] = amount
        display_name = values.get("display_name")
        if display_name:
            limits[str(display_name)] = amount
    return limits


def _error(code: str, *messages: str) -> dict[str, Any]:
    return {"valid": False, "error_code": code, "errors": list(messages), "review_required": False}


def _review(claim: dict[str, Any], *messages: str) -> dict[str, Any]:
    return {
        "valid": True,
        "claim": claim,
        "error_code": "needs_review",
        "errors": list(messages),
        "review_required": True,
    }


def _policy_reject(claim: dict[str, Any], code: str, message: str) -> dict[str, Any]:
    return {
        "valid": True,
        "claim": claim,
        "error_code": code,
        "errors": [message],
        "review_required": False,
        "policy_decision": code,
    }


def validate_claim(
    claim: dict[str, Any],
    *,
    formal: bool = True,
    policy: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Validate a claim and return normalized data plus structured errors.

    ``formal=False`` is the compatibility path used by the old chat adapter;
    it validates only the fields that the legacy rule engine can understand.
    """
    if not isinstance(claim, dict):
        return _error("invalid_claim", "claim must be an object")
    facts = policy or load_policy_facts()
    category = normalize_category(claim.get("category"), facts)
    if not category:
        return _error("invalid_claim", "category is missing or unknown")
    amount = claim.get("amount")
    if isinstance(amount, bool) or not isinstance(amount, (int, float)):
        return _error("invalid_claim", "amount must be a number")
    if not math.isfinite(float(amount)) or float(amount) < 0:
        return _error("invalid_claim", "amount must be finite and non-negative")
    if not isinstance(claim.get("has_receipt"), bool):
        return _error("invalid_claim", "has_receipt must be boolean")
    if "pre_approved" in claim and not isinstance(claim["pre_approved"], bool):
        if claim["pre_approved"] is not None or not claim.get("pre_approval_ref"):
            return _error("invalid_claim", "pre_approved must be boolean unless a pre_approval_ref is supplied")

    normalized = dict(claim)
    normalized["category"] = category
    normalized["amount"] = float(amount)
    if not formal:
        base_currency = str(facts.get("currency", "USD")).upper()
        currency = str(claim.get("currency", base_currency)).upper()
        normalized["currency"] = currency
        if currency != base_currency:
            return {
                "valid": True,
                "claim": normalized,
                "error_code": "needs_review",
                "errors": [f"non-{base_currency} claims require manual review"],
                "review_required": True,
            }
        return {"valid": True, "claim": normalized, "error_code": "", "errors": [], "review_required": False}

    required = ["claim_id", "claim_version", "currency", "occurred_on", "description", "business_purpose"]
    missing = [field for field in required if not claim.get(field)]
    if claim.get("has_receipt") and not claim.get("receipt_refs"):
        missing.append("receipt_refs")
    if "pre_approved" not in claim and not claim.get("pre_approval_ref"):
        missing.append("pre_approved or pre_approval_ref")
    category_facts = facts["categories"][category]
    if category == "meal" and claim.get("expense_type") == "entertainment" and not claim.get("business_purpose"):
        return _policy_reject(normalized, "reject_policy", "entertainment requires a business purpose")
    if category == "office_purchase" and not claim.get("purchase_order_id"):
        missing_without_po = list(missing)
        missing_without_po.extend(
            field for field in category_facts["required_fields"]
            if field != "purchase_order_id" and not claim.get(field)
        )
        if not missing_without_po:
            return _policy_reject(normalized, "reject_missing_purchase_order", "purchase_order_id is required")
    missing.extend(field for field in category_facts["required_fields"] if not claim.get(field))
    if missing:
        return _error("invalid_claim", "missing required fields: " + ", ".join(sorted(set(missing))))
    try:
        date.fromisoformat(str(claim["occurred_on"]))
    except (TypeError, ValueError):
        return _error("invalid_claim", "occurred_on must be an ISO date")
    if claim.get("business_critical_trip") and not claim.get("pre_approved"):
        return _review(normalized, "business-critical trip requires manager pre-approval")

    if category == "office_purchase":
        pattern = str(category_facts.get("purchase_order_pattern", ""))
        if pattern and not re.fullmatch(pattern, str(claim["purchase_order_id"])):
            return _error("invalid_claim", "purchase_order_id has an invalid format")
        if not claim.get("purchase_order_verified"):
            return _review(normalized, "purchase order is not verified in the simulation registry")
    if category == "transport":
        invalid = []
        for field, key in (("transport_mode", "transport_modes"), ("route_scope", "route_scopes"), ("seat_class", "seat_classes")):
            if claim[field] not in category_facts[key]:
                invalid.append(f"unknown {field}: {claim[field]}")
        if invalid:
            return _error("invalid_claim", *invalid)
        if float(amount) > float(category_facts["limit_amount"]):
            return _policy_reject(normalized, "reject_over_limit", "transport amount exceeds the per-claim limit")
        combination = [claim["transport_mode"], claim["route_scope"], claim["seat_class"]]
        if combination not in category_facts.get("allowed_combinations", []):
            return _review(normalized, "transport combination is outside the simulation policy")
        if claim["transport_mode"] == "flight":
            market_price = claim.get("market_price")
            if not isinstance(market_price, (int, float)) or isinstance(market_price, bool) or market_price <= 0:
                return _review(normalized, "flight market reference price is required")
            threshold = float(facts.get("global_rules", {}).get("dynamic_price_review_pct", 20))
            if float(amount) > float(market_price) * (1 + threshold / 100):
                return _review(normalized, "airfare exceeds the simulated dynamic market price threshold")
    elif category == "meal":
        if claim["expense_type"] not in category_facts["expense_types"]:
            return _error("invalid_claim", f"unknown expense_type: {claim['expense_type']}")
        if claim["expense_type"] == "entertainment":
            occurred_on = date.fromisoformat(str(claim["occurred_on"]))
            if occurred_on.weekday() >= 5:
                return _review(normalized, "weekend entertainment requires manual review")
            return _review(normalized, "entertainment requires review under a separate policy")
    elif category == "lodging":
        directory = category_facts.get("city_directory", {})
        configured_tier = directory.get(str(claim["city_code"]).upper())
        if not configured_tier:
            return _review(normalized, "destination city is not in the simulation directory")
        if configured_tier not in category_facts["city_tiers"]:
            return _error("invalid_claim", f"unknown configured city_tier: {configured_tier}")
        legacy_tier_aliases = {"tier1": "market_high", "tier2": "market_standard", "tier3": "market_low"}
        supplied_tier = legacy_tier_aliases.get(str(claim["city_tier"]), claim["city_tier"])
        if supplied_tier != configured_tier:
            return _error("invalid_claim", "city_tier does not match the configured destination directory")
        try:
            check_in = date.fromisoformat(str(claim["check_in"]))
            check_out = date.fromisoformat(str(claim["check_out"]))
            nights = int(claim["nights"])
        except (TypeError, ValueError):
            return _error("invalid_claim", "lodging dates and nights are invalid")
        if check_out <= check_in or nights != (check_out - check_in).days:
            return _error("invalid_claim", "nights must equal check_out minus check_in")
        nightly_amount = float(amount) / nights
        nightly_limit = category_facts.get("tier_limits_per_night", {}).get(configured_tier)
        if nightly_limit is None:
            return _review(normalized, "destination market has no configured lodging limit")
        if nightly_amount > float(nightly_limit) and not claim.get("pre_approved"):
            return _policy_reject(normalized, "reject_over_limit", "lodging amount exceeds the destination nightly limit")
        market_price = claim.get("market_price_per_night")
        if not isinstance(market_price, (int, float)) or isinstance(market_price, bool) or market_price <= 0:
            return _review(normalized, "lodging market reference price is required")
        threshold = float(facts.get("global_rules", {}).get("dynamic_price_review_pct", 20))
        if nightly_amount > float(market_price) * (1 + threshold / 100):
            return _review(normalized, "lodging exceeds the simulated dynamic market price threshold")
        normalized["nightly_amount"] = nightly_amount
        normalized["nightly_limit"] = float(nightly_limit)
    monthly_total = claim.get("monthly_reimbursement_total")
    if monthly_total is not None:
        if isinstance(monthly_total, bool) or not isinstance(monthly_total, (int, float)) or monthly_total < 0:
            return _error("invalid_claim", "monthly_reimbursement_total must be a non-negative number")
        global_rules = facts.get("global_rules", {})
        threshold = global_rules.get("monthly_reimbursement_review_threshold")
        if claim.get("member_group") == "e_group":
            threshold = global_rules.get("e_group_monthly_reimbursement_review_threshold", threshold)
        if threshold is not None and float(monthly_total) > float(threshold):
            return _review(normalized, "monthly reimbursement total exceeds the simulation review threshold")
    base_currency = str(facts.get("currency", "USD")).upper()
    if str(claim["currency"]).upper() != base_currency:
        normalized["currency"] = str(claim["currency"]).upper()
        return {
            "valid": True,
            "claim": normalized,
            "error_code": "needs_review",
            "errors": [f"non-{base_currency} claims require manual review"],
            "review_required": True,
        }
    return {"valid": True, "claim": normalized, "error_code": "", "errors": [], "review_required": False}
