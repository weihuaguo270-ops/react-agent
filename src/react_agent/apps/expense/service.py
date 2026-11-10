"""Application service for the persistent Expense Claim lifecycle."""
from __future__ import annotations

from typing import Any, Mapping

from .store import ExpenseClaimStore, ExpenseStoreError
from .workflow import EXPENSE_WORKFLOW_NAME, run_expense_workflow


def create_claim(store: ExpenseClaimStore, payload: Mapping[str, Any], *, actor_id: str, request_id: str, idempotency_key: str) -> dict[str, Any]:
    return store.create(payload, actor_id=actor_id, request_id=request_id, idempotency_key=idempotency_key)


def get_claim(store: ExpenseClaimStore, claim_id: str, *, actor_id: str) -> dict[str, Any]:
    return store.get(claim_id, actor_id=actor_id)


def update_claim(store: ExpenseClaimStore, claim_id: str, patch: Mapping[str, Any], *, actor_id: str, expected_version: int, request_id: str, idempotency_key: str) -> dict[str, Any]:
    return store.update(claim_id, patch, actor_id=actor_id, expected_version=expected_version, request_id=request_id, idempotency_key=idempotency_key)


def submit_claim(store: ExpenseClaimStore, claim_id: str, *, actor_id: str, expected_version: int, request_id: str, idempotency_key: str) -> dict[str, Any]:
    idem_payload = {"claim_id": claim_id, "actor_id": actor_id, "expected_version": expected_version}
    replay = store.replay("submit", idempotency_key, idem_payload)
    if replay is not None:
        return replay
    return store.submit(
        claim_id,
        actor_id=actor_id,
        expected_version=expected_version,
        request_id=request_id,
        idempotency_key=idempotency_key,
        workflow_runner=lambda claim: _run_submit_workflow(claim, claim_id=claim_id, idempotency_key=idempotency_key),
    )


def _run_submit_workflow(claim: Mapping[str, Any], *, claim_id: str, idempotency_key: str) -> dict[str, Any]:
    workflow = run_expense_workflow({
        "claim": dict(claim),
        "idempotency_key": f"expense:{claim_id}:v{claim.get('version', claim.get('claim_version', 1))}:submit:{idempotency_key}",
    })
    return {"workflow": workflow.workflow, "run_id": workflow.run_id, "ok": workflow.ok, "state": workflow.state, "answer": workflow.answer, "refused": workflow.refused, "citations": workflow.citations}


def list_events(store: ExpenseClaimStore, claim_id: str, *, actor_id: str) -> list[dict[str, Any]]:
    return store.events(claim_id, actor_id=actor_id)


__all__ = ["ExpenseStoreError", "EXPENSE_WORKFLOW_NAME", "create_claim", "get_claim", "list_events", "submit_claim", "update_claim"]
