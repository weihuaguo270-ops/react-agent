"""Thin production-oriented HTTP surface (stdlib only)."""
from __future__ import annotations

import json
import os
import traceback
import uuid
import queue
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Optional
from urllib.parse import parse_qs, urlparse

# Service defaults before heavy imports
os.environ.setdefault("REACT_AGENT_DISABLE_MCP", "1")
os.environ.setdefault("REACT_AGENT_DEFAULT_APP", "docs_troubleshoot")
os.environ.setdefault("REACT_AGENT_RAG_MODE", "keyword")

from react_agent.server.auth import (
    authorized,
    host_allowed,
    unauthenticated_exposure_warning,
)
from react_agent.server.chat_router import (
    handle_chat,
    list_applications,
    normalize_app,
    registry_pillars,
)
from react_agent.server.health import (
    confirmation_gate_startup_warning,
    liveness_payload,
    package_version,
    readiness_payload,
)
from react_agent.server.http_util import error_response
from react_agent.server.static_files import docs_troubleshoot_ui_html
from react_agent.server.streaming import (
    HEARTBEAT_SECONDS,
    install,
    query_body,
    request_cancel,
    reset,
    sse_frame,
)


class AgentHandler(BaseHTTPRequestHandler):
    server_version = f"react-agent-server/{package_version()}"

    def _send(self, status: int, payload: dict):
        raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("X-Request-Id", payload.get("request_id")
                         or (payload.get("error") or {}).get("request_id", ""))
        self.end_headers()
        self.wfile.write(raw)

    def log_message(self, fmt, *args):
        print(f"[server] {self.address_string()} {fmt % args}")

    def _bound_host(self) -> str:
        """本连接的服务器绑定地址（用于判断是否强制 Host 校验）。"""
        server = getattr(self, "server", None)
        return str(getattr(server, "server_address", ("", 0))[0] or "")

    def _prepare_request_context(self, body: dict, request_id: str) -> None:
        """把请求级上下文装进当前线程（ContextVar 不跨线程）。

        审批闸门依赖它拿到 request_id 与本次请求携带的审批凭据。
        """
        from react_agent.safety.permission_gate import (
            set_approval_credential,
            set_request_id,
        )

        set_request_id(request_id)
        set_approval_credential(str((body or {}).get("approval_id") or "").strip())

    def _reject(self, code: str, message: str, *, status: int, **headers) -> bool:
        request_id = self.headers.get("X-Request-Id") or str(uuid.uuid4())
        _, payload = error_response(code, message, request_id, status)
        raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        for name, value in headers.items():
            self.send_header(name.replace("_", "-"), value)
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("X-Request-Id", request_id)
        self.end_headers()
        self.wfile.write(raw)
        return True

    def _reject_unauthenticated(self, path: str) -> bool:
        """Return True when the request was rejected and handled."""
        # Host 头先校验：绑定回环时拒绝非回环 Host，阻断 DNS rebinding
        if not host_allowed(self, self._bound_host()):
            return self._reject(
                "invalid_host",
                "Host header is not allowed for this server binding",
                status=421,
            )
        if authorized(self, path):
            return False
        return self._reject(
            "unauthorized",
            "missing or invalid credentials",
            status=401,
            WWW_Authenticate="Bearer",
        )

    def _send_sse(self, body: dict, request_id: str):
        """Run the existing chat handler and expose request-local progress as SSE."""
        # The queue is request-scoped.  Keeping it unbounded here avoids
        # dropping the terminal ``done`` event when a long Agent emits many
        # progress updates; the client still controls the connection lifetime.
        events: queue.Queue[tuple[str, dict]] = queue.Queue()
        disconnected = threading.Event()
        # 取消信号由 worker 创建，但必须暴露给本（连接）线程使用——ContextVar
        # 不跨线程共享，只能靠直接持有同一个 Event 对象传递。
        cancel_signal: dict = {}
        sequence = 0

        def publish(event: str, data: dict):
            if disconnected.is_set():
                return
            message = dict(data or {})
            message.setdefault("request_id", request_id)
            events.put((event, message))

        def worker():
            from react_agent.llm import LLMCancelled

            # ContextVar 不跨线程：必须在 worker 内部设置，才能被 Agent 循环读到
            self._prepare_request_context(body, request_id)

            tokens, cancel_event = install(publish)
            cancel_signal["event"] = cancel_event
            try:
                publish("started", {"app": body.get("app") or body.get("application") or ""})
                status, payload = handle_chat(body, request_id)
                if "request_id" not in payload and "error" not in payload:
                    payload["request_id"] = request_id
                # Offline handlers expose completed agent_steps even when the
                # execution path has no live callback hooks.
                for index, step in enumerate(payload.get("agent_steps") or [], 1):
                    publish("step", {"step": index, "status": "completed", "detail": step})
                # 审批是状态而非消息：把「等待人工审批」显式标注出来，客户端批准后
                # 带 approval_id 重试即可，不需要长连接等待。
                from react_agent.server.health import capture_approval_status

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
                # （publish 在断连后是 no-op，这里的事件主要留给日志与单测断言）
                print(f"[server] request {request_id[:8]} cancelled by client disconnect")
                publish("cancelled", {"request_id": request_id, "reason": "client_disconnected"})
                publish("done", {"status": 499, "ok": False, "cancelled": True})
            except Exception as exc:
                traceback.print_exc()
                publish("error", {"status": 500, "error": {"code": "internal_error", "message": str(exc)[:300]}})
                publish("done", {"status": 500, "ok": False})
            finally:
                reset(tokens)

        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache, no-transform")
        self.send_header("Connection", "close")
        self.send_header("X-Accel-Buffering", "no")
        self.send_header("X-Request-Id", request_id)
        self.end_headers()
        self.close_connection = True
        thread = threading.Thread(target=worker, name=f"agent-sse-{request_id[:8]}", daemon=True)
        thread.start()
        try:
            while True:
                try:
                    event, data = events.get(timeout=HEARTBEAT_SECONDS)
                except queue.Empty:
                    self.wfile.write(
                        sse_frame("heartbeat", {"request_id": request_id, "ts": time.time()}).encode("utf-8")
                    )
                    self.wfile.flush()
                    continue
                sequence += 1
                self.wfile.write(sse_frame(event, data, str(sequence)).encode("utf-8"))
                self.wfile.flush()
                if event == "done":
                    break
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            disconnected.set()
            # 关键：不仅停止推送，还要通知 Agent 真正中止——否则客户端离开后
            # Agent 仍会跑完全部步数，空烧 LLM 调用。
            request_cancel(cancel_signal.get("event"))
        finally:
            disconnected.set()
            # 正常结束时同样置位：worker 已交付 done，再置位无副作用；
            # 若 worker 仍在收尾（例如断连后），这里保证它一定停下来。
            request_cancel(cancel_signal.get("event"))

    @staticmethod
    def _stream_query(parsed) -> dict:
        """EventSource 查询参数 → 请求体（解析逻辑与 FastAPI 面共用）。"""
        query = parse_qs(parsed.query, keep_blank_values=True)
        return query_body(
            (key, values[-1]) for key, values in query.items() if values
        )

    def do_GET(self):
        request_id = self.headers.get("X-Request-Id") or str(uuid.uuid4())
        parsed = urlparse(self.path)
        path = parsed.path
        if self._reject_unauthenticated(path):
            return
        if path == "/v1/chat/stream":
            # 请求上下文由 _send_sse 的 worker 线程设置（ContextVar 不跨线程）
            self._send_sse(self._stream_query(parsed), request_id)
            return
        if path in ("/", "/ui", "/v1/ui"):
            raw = docs_troubleshoot_ui_html()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)
            return
        if path == "/v1/info":
            default_app = normalize_app(None)
            self._send(
                200,
                {
                    "product": "react-agent",
                    "version": package_version(),
                    "default_app": default_app,
                    "applications": list_applications(),
                    # 已实现：由应用注册表派生，保证与实际可路由的 pillar 一致
                    "pillars": registry_pillars(),
                    # 对外宣称的三支柱定位（见 docs/APPLICATION_DIRECTION.md）；
                    # rag_research 目前没有绑定应用，故不出现在上面的 pillars 中
                    "declared_pillars": ["coding_execution", "support_automation", "rag_research"],
                    "default_mode": "offline"
                    if default_app != "default"
                    else "llm",
                    "features": [
                        "multi_app_chat",
                        "agent_loop_offline",
                        "react_loop_llm",
                        "harness_trajectory",
                        "chat_stream_sse",
                    ],
                    "ui_paths": ["/", "/ui"],
                    "request_id": request_id,
                },
            )
            return
        if path in ("/health", "/v1/health"):
            self._send(200, liveness_payload(request_id=request_id))
            return
        if path in ("/ready", "/v1/ready"):
            status, payload = readiness_payload(request_id=request_id)
            self._send(status, payload)
            return
        if path in ("/v1/workflows", "/v1/workflows/list"):
            from react_agent.workflow import list_workflows

            self._send(
                200,
                {"request_id": request_id, "workflows": list_workflows()},
            )
            return
        if path == "/v1/approvals":
            from react_agent.safety import approvals

            self._send(
                200,
                {
                    "request_id": request_id,
                    "mode": approvals.approval_mode(),
                    "pending": approvals.list_pending(),
                },
            )
            return
        status, payload = error_response("not_found", f"unknown path {path}", request_id, 404)
        self._send(status, payload)

    def do_POST(self):
        request_id = self.headers.get("X-Request-Id") or str(uuid.uuid4())
        path = urlparse(self.path).path
        if self._reject_unauthenticated(path):
            return
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        try:
            body = json.loads(raw.decode("utf-8") or "{}")
        except json.JSONDecodeError:
            status, payload = error_response("invalid_request", "invalid JSON body", request_id, 400)
            self._send(status, payload)
            return
        if not isinstance(body, dict):
            status, payload = error_response("invalid_request", "body must be object", request_id, 400)
            self._send(status, payload)
            return

        try:
            if path == "/v1/chat":
                self._prepare_request_context(body, request_id)
                status, payload = handle_chat(body, request_id)
                if "request_id" not in payload and "error" not in payload:
                    payload["request_id"] = request_id
                from react_agent.server.health import capture_approval_status

                approval_id = capture_approval_status(payload)
                if approval_id:
                    payload["status"] = "awaiting_approval"
                    payload["approval_id"] = approval_id
                self._send(status, payload)
                return
            if path == "/v1/chat/stream":
                self._send_sse(body, request_id)
                return
            if path.startswith("/v1/approvals/"):
                from react_agent.safety import approvals

                approval_id = path.rsplit("/", 1)[-1]
                ok, record = approvals.resolve(
                    approval_id,
                    decision=str(body.get("decision") or ""),
                    scope=str(body.get("scope") or "once"),
                    approver=str(body.get("approver") or approvals.new_approval_token()),
                )
                if not ok:
                    status, payload = error_response(
                        str(record.get("error") or "approval_error"),
                        f"cannot resolve approval {approval_id}",
                        request_id,
                        404 if record.get("error") == "approval_not_found" else 409,
                    )
                    payload["detail"] = record
                    self._send(status, payload)
                    return
                self._send(200, {"request_id": request_id, "approval": record})
                return
            if path in ("/v1/workflows", "/v1/workflows/list"):
                from react_agent.workflow import list_workflows

                self._send(
                    200,
                    {"request_id": request_id, "workflows": list_workflows()},
                )
                return
            if path == "/v1/workflows/run":
                name = (body.get("name") or "").strip()
                if not name:
                    status, payload = error_response(
                        "invalid_request", "name is required", request_id, 400
                    )
                    self._send(status, payload)
                    return
                from react_agent.workflow.tools import run_workflow_tool

                raw_out = run_workflow_tool(
                    name=name,
                    query=str(body.get("query") or ""),
                    payload_json=json.dumps(body.get("state") or {})
                    if isinstance(body.get("state"), dict)
                    else str(body.get("payload_json") or ""),
                )
                data = json.loads(raw_out)
                data["request_id"] = request_id
                self._send(200 if data.get("ok", True) else 500, data)
                return
            status, payload = error_response("not_found", f"unknown path {path}", request_id, 404)
            self._send(status, payload)
        except Exception as e:
            traceback.print_exc()
            status, payload = error_response("internal_error", str(e)[:300], request_id, 500)
            self._send(status, payload)


