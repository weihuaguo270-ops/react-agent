"""Read-only H4 projections, rebuilt solely from exported append-only audits.

Counts are observed case work and submitted Claim versions, never model success,
payment, real notification delivery, or a guarantee of SLA compliance.
"""
from __future__ import annotations

import json
from collections import Counter

from sqlalchemy import literal, select, union_all

from .handoff import TERMINAL_STATUSES


def rebuild_metrics(audit):
    """Deterministic projection of the complete exported history (no live rows)."""
    cases = {}
    breaches = set()
    breach_queues = {}
    submitted = set()
    seen = set()
    for event in audit["claim_events"]:
        if event["event_type"] == "claim_submitted":
            submitted.add((event["claim_id"], event["claim_version"]))
    events = sorted(audit["case_events"], key=lambda e: (e["case_id"], e["sequence"]))
    for event in events:
        if event["event_id"] in seen:
            continue  # Replayed export batches must not inflate counts.
        seen.add(event["event_id"])
        kind = event["event_type"]
        if kind.startswith("notification_"):
            continue
        case_id = event["case_id"]
        if kind == "case_created":
            metadata = event["metadata"]
            cases[case_id] = {"status": event["to_status"], "queue": event["queue_id"],
                "binding": (metadata["claim_id"], event["claim_version"]) if metadata.get("claim_id") else None}
        if case_id not in cases:
            raise ValueError("complete case_created history is required to rebuild metrics")
        cases[case_id].update(status=event["to_status"], queue=event["queue_id"])
        if kind in {"sla_response_breached", "sla_resolution_breached"}:
            key = (case_id, kind)
            breaches.add(key)
            breach_queues.setdefault(key, event["queue_id"] or "unrouted")
    queues = {}
    for state in cases.values():
        queue = queues.setdefault(state["queue"] or "unrouted", {
            "total_cases": 0, "pending": 0, "by_status": Counter(),
            "sla_response_breached": 0, "sla_resolution_breached": 0})
        queue["total_cases"] += 1
        queue["pending"] += state["status"] not in TERMINAL_STATUSES
        queue["by_status"][state["status"]] += 1
    for key in breaches:
        queue = queues.setdefault(breach_queues[key], {"total_cases": 0, "pending": 0,
            "by_status": Counter(), "sla_response_breached": 0, "sla_resolution_breached": 0})
        queue[key[1]] += 1
    handoffs = {s["binding"] for s in cases.values() if s["binding"] is not None}
    unbound = sum(s["binding"] is None for s in cases.values())
    missing_submissions = len(handoffs - submitted)
    complete = unbound == 0 and missing_submissions == 0
    return {
        "metric_version": "expense-handoff-audit-v1",
        "total_cases": len(cases),
        "pending": sum(s["status"] not in TERMINAL_STATUSES for s in cases.values()),
        "queues": {q: {**v, "by_status": dict(sorted(v["by_status"].items()))} for q, v in sorted(queues.items())},
        "sla_breach": {"cases": len({case_id for case_id, _ in breaches}),
            "response": sum(kind == "sla_response_breached" for _, kind in breaches),
            "resolution": sum(kind == "sla_resolution_breached" for _, kind in breaches),
            "basis": "recorded_scan_events"},
        "human_handoff": {"case_claim_versions": len(handoffs), "submitted_claim_versions": len(submitted),
            "rate": len(handoffs) / len(submitted) if complete and submitted else None,
            "unattributed_cases": unbound, "missing_submission_versions": missing_submissions,
            "status": "available" if complete and submitted else "unavailable",
            "basis": "distinct_claim_version_all_exported_history"},
    }


class CaseMetrics:
    def metrics_audit(self, *, actor):
        """One SQL statement gives a consistent cross-audit snapshot, admin only."""
        from .case_store import _timestamp
        self._notification_admin(actor)
        case, claim = self._events, self._claims_store._events
        statement = union_all(
            select(literal("case").label("source"), case.c.event_id, case.c.case_id, case.c.sequence,
                literal(None).label("claim_id"), case.c.claim_version, case.c.event_type,
                case.c.to_status, case.c.queue_id, case.c.metadata_json, case.c.created_at),
            select(literal("claim"), claim.c.event_id, literal(None), literal(None),
                claim.c.claim_id, claim.c.claim_version, claim.c.event_type,
                literal(None), literal(None), claim.c.metadata_json, claim.c.created_at))
        result = {"case_events": [], "claim_events": []}
        with self._engine.connect() as connection:
            for item in connection.execute(statement).mappings():
                event = dict(item)
                source = event.pop("source")
                event["metadata"] = json.loads(event.pop("metadata_json"))
                event["created_at"] = _timestamp(event["created_at"])
                result[source + "_events"].append(event)
        for key in result:
            result[key].sort(key=lambda e: (e["case_id"] or "", e["sequence"] or 0, e["event_id"]))
        return result

    def metrics(self, *, actor):
        return rebuild_metrics(self.metrics_audit(actor=actor))
