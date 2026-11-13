"""S6 HTTP adapter. Bearer is service auth; actor grants come only from server config."""
from __future__ import annotations

import json
import os
import uuid
from dataclasses import asdict
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Header
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from react_agent.apps.expense.case_metrics import rebuild_metrics
from react_agent.apps.expense.case_store import CaseActor
from react_agent.apps.expense.handoff import Role, load_routing_config
from react_agent.apps.expense.store import ExpenseStoreError
from react_agent.server.http_util import error_response

DEFAULT_ROUTING = Path(__file__).resolve().parents[3] / "fixtures/expense/handoff_routing_v1.json"


def server_routing():
    try:
        return load_routing_config(os.environ.get("REACT_AGENT_EXPENSE_CASE_ROUTING_FILE") or DEFAULT_ROUTING)
    except (OSError, ValueError) as exc:
        # Never let S5's no-database ValueError compatibility fallback turn a
        # malformed configured route into process-local approval handling.
        raise ExpenseStoreError("invalid_routing_config", "server routing configuration unavailable", status_code=503) from exc


def server_actor(actor_id: str | None) -> CaseActor:
    if not actor_id or not actor_id.strip():
        raise ExpenseStoreError("case_not_found", "expense case not found", status_code=404)
    actor_id = actor_id.strip()
    path = os.environ.get("REACT_AGENT_EXPENSE_CASE_ACTORS_FILE")
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8")) if path else {}
        if not isinstance(raw, dict):
            raise ValueError("actor directory must be an object")
        directory = {key: CaseActor(key, **value) for key, value in raw.items()}
    except (OSError, ValueError, TypeError, ExpenseStoreError) as exc:
        raise ExpenseStoreError("identity_unavailable", "server actor configuration unavailable", status_code=503) from exc
    return directory.get(actor_id, CaseActor(actor_id))


class CaseRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class CreateCaseRequest(CaseRequest):
    claim_id: str = Field(min_length=1, max_length=128)
    claim_version: int = Field(ge=1)
    decision_hash: str = Field(min_length=10, max_length=200)
    approval_id: str | None = Field(default=None, min_length=1, max_length=128)
    reason_code: str | None = Field(default=None, max_length=80)
    reason: str = Field(default="", max_length=500)
    suggested_queue: str | None = Field(default=None, max_length=80)


class CaseActionRequest(CaseRequest):
    expected_case_version: int = Field(ge=1)
    reason: str | None = Field(default=None, max_length=500)
    target_queue_id: str | None = Field(default=None, max_length=80)
    claim_version: int | None = Field(default=None, ge=1)
    decision_hash: str | None = Field(default=None, max_length=200)
    evidence_ref: str | None = Field(default=None, max_length=128)


class ResolveCaseRequest(CaseRequest):
    decision: Literal["approve", "reject", "complete"]
    approval_id: str | None  # Explicit null is required for work-only completion.
    claim_version: int = Field(ge=1)
    decision_hash: str = Field(min_length=10, max_length=200)
    expected_case_version: int = Field(ge=1)
    reason: str = Field(min_length=1, max_length=500)


