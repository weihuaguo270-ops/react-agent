"""H1 storage smoke, in an isolated schema of the existing project PostgreSQL.

Run prepare, restart the VERIFIED project PostgreSQL container externally, then
run finish with the same state file. This script never creates/restarts Docker
containers. Synthetic structured Decisions exercise storage, not live routing.
The finish phase drops only the generated schema after all assertions pass.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import uuid
from pathlib import Path

from sqlalchemy import create_engine, select, text, update
from sqlalchemy.exc import DBAPIError

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src"))


def main() -> int:
    from react_agent.apps.expense.case_store import CaseActor, ExpenseCaseStore
    from react_agent.apps.expense.domain import Decision, Handoff
    from react_agent.apps.expense.handoff import load_routing_config
    from react_agent.apps.expense.store import ExpenseClaimStore, ExpenseStoreError

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-url", default=os.environ.get("REACT_AGENT_DATABASE_URL"))
    parser.add_argument("--phase", choices=("prepare", "finish"), required=True)
    parser.add_argument("--state-file", type=Path, required=True, help="synthetic state only; no database credentials")
    args = parser.parse_args()
    if not args.database_url:
        parser.error("--database-url or REACT_AGENT_DATABASE_URL is required")
    admin = create_engine(args.database_url, pool_pre_ping=True)
    if admin.dialect.name != "postgresql":
        parser.error("this smoke requires PostgreSQL")
    if args.phase == "prepare" and args.state_file.exists():
        parser.error("state file exists; preserve it for recovery or choose another path")
    state = (json.loads(args.state_file.read_text(encoding="utf-8")) if args.phase == "finish" else
             {"schema": "expense_h1_smoke_" + uuid.uuid4().hex})
    schema = state["schema"]
    if not re.fullmatch(r"expense_h1_smoke_[a-f0-9]{32}", schema):
        parser.error("refusing non-smoke schema")
    with admin.begin() as connection:
        started = connection.execute(text("SELECT pg_postmaster_start_time()")).scalar_one().isoformat()
        if args.phase == "prepare":
            connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    if args.phase == "prepare":
        # Preserve recovery coordinates even if storage initialization fails.
        state["postmaster_started_at"] = started
        args.state_file.parent.mkdir(parents=True, exist_ok=True)
        args.state_file.write_text(json.dumps(state), encoding="utf-8")
    engine = create_engine(args.database_url, pool_pre_ping=True, connect_args={"options": f"-csearch_path={schema}"})
    claims = ExpenseClaimStore(engine=engine)
    cases = ExpenseCaseStore(claims)
    routing = load_routing_config(ROOT / "fixtures/expense/handoff_routing_v1.json")
    owner = CaseActor("employee-h1-smoke")
    auditor = CaseActor("finance-h1-smoke", "finance_admin")
    try:
        if args.phase == "prepare":
            # On failure retain the isolated schema and state for diagnosis.
            claim = claims.create({
                "category": "meal", "amount": 128, "currency": "USD",
                "occurred_on": "2026-11-12", "description": "synthetic H1 restart smoke",
                "has_receipt": True, "receipt_refs": ["receipt-h1-smoke"],
            }, actor_id=owner.actor_id, request_id="smoke-create", idempotency_key="smoke-create")
            decision = Decision(
                decision="needs_review", reasons=("synthetic H1 storage smoke",),
                decision_source="rules", decision_model="expense-h1-smoke-v1", rule_result="matched",
                review_required=True, handoff=Handoff("receipt_manual_verification", "medium", "100-500"),
                claim_id=claim["claim_id"], claim_version=1, policy_version="expense-policy-sim-v1",
            )
            claims.submit(claim["claim_id"], actor_id=owner.actor_id, expected_version=1,
                request_id="smoke-submit", idempotency_key="smoke-submit",
                workflow_runner=lambda _: {"ok": True, "state": {"decision": decision.to_dict()}})
            binding = dict(claim_id=claim["claim_id"], claim_version=1, decision_hash=decision.decision_hash)
            case = cases.create(**binding, actor=owner, routing=routing, request_id="smoke-case")
            cases.append_event(case["case_id"], actor=owner, request_id="smoke-evidence",
                idempotency_key="receipt-added", evidence_ref="receipt:h1-smoke")
            state.update(binding=binding, case=case, events=cases.events(case["case_id"], actor=owner),
                outbox=cases.outbox(case["case_id"], actor=auditor),
                claim=claims.get(claim["claim_id"], actor_id=owner.actor_id),
                claim_events=claims.events(claim["claim_id"], actor_id=owner.actor_id),
                reviews=claims.list_reviews(claim_id=claim["claim_id"]))
            args.state_file.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
            print(json.dumps({"phase": "prepare", "schema": schema, "case_id": case["case_id"],
                "synthetic": True, "restart_verified": False}))
            return 0
        assert started != state["postmaster_started_at"], "PostgreSQL has not restarted since prepare"
        case_id = state["case"]["case_id"]
        assert cases.get(case_id, actor=owner) == state["case"]
        assert cases.events(case_id, actor=owner) == state["events"]
        assert cases.outbox(case_id, actor=auditor) == state["outbox"]
        replay = cases.create(**state["binding"], actor=owner, routing=routing, request_id="smoke-replay")
        assert replay == {**state["case"], "idempotent_replay": True}
        cases.append_event(case_id, actor=owner, request_id="smoke-replay",
            idempotency_key="receipt-added", evidence_ref="receipt:h1-smoke")
        assert cases.events(case_id, actor=owner) == state["events"]
        assert cases.outbox(case_id, actor=auditor) == state["outbox"]
        for actor in (CaseActor("other-employee"), CaseActor("outsider", "finance_reviewer")):
            try:
                cases.get(case_id, actor=actor)
            except ExpenseStoreError as exc:
                assert exc.code == "case_not_found" and exc.status_code == 404
            else:
                raise AssertionError("unauthorized case lookup succeeded")
        try:
            with engine.begin() as connection:
                connection.execute(update(cases._events).values(metadata_json="{}"))
        except DBAPIError as exc:
            assert "append-only" in str(exc)
        else:
            raise AssertionError("event mutation succeeded")
        assert cases.events(case_id, actor=owner) == state["events"]
        assert claims.get(state["binding"]["claim_id"], actor_id=owner.actor_id) == state["claim"]
        assert claims.events(state["binding"]["claim_id"], actor_id=owner.actor_id) == state["claim_events"]
        assert claims.list_reviews(claim_id=state["binding"]["claim_id"]) == state["reviews"]
        with engine.connect() as connection:
            assert len(connection.execute(select(cases._cases)).all()) == 1
        claims.close()
        with admin.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        print(json.dumps({"ok": True, "case_id": case_id, "synthetic": True,
            "restart_verified": True, "events": len(state["events"]),
            "outbox_pending": len(state["outbox"]), "schema_removed": schema}))
        return 0
    finally:
        claims.close()
        admin.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
