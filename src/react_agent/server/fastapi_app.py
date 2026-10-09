"""Optional FastAPI surface for task submission and durable status queries."""
from __future__ import annotations

import argparse
import asyncio
import os
import json
import threading
import time
import uuid
from contextlib import asynccontextmanager
from typing import Any, Callable

from fastapi import FastAPI, Header, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field, model_validator

from react_agent.server.auth import (
    HostValidationError,
    authorized_headers,
    host_header_allowed,
    unauthenticated_exposure_warning,
    validate_host_configuration,
)
from react_agent.server.chat_router import handle_chat, list_applications, normalize_app
from react_agent.server.health import liveness_payload, package_version, readiness_payload
from react_agent.server.http_util import error_response
from react_agent.server.static_files import docs_troubleshoot_ui_html
from react_agent.server.task_manager import TaskManager, task_manager


ChatHandler = Callable[[dict[str, Any], str], tuple[int, dict[str, Any]]]


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    message: str | None = Field(default=None, max_length=100_000)
    query: str | None = Field(default=None, max_length=100_000)
    app: str | None = Field(default=None, max_length=64)

    @model_validator(mode="after")
    def require_message(self) -> "ChatRequest":
        # Application-specific payloads (for example an expense claim) do not
        # necessarily have a free-text message.  Reject only an empty envelope.
        if not (self.message or self.query or any(
            key != "app" for key in self.model_fields_set
        )):
            raise ValueError("message, query, or application payload is required")
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


class WorkflowRunRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    name: str = Field(min_length=1, max_length=100)
    query: str = Field(default="", max_length=100_000)
    state: dict[str, Any] | None = None
    payload_json: str | None = Field(default=None, max_length=100_000)


class ApprovalDecisionRequest(BaseModel):
    """人工审批决议。

    ``decision`` / ``scope`` 刻意只做长度约束、不写成 Literal：取值语义交给
    ``safety.approvals.resolve`` 判（``invalid_decision`` / ``invalid_scope`` →
    409），与 stdlib 服务面的错误码一致；写成枚举会变成 422 校验错误，同一个
    请求在两个入口点会拿到不同的码。
    """

    model_config = ConfigDict(extra="allow")

    decision: str = Field(min_length=1, max_length=20)
    scope: str = Field(default="once", max_length=20)
    approver: str | None = Field(default=None, max_length=200)


def _request_id(value: str | None) -> str:
    return value or str(uuid.uuid4())


def _task_payload(record: Any, request_id: str) -> dict[str, Any]:
    return {"request_id": request_id, **record.public()}


def _run_chat(
    chat_handler: ChatHandler, body: dict[str, Any], request_id: str
) -> tuple[int, dict[str, Any]]:
    """跑一次对话，并在**同一个上下文**里设置/读取请求级状态。

    ContextVar 是「每上下文一份」：闸门在工具执行时写入待批信号（见
    ``approvals.note_approval_required``）与请求 id，只有读回**同一上下文**的
    ``approvals.take_pending_approval()`` 才拿得到。FastAPI 的 handler 跑在事件
    循环、真正的对话跑在线程池线程，所以「设置上下文 + 捕获审批状态」必须一起
    放进这个线程函数，不能横跨 ``run_in_threadpool`` 的边界——跨过去读会永远
    读到 None。
    """
    from react_agent.safety.permission_gate import set_approval_credential, set_request_id
    from react_agent.server.health import capture_approval_status

    set_request_id(request_id)
    # 客户端批准后带同一 approval_id 重试，闸门据此放行（once 用掉即作废）
    set_approval_credential(str(body.get("approval_id") or "").strip())

    status, payload = chat_handler(body, request_id)
    if "request_id" not in payload and "error" not in payload:
        payload["request_id"] = request_id
    # 审批是状态而非消息：把「等待人工审批」显式标注出来，客户端批准后重试即可，
    # 不需要长连接等待。
    approval_id = capture_approval_status(payload)
    if approval_id:
        payload["status"] = "awaiting_approval"
        payload["approval_id"] = approval_id
    return status, payload


