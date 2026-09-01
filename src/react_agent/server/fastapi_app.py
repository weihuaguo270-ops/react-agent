"""Optional FastAPI surface for task submission and durable status queries."""
from __future__ import annotations

import os
import uuid
from contextlib import asynccontextmanager
from typing import Any, Callable

from fastapi import FastAPI, Header
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, model_validator

from react_agent.server.chat_router import handle_chat, list_applications, normalize_app
from react_agent.server.health import liveness_payload, package_version, readiness_payload
from react_agent.server.http_util import error_response
from react_agent.server.task_manager import TaskManager, task_manager


ChatHandler = Callable[[dict[str, Any], str], tuple[int, dict[str, Any]]]


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    message: str | None = Field(default=None, max_length=100_000)
    query: str | None = Field(default=None, max_length=100_000)
    app: str | None = Field(default=None, max_length=64)

    @model_validator(mode="after")
    def require_message(self) -> "ChatRequest":
        if not (self.message or self.query):
            raise ValueError("message or query is required")
        return self


class TaskResponse(BaseModel):
    request_id: str
    task_id: str
    status: str
    created_at: float
    started_at: float | None = None
    finished_at: float | None = None
    result: Any = None
    error: str | None = None


class SkillRunRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    name: str = Field(min_length=1, max_length=100)
    query: str | None = Field(default=None, max_length=100_000)
    payload: dict[str, Any] = Field(default_factory=dict)


class SkillRouteRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    query: str = Field(default="", max_length=100_000)
    payload: dict[str, Any] = Field(default_factory=dict)


class SecurityCaseCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message: str | None = Field(default=None, max_length=100_000)
    query: str | None = Field(default=None, max_length=100_000)
    cve_ids: list[str] = Field(default_factory=list, max_length=20)
    iocs: list[str] = Field(default_factory=list, max_length=50)
    assets: list[dict[str, Any]] = Field(default_factory=list, max_length=100)
    sbom: dict[str, Any] | None = None

    @model_validator(mode="after")
    def require_security_input(self) -> "SecurityCaseCreateRequest":
        if not (self.message or self.query or self.cve_ids or self.iocs):
            raise ValueError("provide at least one message, CVE ID, or IOC")
        return self


class SecurityReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: str = Field(min_length=1, max_length=20)
    reviewer: str = Field(min_length=1, max_length=200)
    notes: str = Field(default="", max_length=10_000)
    expected_version: int = Field(ge=1)


def _request_id(value: str | None) -> str:
    return value or str(uuid.uuid4())


def _task_payload(record: Any, request_id: str) -> dict[str, Any]:
    return {"request_id": request_id, **record.public()}