def register_case_routes(api, store_provider):
    router = APIRouter(prefix="/v1/expense")

    async def execute(operation, *, actor_id, request_id, key=None, write=False, credential=""):
        request_id = request_id or str(uuid.uuid4())

        def run():
            from react_agent.safety.permission_gate import set_approval_credential, set_request_id

            actor = server_actor(actor_id)
            if write and (not key or not key.strip()):
                raise ExpenseStoreError("invalid_request", "Idempotency-Key is required", status_code=400)
            claims = store_provider()
            cases = claims._handoff_cases
            set_request_id(request_id)
            set_approval_credential(credential or "")
            try:
                return operation(cases, actor, request_id, (key or "").strip())
            finally:
                set_approval_credential("")

        try:
            result = await run_in_threadpool(run)
            return JSONResponse({"request_id": request_id, **result})
        except (ExpenseStoreError, ValueError, OSError) as exc:
            code, status_code = getattr(exc, "code", "storage_unavailable"), getattr(exc, "status_code", 503)
            # Do not reveal case or related Claim/approval existence to unauthorized actors.
            if code in {"queue_not_allowed", "permission_denied", "forbidden_claim_access", "claim_not_found"}:
                code, status_code = "case_not_found", 404
            status, payload = error_response(code, "expense case not found" if code == "case_not_found" else str(exc), request_id, status_code)
            return JSONResponse(payload, status_code=status)

    @router.post("/cases")
    async def create_case(request: CreateCaseRequest,
                          actor_id: str | None = Header(default=None, alias="X-Actor-Id"),
                          key: str | None = Header(default=None, alias="Idempotency-Key"),
                          request_id: str | None = Header(default=None, alias="X-Request-Id")):
        def create(cases, actor, rid, key):
            # suggested_queue/reason are hints/display text only; v1 routes by persisted reason.
            result = cases.create(request.claim_id, claim_version=request.claim_version,
                decision_hash=request.decision_hash, approval_id=request.approval_id,
                bind_pending_approval="approval_id" not in request.model_fields_set,
                reason_code=request.reason_code, actor=actor, routing=cases._claims_store._handoff_routing,
                request_id=rid, idempotency_key=key, request_payload=request.model_dump(exclude_unset=True))
            return {"case": result}
        return await execute(create, actor_id=actor_id, request_id=request_id, key=key, write=True)

    @router.get("/cases")
    async def list_cases(actor_id: str | None = Header(default=None, alias="X-Actor-Id"),
                         request_id: str | None = Header(default=None, alias="X-Request-Id")):
        return await execute(lambda cases, actor, rid, key: {"cases": cases.list_cases(actor=actor)},
            actor_id=actor_id, request_id=request_id)

    @router.get("/cases/{case_id}")
    async def get_case(case_id: str, actor_id: str | None = Header(default=None, alias="X-Actor-Id"),
                       request_id: str | None = Header(default=None, alias="X-Request-Id")):
        return await execute(lambda cases, actor, rid, key: {"case": cases.get(case_id, actor=actor)},
            actor_id=actor_id, request_id=request_id)

    @router.get("/cases/{case_id}/events")
    async def case_events(case_id: str, actor_id: str | None = Header(default=None, alias="X-Actor-Id"),
                          request_id: str | None = Header(default=None, alias="X-Request-Id")):
        return await execute(lambda cases, actor, rid, key: {"events": cases.events(case_id, actor=actor)},
            actor_id=actor_id, request_id=request_id)

    @router.post("/cases/{case_id}/resolve")
    async def resolve_case(case_id: str, request: ResolveCaseRequest,
                           actor_id: str | None = Header(default=None, alias="X-Actor-Id"),
                           key: str | None = Header(default=None, alias="Idempotency-Key"),
                           request_id: str | None = Header(default=None, alias="X-Request-Id"),
                           credential: str | None = Header(default=None, alias="X-Approval-Credential")):
        return await execute(lambda cases, actor, rid, key: {"case": cases.resolve_case(case_id,
            actor=actor, request_id=rid, idempotency_key=key, **request.model_dump())},
            actor_id=actor_id, request_id=request_id, key=key, write=True, credential=credential)

    def action_endpoint(action):
        async def case_action(case_id: str,
                              request: CaseActionRequest,
                              actor_id: str | None = Header(default=None, alias="X-Actor-Id"),
                              key: str | None = Header(default=None, alias="Idempotency-Key"),
                              request_id: str | None = Header(default=None, alias="X-Request-Id")):
            def act(cases, actor, rid, key):
                methods = {"claim": "claim_case", "release": "release_case", "transfer": "transfer_case",
                    "escalate": "escalate_case", "start": "start_case",
                    "needs_applicant": "request_applicant", "resume": "resume_case"}
                args = dict(actor=actor, expected_case_version=request.expected_case_version,
                    request_id=rid, idempotency_key=key)
                if action in {"claim", "transfer", "escalate", "resume"}:
                    args["routing"] = cases._claims_store._handoff_routing
                if action in {"release", "transfer", "escalate", "needs_applicant", "resume"}:
                    args["reason"] = request.reason
                if action == "transfer":
                    args["target_queue_id"] = request.target_queue_id
                if action == "resume":
                    args.update(claim_version=request.claim_version, decision_hash=request.decision_hash,
                        evidence_ref=request.evidence_ref)
                return {"case": getattr(cases, methods[action])(case_id, **args)}
            return await execute(act, actor_id=actor_id, request_id=request_id, key=key, write=True)

        return case_action

    for action in ("claim", "release", "transfer", "escalate", "start", "needs_applicant", "resume"):
        router.add_api_route(f"/cases/{{case_id}}/{action}", action_endpoint(action), methods=["POST"],
            name="expense_case_" + action)

    @router.get("/queues")
    async def queues(actor_id: str | None = Header(default=None, alias="X-Actor-Id"),
                     request_id: str | None = Header(default=None, alias="X-Request-Id")):
        def summary(cases, actor, rid, key):
            routing = cases._claims_store._handoff_routing
            visible = [q for q in routing.queues if actor.role == Role.FINANCE_ADMIN or
                (q.queue_id in actor.queue_ids and actor.role in q.allowed_roles)]
            audit = {"case_events": [], "claim_events": []}
            for case in cases.list_cases(actor=actor):
                audit["case_events"].extend(cases.events(case["case_id"], actor=actor))
            metrics = rebuild_metrics(audit)
            return {"routing_rule_version": routing.routing_rule_version,
                "queues": [{**asdict(q), "summary": metrics["queues"].get(q.queue_id, {
                    "total_cases": 0, "pending": 0, "by_status": {},
                    "sla_response_breached": 0, "sla_resolution_breached": 0})} for q in visible]}
        return await execute(summary, actor_id=actor_id, request_id=request_id)

    api.include_router(router)