def _stream_worker(
    chat_handler: ChatHandler,
    body: dict[str, Any],
    request_id: str,
    publish: Callable[[str, dict[str, Any]], None],
    cancel_signal: dict[str, Any],
) -> None:
    """在后台线程里跑一次对话，把进度事件交给 ``publish``。

    与 stdlib 面（``app._send_sse`` 的 worker）保持同一套顺序与语义：
    请求级上下文与事件 sink 都必须在**本线程内**安装，Agent 循环才读得到
    （ContextVar 不跨线程共享）；``cancel_event`` 由本线程创建后放进
    ``cancel_signal``，因为连接侧只有拿到同一个 Event 对象才能把取消送达。
    """
    from react_agent.llm import LLMCancelled
    from react_agent.safety.permission_gate import set_approval_credential, set_request_id
    from react_agent.server.health import capture_approval_status
    from react_agent.server.streaming import install, reset

    set_request_id(request_id)
    set_approval_credential(str(body.get("approval_id") or "").strip())

    tokens, cancel_event = install(publish)
    cancel_signal["event"] = cancel_event
    try:
        publish("started", {"app": body.get("app") or body.get("application") or ""})
        status, payload = chat_handler(body, request_id)
        if "request_id" not in payload and "error" not in payload:
            payload["request_id"] = request_id
        # 离线处理器只给最终 agent_steps（没有 live 回调），补发 step 事件
        for index, step in enumerate(payload.get("agent_steps") or [], 1):
            publish("step", {"step": index, "status": "completed", "detail": step})
        approval_id = capture_approval_status(payload)
        if approval_id:
            payload["status"] = "awaiting_approval"
            payload["approval_id"] = approval_id
            publish("approval_required", {"approval_id": approval_id, "request_id": request_id})
        if status >= 400 or "error" in payload:
            publish("error", {"status": status, "error": payload.get("error", payload)})
        else:
            publish("result", {"status": status, "result": payload})
        publish("done", {"status": status, "ok": status < 400})
    except LLMCancelled:
        # 客户端已断开：这是预期终止，不是错误
        publish("cancelled", {"request_id": request_id, "reason": "client_disconnected"})
        publish("done", {"status": 499, "ok": False, "cancelled": True})
    except Exception as exc:
        publish(
            "error",
            {"status": 500, "error": {"code": "internal_error", "message": str(exc)[:300]}},
        )
        publish("done", {"status": 500, "ok": False})
    finally:
        reset(tokens)


async def _chat_event_stream(chat_handler: ChatHandler, body: dict[str, Any], request_id: str):
    """把一次对话的进度事件转成 SSE 帧。

    线程与事件循环之间用 ``asyncio.Queue`` 交接：``asyncio.Queue`` 不是线程安全的，
    所以 worker 侧一律经 ``loop.call_soon_threadsafe`` 投递。空闲超过
    ``HEARTBEAT_SECONDS`` 就发一帧 ``heartbeat`` 保活；收到 ``done`` 收尾。

    生成器被回收（客户端断开）时置位取消信号：只停止推送是不够的，必须让 Agent
    真正停下来，否则用户离开后仍会跑完全部步数、空烧 LLM 调用。
    """
    from react_agent.server.streaming import HEARTBEAT_SECONDS, request_cancel, sse_frame

    loop = asyncio.get_running_loop()
    events: asyncio.Queue[tuple[str, dict[str, Any]]] = asyncio.Queue()
    disconnected = threading.Event()
    cancel_signal: dict[str, Any] = {}
    sequence = 0

    def publish(event: str, data: dict[str, Any]) -> None:
        if disconnected.is_set():
            return
        message = dict(data or {})
        message.setdefault("request_id", request_id)
        try:
            loop.call_soon_threadsafe(events.put_nowait, (event, message))
        except RuntimeError:
            # 事件循环已关闭（断连后生成器已回收）：丢弃事件并停止后续投递
            disconnected.set()

    thread = threading.Thread(
        target=_stream_worker,
        args=(chat_handler, body, request_id, publish, cancel_signal),
        name=f"agent-sse-{request_id[:8]}",
        daemon=True,
    )
    thread.start()
    try:
        while True:
            try:
                event, data = await asyncio.wait_for(events.get(), timeout=HEARTBEAT_SECONDS)
            except asyncio.TimeoutError:
                sequence += 1
                yield sse_frame(
                    "heartbeat", {"request_id": request_id, "ts": time.time()}, str(sequence)
                )
                continue
            sequence += 1
            yield sse_frame(event, data, str(sequence))
            if event == "done":
                break
    finally:
        disconnected.set()
        # 正常结束时 worker 已交付 done，再置位无副作用；断连时则保证它停下来
        request_cancel(cancel_signal.get("event"))


def _sse_response(chat_handler: ChatHandler, body: dict[str, Any], request_id: str) -> StreamingResponse:
    return StreamingResponse(
        _chat_event_stream(chat_handler, body, request_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "close",
            "X-Accel-Buffering": "no",
            "X-Request-Id": request_id,
        },
    )