def create_app(
    *,
    manager: TaskManager | None = None,
    chat_handler: ChatHandler = handle_chat,
    initialize_runtime: bool = True,
    security_case_store: Any | None = None,
) -> FastAPI:
    selected_manager = manager or task_manager
    selected_security_store = security_case_store
    owns_security_store = False

    def get_security_store():
        nonlocal selected_security_store, owns_security_store
        if selected_security_store is None:
            from react_agent.apps.security_triage.case_store import SecurityCaseStore

            selected_security_store = SecurityCaseStore()
            owns_security_store = True
        return selected_security_store

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        try:
            if initialize_runtime:
                from react_agent.apps.docs_troubleshoot.index import reset_index
                from react_agent.tools import enable_app_tools

                enable_app_tools()
                reset_index()
            yield
        finally:
            if owns_security_store and selected_security_store is not None:
                selected_security_store.close()

    api = FastAPI(
        title="react-agent service",
        version=package_version(),
        lifespan=lifespan,
    )

    @api.get("/health")
    @api.get("/v1/health")
    async def health(x_request_id: str | None = Header(default=None)) -> dict[str, Any]:
        return liveness_payload(request_id=_request_id(x_request_id))

    @api.get("/ready")
    @api.get("/v1/ready")
    async def ready(x_request_id: str | None = Header(default=None)) -> JSONResponse:
        status, payload = await run_in_threadpool(
            readiness_payload, request_id=_request_id(x_request_id)
        )
        return JSONResponse(payload, status_code=status)

    @api.get("/v1/info")
    async def info(x_request_id: str | None = Header(default=None)) -> dict[str, Any]:
        default_app = normalize_app(None)
        return {
            "product": "react-agent",
            "version": package_version(),
            "default_app": default_app,
            "applications": list_applications(),
            "features": [
                "business_skill_contracts",
                "progressive_skill_context",
                "security_case_persistence",
                "security_asset_correlation",
                "security_human_review",
            ],
            "request_id": _request_id(x_request_id),
        }

    @api.post("/v1/chat")
    async def chat(
        request: ChatRequest,
        x_request_id: str | None = Header(default=None),
    ) -> JSONResponse:
        request_id = _request_id(x_request_id)
        status, payload = await run_in_threadpool(
            chat_handler, request.model_dump(exclude_none=True), request_id
        )
        payload.setdefault("request_id", request_id)
        return JSONResponse(payload, status_code=status)

    @api.post("/v1/tasks", response_model=TaskResponse, status_code=202)
    async def submit_task(
        request: ChatRequest,
        x_request_id: str | None = Header(default=None),
    ):
        request_id = _request_id(x_request_id)

        def execute() -> dict[str, Any]:
            status, payload = chat_handler(request.model_dump(exclude_none=True), request_id)
            return {"http_status": status, "payload": payload}

        try:
            record = selected_manager.submit(execute)
        except RuntimeError as exc:
            status, payload = error_response("queue_full", str(exc), request_id, 429)
            return JSONResponse(payload, status_code=status)
        return _task_payload(record, request_id)

    @api.post("/v1/security/cases", status_code=201)
    async def create_security_triage_case(
        request: SecurityCaseCreateRequest,
        x_request_id: str | None = Header(default=None),
    ) -> JSONResponse:
        from react_agent.apps.security_triage.case_service import create_security_case

        request_id = _request_id(x_request_id)
        try:
            record = await run_in_threadpool(
                create_security_case,
                get_security_store(),
                request.model_dump(exclude_none=True),
            )
        except ValueError as exc:
            status, payload = error_response("invalid_security_case", str(exc), request_id, 422)
            return JSONResponse(payload, status_code=status)
        return JSONResponse({"request_id": request_id, **record}, status_code=201)

    @api.get("/v1/security/cases/{case_id}")
    async def get_security_triage_case(
        case_id: str,
        x_request_id: str | None = Header(default=None),
    ) -> JSONResponse:
        request_id = _request_id(x_request_id)
        record = await run_in_threadpool(get_security_store().get, case_id)
        if record is None:
            status, payload = error_response("not_found", "security case not found", request_id, 404)
            return JSONResponse(payload, status_code=status)
        return JSONResponse({"request_id": request_id, **record})

    @api.post("/v1/security/cases/{case_id}/reviews")
    async def review_security_triage_case(
        case_id: str,
        request: SecurityReviewRequest,
        x_request_id: str | None = Header(default=None),
    ) -> JSONResponse:
        from react_agent.apps.security_triage.case_store import (
            SecurityCaseConflict,
            SecurityCaseNotFound,
        )

        request_id = _request_id(x_request_id)
        payload = request.model_dump()
        expected_version = payload.pop("expected_version")
        try:
            record = await run_in_threadpool(
                get_security_store().review,
                case_id,
                expected_version=expected_version,
                review=payload,
            )
        except SecurityCaseNotFound:
            status, error = error_response("not_found", "security case not found", request_id, 404)
            return JSONResponse(error, status_code=status)
        except SecurityCaseConflict as exc:
            status, error = error_response("case_version_conflict", str(exc), request_id, 409)
            return JSONResponse(error, status_code=status)
        except ValueError as exc:
            status, error = error_response("invalid_security_review", str(exc), request_id, 422)
            return JSONResponse(error, status_code=status)
        return JSONResponse({"request_id": request_id, **record})

    @api.get("/v1/security/cases/{case_id}/reviews")
    async def list_security_triage_reviews(
        case_id: str,
        x_request_id: str | None = Header(default=None),
    ) -> JSONResponse:
        from react_agent.apps.security_triage.case_store import SecurityCaseNotFound

        request_id = _request_id(x_request_id)
        try:
            reviews = await run_in_threadpool(get_security_store().list_reviews, case_id)
        except SecurityCaseNotFound:
            status, error = error_response("not_found", "security case not found", request_id, 404)
            return JSONResponse(error, status_code=status)
        return JSONResponse({"request_id": request_id, "case_id": case_id, "reviews": reviews})

    @api.get("/v1/skills")
    async def skills(x_request_id: str | None = Header(default=None)) -> dict[str, Any]:
        from react_agent.skills import list_skills

        return {
            "request_id": _request_id(x_request_id),
            "skills": list_skills(detail="summary"),
        }

    @api.get("/v1/skills/{name}")
    async def skill_context(
        name: str,
        level: str = "summary",
        x_request_id: str | None = Header(default=None),
    ) -> JSONResponse:
        try:
            from react_agent.skills import get_skill_context

            context = get_skill_context(name, level=level)
        except (KeyError, ValueError) as exc:
            status, payload = error_response("invalid_request", str(exc), _request_id(x_request_id), 400)
            return JSONResponse(payload, status_code=status)
        return JSONResponse({"request_id": _request_id(x_request_id), "context": context})

    @api.post("/v1/skills/route")
    async def route_business_skill(
        request: SkillRouteRequest,
        x_request_id: str | None = Header(default=None),
    ) -> JSONResponse:
        from react_agent.skills import route_skill_decision

        payload = dict(request.payload)
        for key, value in request.model_dump(exclude={"query", "payload"}).items():
            payload.setdefault(key, value)
        try:
            decision = route_skill_decision(request.query, payload)
        except ValueError as exc:
            status, payload_out = error_response("routing_failed", str(exc), _request_id(x_request_id), 422)
            return JSONResponse(payload_out, status_code=status)
        return JSONResponse({"request_id": _request_id(x_request_id), "route": decision.to_dict()})

    @api.post("/v1/skills/run")
    async def run_business_skill(
        request: SkillRunRequest,
        x_request_id: str | None = Header(default=None),
    ) -> JSONResponse:
        from react_agent.skills import get_skill, run_skill

        request_id = _request_id(x_request_id)
        try:
            skill = get_skill(request.name)
        except KeyError as exc:
            status, payload = error_response("not_found", str(exc), request_id, 404)
            return JSONResponse(payload, status_code=status)
        if skill.risk_level != "read_only" or not skill.agent_callable:
            status, payload = error_response(
                "skill_requires_controlled_caller",
                f"skill {request.name} requires an explicit controlled caller",
                request_id,
                403,
            )
            return JSONResponse(payload, status_code=status)
        payload = dict(request.payload)
        if request.query and "query" not in payload:
            payload["query"] = request.query
        result = await run_in_threadpool(run_skill, request.name, payload)
        return JSONResponse({"request_id": request_id, **result.to_dict()}, status_code=200 if result.ok else 422)

    @api.get("/v1/tasks/{task_id}", response_model=TaskResponse)
    async def get_task(
        task_id: str,
        x_request_id: str | None = Header(default=None),
    ):
        request_id = _request_id(x_request_id)
        record = selected_manager.get(task_id)
        if record is None:
            status, payload = error_response("not_found", "task not found", request_id, 404)
            return JSONResponse(payload, status_code=status)
        return _task_payload(record, request_id)

    @api.delete("/v1/tasks/{task_id}", response_model=TaskResponse)
    async def cancel_task(
        task_id: str,
        x_request_id: str | None = Header(default=None),
    ):
        request_id = _request_id(x_request_id)
        record = selected_manager.cancel(task_id)
        if record is None:
            status, payload = error_response("not_found", "task not found", request_id, 404)
            return JSONResponse(payload, status_code=status)
        return _task_payload(record, request_id)

    return api


app = create_app()


def main() -> None:
    try:
        import uvicorn
    except ImportError as exc:
        raise RuntimeError("install react-agent[service] to run FastAPI") from exc
    uvicorn.run(
        "react_agent.server.fastapi_app:app",
        host=os.environ.get("REACT_AGENT_HOST", "127.0.0.1"),
        port=int(os.environ.get("REACT_AGENT_PORT", "8765")),
        reload=False,
    )
