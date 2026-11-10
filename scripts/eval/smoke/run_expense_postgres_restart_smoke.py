"""Run the Expense Claim persistence and review smoke against PostgreSQL.

The smoke uses the configured database as the source of truth, closes and
reopens the SQL store, and optionally restarts the repository Compose service.
It only creates one uniquely identified synthetic claim and removes its rows
before exiting.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import uuid
from pathlib import Path

from sqlalchemy import text

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src"))


def _claim(actor_id: str) -> dict[str, object]:
    return {
        "category": "meal",
        "amount": 128,
        "currency": "EUR",
        "occurred_on": "2026-10-12",
        "description": "PostgreSQL restart smoke",
        "business_purpose": "synthetic persistence verification",
        "has_receipt": True,
        "receipt_refs": ["restart-smoke-receipt"],
        "pre_approved": False,
        "expense_type": "business_meal",
        "participants": [actor_id],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database-url", default=os.environ.get("REACT_AGENT_DATABASE_URL"))
    parser.add_argument("--restart-container", action="store_true")
    parser.add_argument("--phase", choices=("full", "prepare", "finish"), default="full")
    parser.add_argument("--state-json", help="state emitted by the prepare phase")
    args = parser.parse_args()
    if not args.database_url:
        parser.error("--database-url or REACT_AGENT_DATABASE_URL is required")
    if args.phase == "finish" and not args.state_json:
        parser.error("--state-json is required for the finish phase")

    from react_agent.apps.expense.service import submit_claim
    from react_agent.apps.expense.store import ExpenseClaimStore

    store = ExpenseClaimStore(args.database_url)
    if args.phase == "finish":
        state = json.loads(args.state_json)
    else:
        actor_id = "expense-restart-smoke"
        suffix = uuid.uuid4().hex
        keys = {name: f"expense-restart:{suffix}:{name}" for name in ("create", "update", "submit", "resolve")}
        created = store.create(_claim(actor_id), actor_id=actor_id, request_id=f"{suffix}:create", idempotency_key=keys["create"])
        updated = store.update(created["claim_id"], {"amount": 140}, actor_id=actor_id, expected_version=1, request_id=f"{suffix}:update", idempotency_key=keys["update"])
        submitted = submit_claim(store, created["claim_id"], actor_id=actor_id, expected_version=updated["version"], request_id=f"{suffix}:submit", idempotency_key=keys["submit"])
        assert submitted["status"] == "under_review"
        assert submitted["approval_id"]
        state = {
            "actor_id": actor_id,
            "claim_id": created["claim_id"],
            "approval_id": submitted["approval_id"],
            "version": updated["version"],
            "decision_hash": submitted["review"]["decision"]["decision_hash"],
            "keys": keys,
            "suffix": suffix,
        }
        store.close()
        if args.phase == "prepare":
            print(json.dumps(state, ensure_ascii=False))
            return 0

    if args.phase == "full" and args.restart_container:
        subprocess.run(["docker", "compose", "restart", "postgres"], cwd=ROOT, check=True)

    reopened = ExpenseClaimStore(args.database_url)
    pending = reopened.get(state["claim_id"], actor_id=state["actor_id"])
    assert pending["status"] == "under_review"
    resolved = reopened.resolve_review(
        state["approval_id"], decision="approve", approver_id="restart-smoke-manager",
        claim_id=state["claim_id"], expected_version=state["version"], decision_hash=state["decision_hash"],
        request_id=f"{state['suffix']}:resolve", idempotency_key=state["keys"]["resolve"], comment="restart smoke",
    )
    assert resolved["status"] == "approved"
    reopened.close()

    final_store = ExpenseClaimStore(args.database_url)
    final = final_store.get(state["claim_id"], actor_id=state["actor_id"])
    events = final_store.events(state["claim_id"], actor_id=state["actor_id"])
    assert final["status"] == "approved"
    assert [event["event_type"] for event in events] == [
        "claim_created", "claim_updated", "claim_submitted", "review_routed", "review_resolved",
    ]
    with final_store._engine.begin() as connection:
        for table, column in (
            ("expense_claim_events", "claim_id"), ("expense_claim_decisions", "claim_id"),
            ("expense_claim_versions", "claim_id"), ("expense_claim_reviews", "claim_id"),
            ("expense_claims", "claim_id"),
        ):
            connection.execute(text(f"DELETE FROM {table} WHERE {column} = :claim_id"), {"claim_id": state["claim_id"]})
        for key in state["keys"].values():
            connection.execute(text("DELETE FROM expense_claim_idempotency WHERE idempotency_key = :key"), {"key": key})
        connection.execute(text("DELETE FROM expense_claim_idempotency WHERE idempotency_key = :key"), {"key": state["keys"]["submit"] + ":route"})
    final_store.close()
    print(json.dumps({"ok": True, "claim_id": state["claim_id"], "status": final["status"], "events": [event["event_type"] for event in events]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