def _bound_host() -> str:
    """ASGI 侧的绑定地址。

    uvicorn 不把 bind host 暴露给应用，因此按 ``REACT_AGENT_HOST`` 读取；``main()``
    会把 ``--host`` 写回该变量。取不到时按「仅回环可达」处理，即只放行本地 Host。
    """
    return os.environ.get("REACT_AGENT_HOST", "").strip()


def _authorized(request: Request) -> bool:
    """除探针（``auth.PUBLIC_PATHS``）外全接口要求凭据——与 stdlib 面同一规则。"""
    return authorized_headers(request.headers, request.url.path)


def create_app(
    *,
    manager: TaskManager | None = None,
    chat_handler: ChatHandler = handle_chat,
    initialize_runtime: bool = True,
) -> FastAPI:
    selected_manager = manager or task_manager

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        if initialize_runtime:
            from react_agent.apps.docs_troubleshoot.index import reset_index
            from react_agent.tools import enable_app_tools

            enable_app_tools()
            reset_index()
        yield

    api = FastAPI(
        title="react-agent service",
        version=package_version(),
        lifespan=lifespan,
    )

    @api.middleware("http")
    async def request_guard(request: Request, call_next):
        request_id = _request_id(request.headers.get("X-Request-Id"))
        # Host 先于鉴权：伪造 Host 且无凭据时必须回 421（Host 问题），
        # 不能回 401 暴露「该接口存在」——与 stdlib 面的顺序一致。
        if not host_header_allowed(request.headers.get("host", ""), _bound_host()):
            status, payload = error_response(
                "invalid_host",
                "Host header is not allowed for this server binding",
                request_id,
                421,
            )
            return JSONResponse(payload, status_code=status)
        if not _authorized(request):
            status, payload = error_response(
                "unauthorized", "missing or invalid credentials", request_id, 401
            )
            return JSONResponse(payload, status_code=status, headers={"WWW-Authenticate": "Bearer"})

        content_length = request.headers.get("content-length")
        max_body = int(os.environ.get("REACT_AGENT_MAX_BODY_BYTES", str(1024 * 1024)))
        if content_length:
            try:
                too_large = int(content_length) > max_body
            except ValueError:
                status, payload = error_response("invalid_request", "Content-Length must be an integer", request_id, 400)
                return JSONResponse(payload, status_code=status)
            if too_large:
                status, payload = error_response(
                    "payload_too_large", f"request body exceeds {max_body} bytes", request_id, 413
                )
                return JSONResponse(payload, status_code=status)

        response = await call_next(request)
        response.headers.setdefault("X-Request-Id", request_id)
        return response

    @api.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError):
        request_id = _request_id(request.headers.get("X-Request-Id"))
        status, payload = error_response("invalid_request", "request validation failed", request_id, 422)
        payload["error"]["details"] = jsonable_encoder(exc.errors())
        return JSONResponse(payload, status_code=status)

    @api.exception_handler(Exception)
    async def unhandled_error(request: Request, exc: Exception):
        request_id = _request_id(request.headers.get("X-Request-Id"))
        status, payload = error_response("internal_error", "internal server error", request_id, 500)
        return JSONResponse(payload, status_code=status)

    @api.get("/", response_class=Response)
    @api.get("/ui", response_class=Response)
    @api.get("/v1/ui", response_class=Response)
    async def ui() -> Response:
        return Response(docs_troubleshoot_ui_html(), media_type="text/html")

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
            ],
            "request_id": _request_id(x_request_id),
        }

    @api.get("/v1/workflows")
    @api.get("/v1/workflows/list")
    async def workflows(x_request_id: str | None = Header(default=None)) -> dict[str, Any]:
        from react_agent.workflow import list_workflows

        return {"request_id": _request_id(x_request_id), "workflows": list_workflows()}

    @api.post("/v1/workflows/run")
    async def run_workflow(
        request: WorkflowRunRequest,
        x_request_id: str | None = Header(default=None),
    ) -> JSONResponse:
        from react_agent.workflow.tools import run_workflow_tool

        request_id = _request_id(x_request_id)
        raw_out = await run_in_threadpool(
            run_workflow_tool,
            name=request.name.strip(),
            query=request.query,
            payload_json=json.dumps(request.state or {})
            if request.state is not None
            else (request.payload_json or ""),
        )
        payload = json.loads(raw_out)
        payload["request_id"] = request_id
        return JSONResponse(payload, status_code=200 if payload.get("ok", True) else 500)

    @api.post("/v1/chat")
    async def chat(
        request: ChatRequest,
        x_request_id: str | None = Header(default=None),
    ) -> JSONResponse:
        request_id = _request_id(x_request_id)
        status, payload = await run_in_threadpool(
            _run_chat, chat_handler, request.model_dump(exclude_none=True), request_id
        )
        payload.setdefault("request_id", request_id)
        return JSONResponse(payload, status_code=status)

    @api.post("/v1/chat/stream")
    async def chat_stream(
        request: ChatRequest,
        x_request_id: str | None = Header(default=None),
    ) -> StreamingResponse:
        return _sse_response(
            chat_handler, request.model_dump(exclude_none=True), _request_id(x_request_id)
        )

    @api.get("/v1/chat/stream")
    async def chat_stream_get(
        request: Request,
        x_request_id: str | None = Header(default=None),
    ) -> StreamingResponse:
        """EventSource 只能发 GET：查询参数形式，与 stdlib 面同一套解析。"""
        from react_agent.server.streaming import query_body

        body = query_body(request.query_params.multi_items())
        return _sse_response(chat_handler, body, _request_id(x_request_id))

    @api.get("/v1/approvals")
    async def pending_approvals(
        x_request_id: str | None = Header(default=None),
    ) -> dict[str, Any]:
        from react_agent.safety import approvals

        pending = await run_in_threadpool(approvals.list_pending)
        return {
            "request_id": _request_id(x_request_id),
            "mode": approvals.approval_mode(),
            "pending": pending,
        }

    @api.post("/v1/approvals/{approval_id}")
    async def resolve_approval(
        approval_id: str,
        request: ApprovalDecisionRequest,
        x_request_id: str | None = Header(default=None),
    ) -> JSONResponse:
        from react_agent.safety import approvals

        request_id = _request_id(x_request_id)
        ok, record = await run_in_threadpool(
            approvals.resolve,
            approval_id,
            decision=request.decision,
            scope=request.scope,
            approver=str(request.approver or approvals.new_approval_token()),
        )
        if not ok:
            # 与 stdlib 面同一套错误映射：找不到 404，其余（已决议/过期/取值非法）409
            status, payload = error_response(
                str(record.get("error") or "approval_error"),
                f"cannot resolve approval {approval_id}",
                request_id,
                404 if record.get("error") == "approval_not_found" else 409,
            )
            payload["detail"] = record
            return JSONResponse(payload, status_code=status)
        return JSONResponse({"request_id": request_id, "approval": record})

    @api.post("/v1/tasks", response_model=TaskResponse, status_code=202)
    async def submit_task(
        request: ChatRequest,
        x_request_id: str | None = Header(default=None),
    ):
        request_id = _request_id(x_request_id)

        def execute() -> dict[str, Any]:
            status, payload = _run_chat(
                chat_handler, request.model_dump(exclude_none=True), request_id
            )
            return {"http_status": status, "payload": payload}

        try:
            if hasattr(selected_manager, "submit_payload"):
                record = selected_manager.submit_payload(
                    request.model_dump(exclude_none=True), request_id
                )
            else:
                record = selected_manager.submit(execute)
        except RuntimeError as exc:
            unavailable = "unavailable" in str(exc).lower()
            status, payload = error_response(
                "queue_unavailable" if unavailable else "queue_full",
                str(exc),
                request_id,
                503 if unavailable else 429,
            )
            return JSONResponse(payload, status_code=status)
        return _task_payload(record, request_id)

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
    parser = argparse.ArgumentParser(description="Run the react-agent FastAPI service")
    parser.add_argument("--host", default=os.environ.get("REACT_AGENT_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("REACT_AGENT_PORT", "8765")))
    args = parser.parse_args()
    # Host 校验要知道绑定地址，而 uvicorn 不把它传给应用：写回环境变量供
    # _bound_host() 按请求读取（app 在 import 期就建好了，只能走环境变量）。
    os.environ["REACT_AGENT_HOST"] = args.host

    # 启动期 fail-closed：严格 Host 校验模式下未声明允许域名则拒绝启动，
    # 与 stdlib 面（server/app.py serve）保持同一语义。
    try:
        validate_host_configuration(args.host)
    except HostValidationError as exc:
        print(f"[server] FATAL: {exc}")
        raise SystemExit(2) from exc

    warning = unauthenticated_exposure_warning(args.host)
    if warning:
        print(warning)

    uvicorn.run(
        "react_agent.server.fastapi_app:app",
        host=args.host,
        port=args.port,
        reload=False,
    )
