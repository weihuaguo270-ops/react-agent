"""Run execution suite tasks through HTTP /v1/chat (app=default)."""
from __future__ import annotations

import json
import socket
import time
import urllib.error
import urllib.request
import uuid
from typing import Any, Callable

from react_agent.eval.execution_scorer import load_execution_dataset, score_agent_task
from react_agent.harness.contracts import StopReason, serialize_trajectory
from react_agent.harness.contracts import assert_valid, normalize_trajectory

HttpChatFn = Callable[[str, dict], tuple[int, dict]]


def _failure_stop_reason(status: int, code: str = "") -> StopReason:
    """Map transport/application failures to the shared termination vocabulary."""
    normalized = code.strip().lower()
    if status in {408, 504} or normalized in {"timeout", "timed_out"}:
        return StopReason.TIMEOUT
    if status == 499 or normalized in {"cancelled", "canceled", "client_disconnected"}:
        return StopReason.CANCELLED
    if status in {401, 403} or normalized in {"policy_denied", "unauthorized", "forbidden"}:
        return StopReason.POLICY_DENIED
    if status in {400, 422} or normalized in {"parse_error", "invalid_request"}:
        return StopReason.PARSE_ERROR
    return StopReason.TOOL_ERROR


def _failure_trajectory(
    *, question: str, session_id: str, message: str, status: int, code: str = ""
) -> dict:
    reason = _failure_stop_reason(status, code)
    return serialize_trajectory(
        session_id=session_id,
        query=question,
        final_answer=message,
        steps=[{"step": 1, "observation": message}],
        metadata={
            "transport": "http",
            "status": status,
            "stop_reason": reason.value,
            "error_code": code or "http_error",
        },
    )


