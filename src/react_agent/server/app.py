"""Thin production-oriented HTTP surface (stdlib only)."""
from __future__ import annotations

import json
import os
import traceback
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Optional
from urllib.parse import urlparse

# Service defaults before heavy imports
os.environ.setdefault("REACT_AGENT_DISABLE_MCP", "1")
os.environ.setdefault("REACT_AGENT_DEFAULT_APP", "docs_troubleshoot")
os.environ.setdefault("REACT_AGENT_RAG_MODE", "keyword")

from react_agent.server.chat_router import handle_chat, list_applications, normalize_app
from react_agent.server.health import liveness_payload, package_version, readiness_payload
from react_agent.server.http_util import error_response
from react_agent.server.static_files import docs_troubleshoot_ui_html


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
        status, payload = error_response("not_found", f"unknown path {path}", request_id, 404)
        self._send(status, payload)

    def do_POST(self):
        request_id = self.headers.get("X-Request-Id") or str(uuid.uuid4())
        path = urlparse(self.path).path
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
                status, payload = handle_chat(body, request_id)
                if "request_id" not in payload and "error" not in payload:
                    payload["request_id"] = request_id
                self._send(status, payload)
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
    from react_agent.tools import enable_app_tools

    enable_app_tools()
    reset_index()
    httpd = ThreadingHTTPServer((host, port), AgentHandler)
    print(f"[server] listening on http://{host}:{port}")
    print("[server] POST /v1/chat  app=default|docs_troubleshoot|expense")
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
