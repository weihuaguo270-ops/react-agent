"""Remote GitHub/CI delivery gateway over MCP Streamable HTTP."""
from __future__ import annotations

import json
from typing import Any

from react_agent.mcp_client import StreamableHTTPMCPClient


class RemoteDeliveryGateway:
    """Small domain adapter over a remote MCP server.

    The MCP server owns GitHub/CI credentials and external writes.  The local
    workflow sends a validated patch and plan metadata, so the Agent process
    never needs a GitHub token or a direct ``gh`` connection.
    """

    def __init__(self, client: Any):
        self.client = client
        self._discovered = False

    @classmethod
    def from_config(
        cls,
        url: str,
        *,
        token: str | None = None,
        token_env: str | None = None,
        timeout: float = 15,
        max_retries: int = 2,
        retry_writes: bool = False,
        confirmation_fn=None,
    ) -> "RemoteDeliveryGateway":
        client = StreamableHTTPMCPClient(
            url,
            token=token,
            token_env=token_env,
            timeout=timeout,
            max_retries=max_retries,
            retry_writes=retry_writes,
            confirmation_fn=confirmation_fn,
            require_confirmation=True,
        )
        return cls(client)

    def connect(self) -> None:
        self.client.connect()
        self.client.discover_tools()
        self._discovered = True

    def publish_draft_pr(
        self,
        *,
        repository: str,
        base_branch: str,
        branch: str,
        task_id: str,
        issue_url: str,
        diff: str,
        plan_sha256: str,
        idempotency_key: str,
        approver: str = "",
        approved_at: str = "",
        allow_external_write: bool = False,
    ) -> str:
        self._ensure_connected()
        result = self._call("create_draft_pr", {
            "repository": repository,
            "base_branch": base_branch,
            "branch": branch,
            "task_id": task_id,
            "issue_url": issue_url,
            "diff": diff,
            "plan_sha256": plan_sha256,
            "idempotency_key": idempotency_key,
            "approver": approver,
            "approved_at": approved_at,
            "allow_external_write": allow_external_write,
        })
        return str(result.get("url") or result.get("pull_request_url") or result.get("text") or "")

    def get_ci_status(self, *, repository: str, ref: str) -> dict[str, Any]:
        self._ensure_connected()
        return self._call("get_ci_status", {"repository": repository, "ref": ref})

    def trigger_ci(
        self,
        *,
        repository: str,
        ref: str,
        workflow: str = "",
        approver: str = "",
        approved_at: str = "",
        allow_external_write: bool = False,
    ) -> dict[str, Any]:
        self._ensure_connected()
        return self._call(
            "trigger_ci",
            {
                "repository": repository,
                "ref": ref,
                "workflow": workflow,
                "approver": approver,
                "approved_at": approved_at,
                "allow_external_write": allow_external_write,
            },
        )

    def _call(self, tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
        raw = self.client.call_tool(tool, arguments)
        if isinstance(raw, dict):
            return raw
        text = str(raw)
        try:
            parsed = json.loads(text)
        except (TypeError, json.JSONDecodeError):
            return {"text": text}
        return parsed if isinstance(parsed, dict) else {"value": parsed}

    def _ensure_connected(self) -> None:
        if not self._discovered:
            self.connect()


__all__ = ["RemoteDeliveryGateway"]
