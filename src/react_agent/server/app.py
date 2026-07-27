"""Thin production-oriented HTTP surface (stdlib only)."""
from __future__ import annotations

import json
import os
import traceback
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Optional
from urllib.parse import urlparse

# Service defaults before heavy imports
os.environ.setdefault("REACT_AGENT_DISABLE_MCP", "1")
os.environ.setdefault("REACT_AGENT_APP", "docs_troubleshoot")
os.environ.setdefault("REACT_AGENT_RAG_MODE", "keyword")


def _version() -> str:
    try:
        from importlib.metadata import version

        return version("react-agent")
    except Exception:
        return "0.2.0"


def _error(code: str, message: str, request_id: str, http_status: int = 400) -> tuple[int, dict]:
    return http_status, {
        "error": {"code": code, "message": message, "request_id": request_id}
    }


def handle_chat(body: dict, request_id: str) -> tuple[int, dict]:
    """
    Offline-capable chat path for docs_troubleshoot:
    retrieve → draft → citation policy. Uses LLM react_loop only when
    REACT_AGENT_SERVER_LLM=1 and a key is configured.
    """
    message = (body.get("message") or body.get("query") or "").strip()
    if not message:
        return _error("invalid_request", "message is required", request_id, 400)

    use_llm = os.environ.get("REACT_AGENT_SERVER_LLM", "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )
    trajectory_id = ""
    citations: list[dict[str, Any]] = []

    if use_llm:
        try:
            from react_agent.harness.recorder import current_trajectory
            from react_agent.react_loop import react_loop

            answer = react_loop(message, max_steps=int(body.get("max_steps") or 6))
            if not isinstance(answer, str):
                answer = str(answer.get("output", answer))
            traj = current_trajectory()
            if traj is not None:
                trajectory_id = getattr(traj, "id", "") or getattr(traj, "run_id", "") or ""
            from react_agent.apps.docs_troubleshoot.policy import enforce_answer_policy

            out = enforce_answer_policy(answer)
            return 200, {
                "request_id": request_id,
                "answer": out["answer"],
                "trajectory_id": trajectory_id,
                "citations": out.get("citations") or [],
                "refused": out.get("refused", False),
                "mode": "llm",
            }
        except Exception as e:
            return _error("internal_error", str(e)[:300], request_id, 500)

    # Deterministic offline path (default for CI / local smoke)
    from react_agent.apps.docs_troubleshoot.policy import enforce_answer_policy
    from react_agent.apps.docs_troubleshoot.tools import lookup_api, search_docs

    data = json.loads(search_docs(message, top_k=2))
    results = data.get("results") or []
    if not results:
        data = json.loads(lookup_api(message, top_k=2))
        results = data.get("results") or []

    sources = [r.get("source", "") for r in results if r.get("source")]
    if results:
        snippet = (results[0].get("content") or "").replace("\n", " ")[:220]
        draft = f"根据 {sources[0]}：{snippet} 来源: {sources[0]}"
    else:
        draft = "未检索到相关文档。"

    must_refuse = any(k in message for k in ("股价", "删库", "删除生产", "rm -rf"))
    out = enforce_answer_policy(
        draft, allowed_sources=sources or None, must_refuse=must_refuse
    )
    return 200, {
        "request_id": request_id,
        "answer": out["answer"],
        "trajectory_id": trajectory_id or f"offline-{request_id[:8]}",
        "citations": out.get("citations") or [{"source": s} for s in sources[:3]],
        "refused": out.get("refused", False),
        "mode": "offline",
        "session_id": body.get("session_id") or "",
    }


class AgentHandler(BaseHTTPRequestHandler):
    server_version = "react-agent-server/0.2"

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
        sys_stderr_write = getattr(self, "_log", None)
        print(f"[server] {self.address_string()} {fmt % args}")

    def do_GET(self):
        request_id = self.headers.get("X-Request-Id") or str(uuid.uuid4())
        path = urlparse(self.path).path
        if path in ("/health", "/v1/health"):
            self._send(
                200,
                {
                    "status": "ok",
                    "version": _version(),
                    "app": os.environ.get("REACT_AGENT_APP", ""),
                    "request_id": request_id,
                },
            )
            return
        if path in ("/v1/workflows", "/v1/workflows/list"):
            from react_agent.workflow import list_workflows

            self._send(
                200,
                {"request_id": request_id, "workflows": list_workflows()},
            )
            return
        status, payload = _error("not_found", f"unknown path {path}", request_id, 404)
        self._send(status, payload)

    def do_POST(self):
        request_id = self.headers.get("X-Request-Id") or str(uuid.uuid4())
        path = urlparse(self.path).path
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        try:
            body = json.loads(raw.decode("utf-8") or "{}")
        except json.JSONDecodeError:
            status, payload = _error("invalid_request", "invalid JSON body", request_id, 400)
            self._send(status, payload)
            return
        if not isinstance(body, dict):
            status, payload = _error("invalid_request", "body must be object", request_id, 400)
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
                    status, payload = _error(
                        "invalid_request", "name is required", request_id, 400
                    )
                    self._send(status, payload)
                    return
                from react_agent.workflow.tools import run_workflow_tool

                raw = run_workflow_tool(
                    name=name,
                    query=str(body.get("query") or ""),
                    payload_json=json.dumps(body.get("state") or {})
                    if isinstance(body.get("state"), dict)
                    else str(body.get("payload_json") or ""),
                )
                data = json.loads(raw)
                data["request_id"] = request_id
                self._send(200 if data.get("ok", True) else 500, data)
                return
            status, payload = _error("not_found", f"unknown path {path}", request_id, 404)
            self._send(status, payload)
        except Exception as e:
            traceback.print_exc()
            status, payload = _error("internal_error", str(e)[:300], request_id, 500)
            self._send(status, payload)


def serve(host: str = "127.0.0.1", port: int = 8765):
    from react_agent.apps.docs_troubleshoot.index import reset_index
    from react_agent.tools import enable_app_tools

    enable_app_tools()
    reset_index()
    httpd = ThreadingHTTPServer((host, port), AgentHandler)
    print(f"[server] listening on http://{host}:{port}")
    print("[server] GET /health  GET /v1/workflows  POST /v1/workflows/run  POST /v1/chat")
    print("[server] REACT_AGENT_SERVER_LLM=1 for live LLM on /v1/chat")
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