def serve(host: str = "127.0.0.1", port: int = 8765):
    from react_agent.apps.docs_troubleshoot.index import reset_index
    from react_agent.server.auth import (
        HostValidationError,
        host_validation_mode,
        validate_host_configuration,
    )

    # 启动期 fail-closed：严格 Host 校验模式下未声明允许域名则拒绝启动，
    # 与 REACT_AGENT_SANDBOX_REQUIRED 的失败语义保持一致。
    try:
        validate_host_configuration(host)
    except HostValidationError as exc:
        print(f"[server] FATAL: {exc}")
        raise SystemExit(2) from exc

    # 不再在启动期调用 enable_app_tools()：app 工具改为按请求作用域提供
    # （tools.set_request_app / get_registry），避免 docs 工具对其他应用可见。
    reset_index()
    httpd = ThreadingHTTPServer((host, port), AgentHandler)
    print(f"[server] listening on http://{host}:{port}")
    print(f"[server] host validation mode: {host_validation_mode()}")
    warning = unauthenticated_exposure_warning(host)
    if warning:
        print(warning)
    # 显式暴露「CONFIRM 级工具当前自动放行」——避免"以为有审批"的误判
    gate_warning = confirmation_gate_startup_warning()
    if gate_warning:
        print(gate_warning)
    print("[server] POST /v1/chat  app=default|docs_troubleshoot|expense")
    print("[server] POST/GET /v1/chat/stream  text/event-stream progress")
    print("[server] GET /v1/info  /health /ready  /  /ui")
    print("[server] REACT_AGENT_SERVER_LLM=1 for app=default (general ReAct)")
    print("[server] REACT_AGENT_SERVER_OFFLINE_REACT=1 for app=default smoke (no Key)")
    httpd.serve_forever()


def main(argv: Optional[list] = None):
    import argparse

    p = argparse.ArgumentParser(description="react-agent thin HTTP server")
    p.add_argument("--host", default=os.environ.get("REACT_AGENT_HOST", "127.0.0.1"))
    p.add_argument("--port", type=int, default=int(os.environ.get("REACT_AGENT_PORT", "8765")))
    args = p.parse_args(argv)
    serve(args.host, args.port)


if __name__ == "__main__":
    main()