def http_chat(base_url: str, body: dict, *, timeout: float = 60) -> tuple[int, dict]:
    """调用外部 Agent HTTP 接口并返回状态码和 JSON 响应。"""
    url = base_url.rstrip("/") + "/v1/chat"
    req = urllib.request.Request(
        url,
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8")
        try:
            return e.code, json.loads(raw)
        except json.JSONDecodeError:
            return e.code, {"error": {"message": raw[:300]}}


def _http_agent_runner_factory(base_url: str) -> Callable[..., tuple]:
    def runner(
        question: str,
        timeout: int = 90,
        max_steps: int | None = None,
        provider: str | None = None,
    ) -> tuple[str, dict | None, int, float]:
        del provider
        started = time.monotonic()
        try:
            status, payload = http_chat(
                base_url,
                {
                    "app": "default",
                    "message": question,
                    "max_steps": max_steps or 6,
                },
                timeout=float(timeout),
            )
        except (TimeoutError, socket.timeout) as exc:
            message = f"HTTP request timed out: {exc or 'timeout'}"
            trajectory = _failure_trajectory(
                question=question,
                session_id=f"http-{uuid.uuid4().hex[:12]}",
                message=message,
                status=504,
                code="timeout",
            )
            return message, trajectory, 1, time.monotonic() - started
        except urllib.error.URLError as exc:
            reason = str(getattr(exc, "reason", exc))
            timed_out = isinstance(getattr(exc, "reason", None), (TimeoutError, socket.timeout))
            status = 504 if timed_out else 503
            code = "timeout" if timed_out else "transport_error"
            message = f"HTTP transport error: {reason[:300]}"
            trajectory = _failure_trajectory(
                question=question,
                session_id=f"http-{uuid.uuid4().hex[:12]}",
                message=message,
                status=status,
                code=code,
            )
            return message, trajectory, 1, time.monotonic() - started
        if status != 200:
            payload_obj = payload if isinstance(payload, dict) else {}
            error_payload = payload_obj.get("error") or {}
            if not isinstance(error_payload, dict):
                error_payload = {}
            err = error_payload.get("message", str(payload))
            trajectory = _failure_trajectory(
                question=question,
                session_id=str(payload_obj.get("request_id") or f"http-{uuid.uuid4().hex[:12]}"),
                message=str(err),
                status=status,
                code=str(error_payload.get("code") or ""),
            )
            return str(err), trajectory, 1, time.monotonic() - started

        answer = str(payload.get("answer") or "")
        session_id = str(payload.get("request_id") or f"http-{uuid.uuid4().hex[:12]}")
        server_trajectory = payload.get("trajectory")
        if isinstance(server_trajectory, dict):
            trajectory = normalize_trajectory(server_trajectory)
            assert_valid(trajectory)
            trajectory.setdefault("metadata", {})
            trajectory["metadata"].update(
                {
                    "transport": "http",
                    "execution_mode": str(payload.get("mode") or trajectory["metadata"].get("execution_mode") or "unknown"),
                }
            )
            stdout_parts = [f"[调工具] {t}()" for t in list(payload.get("tools_called") or [])]
            stdout_parts.append(f"FINAL ANSWER: {answer}")
            return "\n".join(stdout_parts), trajectory, 0, time.monotonic() - started
        tools = list(payload.get("tools_called") or [])
        steps = payload.get("agent_steps") or []
        traj_steps = []
        for i, step in enumerate(steps, start=1):
            item = {
                "step": i,
                "thought": str(step.get("thought") or ""),
                "observation": str(step.get("observation") or ""),
            }
            tool = str(step.get("tool") or step.get("action") or "").strip()
            if tool:
                item["action"] = {
                    "name": tool,
                    "arguments": str(step.get("arguments") or "{}"),
                }
            traj_steps.append(item)
        if not traj_steps:
            traj_steps = [{"step": 1, "observation": answer}]
        stdout_parts = [f"[调工具] {t}()" for t in tools]
        stdout_parts.append(f"FINAL ANSWER: {answer}")
        stdout = "\n".join(stdout_parts)
        trajectory = serialize_trajectory(
            session_id=session_id,
            query=question,
            final_answer=answer,
            steps=traj_steps,
            metadata={
                "transport": "http",
                "status": status,
                # HTTP is an adapter boundary. Preserve the execution mode
                # reported by the underlying ReAct/Workflow endpoint so the
                # trajectory remains attributable to its source path.
                "execution_mode": str(payload.get("mode") or "unknown"),
            },
        )
        return stdout, trajectory, 0, time.monotonic() - started

    return runner


def score_http_agent_task(
    task: dict,
    base_url: str,
    *,
    chat_fn: HttpChatFn | None = None,
) -> dict[str, Any]:
    """Score one agent task via HTTP; reuses agent outcome checks."""
    runner = _http_agent_runner_factory(base_url)
    result = score_agent_task(task, agent_runner=runner)
    result["transport"] = "http"
    result["base_url"] = base_url
    return result


def run_execution_http_smoke(
    base_url: str,
    *,
    only_ids: set[str] | None = None,
    difficulties: list[str] | None = None,
    smoke_ids: tuple[str, ...] = (
        "agent_calc_17x19",
        "agent_calc_100_minus_37",
        "agent_get_time",
    ),
) -> dict[str, Any]:
    """Run a small execution subset through POST /v1/chat app=default."""
    tasks = load_execution_dataset()
    wanted = set(smoke_ids)
    if only_ids:
        wanted = only_ids
    tasks = [t for t in tasks if t.get("mode") == "agent" and str(t.get("id")) in wanted]
    if difficulties:
        wanted_d = set(difficulties)
        tasks = [t for t in tasks if (t.get("difficulty") or "") in wanted_d]

    results = [score_http_agent_task(t, base_url) for t in tasks]
    passed = sum(1 for r in results if r.get("passed"))
    total = len(results)
    return {
        "summary": {
            "total": total,
            "passed": passed,
            "failed": total - passed,
            "pass_rate": round(100.0 * passed / total, 1) if total else 0.0,
        },
        "base_url": base_url,
        "transport": "http",
        "app": "default",
        "results": results,
    }
