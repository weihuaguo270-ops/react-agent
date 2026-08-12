"""Stateful expense operations used by the business-task evaluation suite."""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any

from .offline_answer import decide


@dataclass
class ExpenseLedger:
    """Small deterministic system of record for evaluating Agent side effects."""

    claims: dict[str, dict[str, Any]] = field(default_factory=dict)
    audit_events: list[dict[str, Any]] = field(default_factory=list)

    @classmethod
    def from_claims(cls, claims: list[dict[str, Any]]) -> "ExpenseLedger":
        records = {}
        for raw in claims:
            claim = copy.deepcopy(raw)
            claim_id = str(claim.pop("id"))
            claim.pop("expect", None)
            claim.setdefault("status", "pending")
            claim.setdefault("decision", "")
            records[claim_id] = claim
        return cls(claims=records)

    def inspect_claim(self, claim_id: str) -> dict[str, Any]:
        if claim_id not in self.claims:
            raise KeyError(f"unknown claim: {claim_id}")
        return copy.deepcopy(self.claims[claim_id])

    def decide_claim(
        self,
        claim_id: str,
        *,
        limits: dict[str, float],
        idempotency_key: str,
    ) -> dict[str, Any]:
        if not idempotency_key:
            raise ValueError("idempotency_key is required")
        for event in self.audit_events:
            if event["idempotency_key"] == idempotency_key:
                if event["claim_id"] != claim_id:
                    raise ValueError("idempotency_key already belongs to another claim")
                return copy.deepcopy(event["result"])

        claim = self.inspect_claim(claim_id)
        if claim["status"] != "pending":
            raise ValueError(f"claim is already finalized: {claim_id}")
        decision = decide(claim, limits)
        status = "rejected" if decision.startswith("reject") else "approved"
        self.claims[claim_id]["status"] = status
        self.claims[claim_id]["decision"] = decision
        result = {
            "claim_id": claim_id,
            "status": status,
            "decision": decision,
        }
        self.audit_events.append(
            {
                "claim_id": claim_id,
                "idempotency_key": idempotency_key,
                "result": copy.deepcopy(result),
            }
        )
        return result

    def snapshot(self, claim_id: str) -> dict[str, Any]:
        return {
            "claim": self.inspect_claim(claim_id),
            "audit": {
                "decision_events": sum(
                    event["claim_id"] == claim_id for event in self.audit_events
                )
            },
        }
