"""Minimal remote MCP server for controlled GitHub/CI delivery operations.

The HTTP protocol and policy live here; real GitHub/CI behavior is supplied by
an injected backend in the deployment that owns the credentials.  The default
backend is deliberately an in-memory demo backend and never contacts GitHub.
"""
from __future__ import annotations

import argparse
import json
import os
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Protocol


class DeliveryBackend(Protocol):
    def create_draft_pr(self, arguments: dict[str, Any]) -> dict[str, Any]: ...

    def get_ci_status(self, arguments: dict[str, Any]) -> dict[str, Any]: ...

    def trigger_ci(self, arguments: dict[str, Any]) -> dict[str, Any]: ...


class InMemoryDeliveryBackend:
    """Deterministic backend for local protocol tests and demonstrations."""

    def __init__(self):
        self.prs: dict[str, dict[str, Any]] = {}
        self.ci_runs: list[dict[str, Any]] = []
        self._lock = threading.Lock()

    def create_draft_pr(self, arguments: dict[str, Any]) -> dict[str, Any]:
        key = arguments["idempotency_key"]
        with self._lock:
            if key in self.prs:
                return dict(self.prs[key], idempotent_replay=True)
            number = len(self.prs) + 1
            result = {
                "url": f"https://mcp.local/pull/{number}",
                "status": "draft",
                "repository": arguments["repository"],
                "branch": arguments["branch"],
                "plan_sha256": arguments["plan_sha256"],
            }
            self.prs[key] = result
            return dict(result)

    def get_ci_status(self, arguments: dict[str, Any]) -> dict[str, Any]:
        return {
            "repository": arguments["repository"],
            "ref": arguments["ref"],
            "status": "unknown",
            "source": "in_memory_backend",
        }

    def trigger_ci(self, arguments: dict[str, Any]) -> dict[str, Any]:
        run = {
            "run_id": str(uuid.uuid4()),
            "repository": arguments["repository"],
            "ref": arguments["ref"],
            "workflow": arguments.get("workflow", ""),
            "status": "queued",
        }
        with self._lock:
            self.ci_runs.append(run)
        return run


