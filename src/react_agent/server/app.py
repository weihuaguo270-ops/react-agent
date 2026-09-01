"""Thin production-oriented HTTP surface (stdlib only)."""
from __future__ import annotations

import json
import os
import traceback
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Optional
from urllib.parse import parse_qs, urlparse

# Service defaults before heavy imports
os.environ.setdefault("REACT_AGENT_DISABLE_MCP", "1")
os.environ.setdefault("REACT_AGENT_DEFAULT_APP", "docs_troubleshoot")
os.environ.setdefault("REACT_AGENT_RAG_MODE", "keyword")

MAX_BODY_BYTES = int(os.environ.get("REACT_AGENT_MAX_BODY_BYTES", str(1024 * 1024)))

from react_agent.server.chat_router import handle_chat, list_applications, normalize_app
from react_agent.server.health import liveness_payload, package_version, readiness_payload
from react_agent.server.http_util import error_response
from react_agent.server.static_files import docs_troubleshoot_ui_html
from react_agent.server.task_manager import task_manager


def _run_async_chat(body: dict, request_id: str) -> dict:
    """将内部 ``(status, payload)`` 转成可查询的稳定任务结果。"""
    status, payload = handle_chat(body, request_id)
    return {"http_status": status, "payload": payload}


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

    def _start_sse(self):
        """打开 SSE 响应；事件按完成阶段写出，客户端可立即显示 started。"""
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        # 当前请求结束后关闭连接，避免标准库客户端等待未知长度的事件流。
        self.send_header("Connection", "close")
        self.end_headers()

    def _write_sse(self, event: str, data: dict):
        raw = (f"event: {event}\n"
               f"data: {json.dumps(data, ensure_ascii=False)}\n\n").encode("utf-8")
        self.wfile.write(raw)
        self.wfile.flush()

    def log_message(self, fmt, *args):
        print(f"[server] {self.address_string()} {fmt % args}")

    def do_GET(self):
        request_id = self.headers.get("X-Request-Id") or str(uuid.uuid4())
        path = urlparse(self.path).path
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
                    "pillars": ["coding_execution", "support_automation", "rag_research"],
                    "default_mode": "offline"
                    if default_app != "default"
                    else "llm",
                    "features": [
                        "multi_app_chat",
                        "agent_loop_offline",
                        "react_loop_llm",
                        "harness_trajectory",
                        "business_skill_contracts",
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
        if path == "/v1/skills":
            from react_agent.skills import list_skills

            self._send(
                200,
                {"request_id": request_id, "skills": list_skills(detail="summary")},
            )
            return
        if path.startswith("/v1/skills/"):
            name = path.rsplit("/", 1)[-1]
            query = parse_qs(urlparse(self.path).query)
            level = (query.get("level") or ["summary"])[0]
            try:
                from react_agent.skills import get_skill_context

                context = get_skill_context(name, level=level)
            except (KeyError, ValueError) as exc:
                status, payload = error_response("invalid_request", str(exc), request_id, 400)
                self._send(status, payload)
                return
            self._send(200, {"request_id": request_id, "context": context})
            return
        if path.startswith("/v1/tasks/"):
            task_id = path.rsplit("/", 1)[-1]
            record = task_manager.get(task_id)
            if record is None:
                status, payload = error_response("not_found", "task not found", request_id, 404)
                self._send(status, payload)
            else:
                self._send(200, {"request_id": request_id, **record.public()})
            return
        status, payload = error_response("not_found", f"unknown path {path}", request_id, 404)
        self._send(status, payload)

    def do_POST(self):
        request_id = self.headers.get("X-Request-Id") or str(uuid.uuid4())
        path = urlparse(self.path).path
        raw_length = self.headers.get("Content-Length") or "0"
        try:
            length = int(raw_length)
        except (TypeError, ValueError):
            status, payload = error_response(
                "invalid_request", "Content-Length must be an integer", request_id, 400
            )
            self._send(status, payload)
            return
        if length < 0:
            status, payload = error_response(
                "invalid_request", "Content-Length must not be negative", request_id, 400
            )
            self._send(status, payload)
            return
        if length > MAX_BODY_BYTES:
            # Drain modest oversized bodies so clients receive a deterministic 413
            # instead of a connection reset while the request is still uploading.
            if length <= MAX_BODY_BYTES * 2:
                self.rfile.read(length)
            status, payload = error_response(
                "payload_too_large",
                f"request body exceeds {MAX_BODY_BYTES} bytes",
                request_id,
                413,
            )
            self._send(status, payload)
            return
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
                status, payload = handle_chat(body, request_id)
                if "request_id" not in payload and "error" not in payload:
                    payload["request_id"] = request_id
                self._send(status, payload)
                return
            if path == "/v1/chat/stream":
                self._start_sse()
                self._write_sse("started", {"request_id": request_id})
                status, payload = handle_chat(body, request_id)
                if status >= 400:
                    self._write_sse("error", {"status": status, **payload})
                    return
                self._write_sse("completed", payload)
                return
            if path == "/v1/tasks":
                if not body.get("message") and not body.get("query"):
                    status, payload = error_response("invalid_request", "message is required", request_id, 400)
                    self._send(status, payload)
                    return
                record = task_manager.submit(_run_async_chat, body, request_id)
                self._send(202, {"request_id": request_id, **record.public()})
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
            if path == "/v1/skills/route":
                from react_agent.skills import route_skill_decision

                query = str(body.get("query") or body.get("message") or "")
                payload = body.get("payload") if isinstance(body.get("payload"), dict) else {}
                payload = {**payload, **{k: v for k, v in body.items() if k not in {"query", "message", "payload"}}}
                try:
                    decision = route_skill_decision(query, payload)
                except ValueError as exc:
                    status, payload_out = error_response("routing_failed", str(exc), request_id, 422)
                    self._send(status, payload_out)
                    return
                self._send(200, {"request_id": request_id, "route": decision.to_dict()})
                return
            if path == "/v1/skills/run":
                from react_agent.skills import get_skill, run_skill

                name = str(body.get("name") or "").strip()
                raw_payload = body.get("payload")
                payload = dict(raw_payload) if isinstance(raw_payload, dict) else {}
                if body.get("query") and "query" not in payload:
                    payload["query"] = body["query"]
                if not name:
                    status, payload_out = error_response("invalid_request", "name is required", request_id, 400)
                    self._send(status, payload_out)
                    return
                try:
                    skill = get_skill(name)
                except KeyError as exc:
                    status, payload_out = error_response("not_found", str(exc), request_id, 404)
                    self._send(status, payload_out)
                    return
                if skill.risk_level != "read_only" or not skill.agent_callable:
                    status, payload_out = error_response(
                        "skill_requires_controlled_caller",
                        f"skill {name} requires an explicit controlled caller",
                        request_id,
                        403,
                    )
                    self._send(status, payload_out)
                    return
                result = run_skill(name, payload)
                self._send(200 if result.ok else 422, {"request_id": request_id, **result.to_dict()})
                return
            status, payload = error_response("not_found", f"unknown path {path}", request_id, 404)
            self._send(status, payload)
        except Exception as e:
            traceback.print_exc()
            status, payload = error_response("internal_error", str(e)[:300], request_id, 500)
            self._send(status, payload)

    def do_DELETE(self):
        request_id = self.headers.get("X-Request-Id") or str(uuid.uuid4())
        path = urlparse(self.path).path
        if not path.startswith("/v1/tasks/"):
            status, payload = error_response("not_found", f"unknown path {path}", request_id, 404)
            self._send(status, payload)
            return
        record = task_manager.cancel(path.rsplit("/", 1)[-1])
        if record is None:
            status, payload = error_response("not_found", "task not found", request_id, 404)
            self._send(status, payload)
            return
        self._send(200, {"request_id": request_id, **record.public()})


def serve(host: str = "127.0.0.1", port: int = 8765):
    from react_agent.apps.docs_troubleshoot.index import reset_index
    from react_agent.tools import enable_app_tools

    enable_app_tools()
    reset_index()
    httpd = ThreadingHTTPServer((host, port), AgentHandler)
    print(f"[server] listening on http://{host}:{port}")
    print("[server] POST /v1/chat  app=default|docs_troubleshoot|expense|security_triage")
    print("[server] POST /v1/chat/stream  /v1/tasks; GET/DELETE /v1/tasks/{id}")
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