class MCPDeliveryService:
    """JSON-RPC service with server-side auth, policy and audit hooks."""

    def __init__(
        self,
        backend: DeliveryBackend | None = None,
        *,
        token: str | None = None,
        audit_hook=None,
    ):
        self.backend = backend or InMemoryDeliveryBackend()
        self.token = token
        self.audit_hook = audit_hook
        self.audit_events: list[dict[str, Any]] = []

    def handle(self, body: dict[str, Any], *, authorization: str | None = None) -> dict[str, Any]:
        request_id = body.get("id")
        method = body.get("method")
        if self.token and authorization != f"Bearer {self.token}":
            return self._error(request_id, -32001, "unauthorized")
        if method == "initialize":
            return self._result(request_id, {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "react-agent-delivery-mcp", "version": "1.0.0"},
            })
        if method == "notifications/initialized":
            return {}
        if method == "tools/list":
            return self._result(request_id, {"tools": [
                {"name": "create_draft_pr", "description": "Create an approved draft PR",
                 "inputSchema": {"type": "object", "required": [
                     "repository", "base_branch", "branch", "task_id", "diff",
                     "plan_sha256", "idempotency_key", "allow_external_write",
                 ]}, "annotations": {"destructiveHint": True}},
                {"name": "get_ci_status", "description": "Read CI status",
                 "inputSchema": {"type": "object", "required": ["repository", "ref"]},
                 "annotations": {"readOnlyHint": True}},
                {"name": "trigger_ci", "description": "Trigger a CI run",
                 "inputSchema": {"type": "object", "required": ["repository", "ref"]},
                 "annotations": {"destructiveHint": True}},
            ]})
        if method != "tools/call":
            return self._error(request_id, -32601, f"unknown method: {method}")
        params = body.get("params") if isinstance(body.get("params"), dict) else {}
        name = params.get("name")
        arguments = params.get("arguments") if isinstance(params.get("arguments"), dict) else {}
        self._audit("started", name, arguments)
        try:
            result = self._call_tool(name, arguments)
        except (KeyError, ValueError, PermissionError) as exc:
            self._audit("blocked", name, arguments, error=str(exc))
            return self._error(request_id, -32602, str(exc))
        except Exception as exc:
            self._audit("failed", name, arguments, error=str(exc))
            return self._error(request_id, -32000, str(exc))
        self._audit("completed", name, arguments)
        return self._result(request_id, {"content": [{"type": "text", "text": json.dumps(result)}]})

    def _call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if name == "create_draft_pr":
            required = ("repository", "base_branch", "branch", "task_id", "diff",
                        "plan_sha256", "idempotency_key", "allow_external_write")
            missing = [key for key in required if key not in arguments]
            if missing:
                raise ValueError(f"missing required fields: {', '.join(missing)}")
            if arguments["allow_external_write"] is not True:
                raise PermissionError("external write approval is required")
            if not arguments.get("approver") or not arguments.get("approved_at"):
                raise PermissionError("approver and approved_at are required")
            if len(str(arguments["diff"])) > 2_000_000:
                raise ValueError("diff exceeds remote delivery limit")
            return self.backend.create_draft_pr(arguments)
        if name == "get_ci_status":
            if not arguments.get("repository") or not arguments.get("ref"):
                raise ValueError("repository and ref are required")
            return self.backend.get_ci_status(arguments)
        if name == "trigger_ci":
            if not arguments.get("repository") or not arguments.get("ref"):
                raise ValueError("repository and ref are required")
            if arguments.get("allow_external_write") is not True:
                raise PermissionError("external write approval is required")
            if not arguments.get("approver") or not arguments.get("approved_at"):
                raise PermissionError("approver and approved_at are required")
            return self.backend.trigger_ci(arguments)
        raise ValueError(f"unknown tool: {name}")

    def _audit(self, outcome: str, tool: str, arguments: dict[str, Any], **extra):
        event = {
            "timestamp": time.time(),
            "tool": tool,
            "outcome": outcome,
            "arguments": _redact(arguments),
            **extra,
        }
        self.audit_events.append(event)
        if self.audit_hook:
            self.audit_hook(dict(event))

    @staticmethod
    def _result(request_id, result):
        return {"jsonrpc": "2.0", "id": request_id, "result": result}

    @staticmethod
    def _error(request_id, code: int, message: str):
        return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


class _Handler(BaseHTTPRequestHandler):
    service: MCPDeliveryService

    def log_message(self, *_args):
        return

    def do_POST(self):
        if self.path.rstrip("/") != "/mcp":
            self.send_error(404)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            body = json.loads(self.rfile.read(length) or b"{}")
            payload = self.service.handle(body, authorization=self.headers.get("Authorization"))
        except (ValueError, json.JSONDecodeError):
            payload = self.service._error(None, -32700, "invalid JSON")
        raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(202 if not payload else 200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        if raw:
            self.wfile.write(raw)


def serve(host: str = "127.0.0.1", port: int = 8780, *, token: str | None = None, backend=None):
    service = MCPDeliveryService(backend=backend, token=token)
    handler = type("MCPDeliveryHandler", (_Handler,), {"service": service})
    server = ThreadingHTTPServer((host, port), handler)
    print(f"MCP delivery server listening on http://{host}:{port}/mcp")
    try:
        server.serve_forever()
    finally:
        server.server_close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default=os.environ.get("MCP_SERVER_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("MCP_SERVER_PORT", "8780")))
    parser.add_argument("--token-env", default="MCP_SERVER_TOKEN")
    parser.add_argument(
        "--backend",
        choices=("memory", "github"),
        default=os.environ.get("MCP_DELIVERY_BACKEND", "memory"),
    )
    parser.add_argument("--github-token-env", default="GITHUB_TOKEN")
    args = parser.parse_args()
    backend = None
    if args.backend == "github":
        from react_agent.server.github_backend import GitHubRESTBackend

        backend = GitHubRESTBackend.from_env(token_env=args.github_token_env)
    serve(args.host, args.port, token=os.environ.get(args.token_env) or None, backend=backend)


def _redact(arguments):
    sensitive = {"token", "password", "secret", "api_key", "apikey", "authorization"}
    return {
        key: "<REDACTED>" if key.lower() in sensitive else value
        for key, value in arguments.items()
    }


__all__ = ["DeliveryBackend", "InMemoryDeliveryBackend", "MCPDeliveryService", "main", "serve"]
