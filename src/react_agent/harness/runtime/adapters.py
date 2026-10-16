"""Runtime adapters for ReAct, Workflow and HTTP transport."""
from __future__ import annotations

import json
import time
from typing import Any, Callable, Mapping

from react_agent.harness.contracts import StopReason, assert_valid, serialize_trajectory
from react_agent.harness.runtime.episode import RuntimeEpisode


def _answer_text(value: Any) -> str:
    if isinstance(value, Mapping):
        return str(value.get("answer") or value.get("output") or "")
    return str(value or "")


def _steps_from(value: Any) -> list[dict[str, Any]]:
    steps = value if isinstance(value, list) else []
    normalized: list[dict[str, Any]] = []
    for index, raw in enumerate(steps, start=1):
        item = dict(raw or {})
        item["step"] = index
        if "action" not in item:
            tool = str(item.get("tool") or "").strip()
            if tool:
                item["action"] = {
                    "name": tool,
                    "arguments": item.get("arguments") or "{}",
                }
        normalized.append(item)
    if not normalized:
        normalized.append(
            {
                "step": 1,
                "thought": "runtime_terminal_without_tool_step",
                "observation": "run ended without recorded tool steps",
            }
        )
    return normalized


def _trajectory(
    *,
    episode: RuntimeEpisode,
    answer: str,
    steps: Any,
    stop_reason: StopReason,
    metadata: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    values = {
        "runtime_episode_id": episode.runtime_episode_id,
        "trace_id": episode.trace_id,
        "run_id": episode.run_id,
        "execution_mode": episode.execution_mode,
        "transport": episode.transport,
        "status": episode.status,
        "stop_reason": stop_reason.value,
    }
    values.update(dict(metadata or {}))
    return serialize_trajectory(
        session_id=episode.session_id,
        query=episode.query,
        final_answer=answer,
        steps=_steps_from(steps),
        metadata=values,
    )


def _stop_reason_from_error(exc: BaseException) -> tuple[StopReason, str]:
    from react_agent.harness.contracts import ToolError

    error = ToolError.from_exception(exc)
    return error.stop_reason, error.message


class ReactLoopAdapter:
    """Adapt the existing ReAct function into a RuntimeEpisode."""

    def __init__(self, loop: Callable[..., Any] | None = None, *, environment: Mapping[str, Any] | None = None):
        self.loop = loop
        self.environment = dict(environment or {})

    def run(
        self,
        query: str,
        *,
        max_steps: int | None = None,
        tool_defs: list[dict[str, Any]] | None = None,
        transport: str = "in_process",
        runtime_episode_id: str | None = None,
        trace_id: str | None = None,
    ) -> RuntimeEpisode:
        if self.loop is None:
            from react_agent.react_loop import react_loop

            loop = react_loop
        else:
            loop = self.loop
        episode = RuntimeEpisode.start(
            query,
            "react",
            transport=transport,
            runtime_episode_id=runtime_episode_id,
            trace_id=trace_id,
            environment=self.environment,
        )
        started = time.monotonic()
        try:
            kwargs: dict[str, Any] = {}
            if max_steps is not None:
                kwargs["max_steps"] = max_steps
            if tool_defs is not None:
                kwargs["tool_defs"] = tool_defs
            result = loop(query, **kwargs)
            answer = _answer_text(result)
            steps: Any = result.get("agent_steps") if isinstance(result, Mapping) else None
            try:
                from react_agent.react_loop import get_last_trajectory_steps

                if not steps:
                    steps = get_last_trajectory_steps()
            except Exception:
                pass
            requested_reason = result.get("stop_reason") if isinstance(result, Mapping) else None
            stop_reason = RuntimeEpisode._coerce_stop_reason(requested_reason or StopReason.COMPLETED)
            status = "completed"
            if stop_reason == StopReason.TIMEOUT:
                status = "timeout"
            elif stop_reason in {StopReason.MAX_STEPS, StopReason.PARSE_ERROR}:
                status = "failed"
            trajectory = _trajectory(
                episode=episode,
                answer=answer,
                steps=steps,
                stop_reason=stop_reason,
                metadata={"model": str((result or {}).get("model") or "") if isinstance(result, Mapping) else ""},
            )
            metrics = {
                "steps": len(trajectory["steps"]),
                "tool_calls": sum(1 for step in trajectory["steps"] if step.get("action") or step.get("actions")),
                "duration_seconds": round(time.monotonic() - started, 6),
            }
            return episode.finish(
                trajectory=trajectory,
                stop_reason=stop_reason,
                status=status,
                metrics=metrics,
            )
        except Exception as exc:
            from react_agent.llm import LLMCancelled

            if isinstance(exc, LLMCancelled):
                reason, message = StopReason.CANCELLED, str(exc) or "execution cancelled"
            else:
                reason, message = _stop_reason_from_error(exc)
            status = {
                StopReason.TIMEOUT: "timeout",
                StopReason.CANCELLED: "cancelled",
                StopReason.POLICY_DENIED: "refused",
            }.get(reason, "failed")
            trajectory = _trajectory(
                episode=episode,
                answer="",
                steps=[{"step": 1, "thought": "runtime_error", "observation": message}],
                stop_reason=reason,
            )
            return episode.fail(
                trajectory=trajectory,
                stop_reason=reason,
                status=status,
                metrics={"duration_seconds": round(time.monotonic() - started, 6)},
            )


class WorkflowAdapter:
    """Adapt the declarative Workflow runner into a RuntimeEpisode."""

    def __init__(self, runner: Callable[..., Any] | None = None, *, environment: Mapping[str, Any] | None = None):
        self.runner = runner
        self.environment = dict(environment or {})

    def run(
        self,
        workflow: str,
        initial_state: Mapping[str, Any] | None = None,
        *,
        tool_registry: Mapping[str, Callable[..., Any]] | None = None,
        transport: str = "in_process",
        runtime_episode_id: str | None = None,
        trace_id: str | None = None,
    ) -> RuntimeEpisode:
        if self.runner is None:
            from react_agent.workflow import run_workflow

            runner = run_workflow
        else:
            runner = self.runner
        query = str((initial_state or {}).get("query") or workflow)
        episode = RuntimeEpisode.start(
            query,
            "workflow",
            transport=transport,
            runtime_episode_id=runtime_episode_id,
            trace_id=trace_id,
            environment=self.environment,
        )
        started = time.monotonic()
        try:
            kwargs: dict[str, Any] = {}
            if tool_registry is not None:
                kwargs["tool_registry"] = dict(tool_registry)
            result = runner(workflow, dict(initial_state or {}), **kwargs)
            source_trajectory = result.to_trajectory()
            metadata = dict(source_trajectory.get("metadata") or {})
            metadata.update(
                {
                    "runtime_episode_id": episode.runtime_episode_id,
                    "trace_id": episode.trace_id,
                    "transport": episode.transport,
                }
            )
            trajectory = serialize_trajectory(
                session_id=str(source_trajectory.get("session_id") or result.run_id),
                query=query,
                final_answer=str(getattr(result, "answer", "") or ""),
                steps=source_trajectory.get("steps") or [],
                metadata=metadata,
            )
            stop_reason = RuntimeEpisode._coerce_stop_reason(
                metadata.get("stop_reason") or (StopReason.COMPLETED if result.ok else StopReason.TOOL_ERROR)
            )
            status = "completed" if result.ok else ("refused" if result.refused else "failed")
            episode.run_id = str(result.run_id)
            episode.session_id = str(trajectory["session_id"])
            return episode.finish(
                trajectory=trajectory,
                stop_reason=stop_reason,
                status=status,
                metrics={
                    "steps": len(trajectory["steps"]),
                    "tool_calls": sum(1 for step in trajectory["steps"] if step.get("action") or step.get("actions")),
                    "duration_seconds": round(time.monotonic() - started, 6),
                },
            )
        except Exception as exc:
            reason, message = _stop_reason_from_error(exc)
            trajectory = _trajectory(
                episode=episode,
                answer="",
                steps=[{"step": 1, "thought": "workflow_error", "observation": message}],
                stop_reason=reason,
            )
            return episode.fail(
                trajectory=trajectory,
                stop_reason=reason,
                status="refused" if reason == StopReason.POLICY_DENIED else "failed",
                metrics={"duration_seconds": round(time.monotonic() - started, 6)},
            )


class HttpRunnerAdapter:
    """Attach HTTP transport metadata to a ReAct or Workflow result."""

    def adapt_response(
        self,
        payload: Mapping[str, Any],
        *,
        request_id: str,
        execution_mode: str | None = None,
        status_code: int = 200,
        transport: str = "http",
    ) -> tuple[dict[str, Any], RuntimeEpisode]:
        data = dict(payload)
        mode_value = str(execution_mode or data.get("mode") or "react").lower()
        mode = "workflow" if mode_value == "workflow" else "react"
        trajectory = data.get("trajectory")
        source_query = (
            str(trajectory.get("query") or "")
            if isinstance(trajectory, Mapping)
            else str(data.get("query") or data.get("message") or "")
        )
        episode = RuntimeEpisode.start(
            source_query or str(data.get("answer") or request_id),
            mode,
            transport=transport,
            runtime_episode_id=str(data.get("runtime_episode_id") or f"runtime-http-{request_id}"),
            trace_id=request_id,
            session_id=str((trajectory or {}).get("session_id") or request_id) if isinstance(trajectory, Mapping) else request_id,
            run_id=str(data.get("run_id") or request_id),
            environment={"http_status": status_code},
        )
        if isinstance(trajectory, Mapping):
            normalized = dict(trajectory)
            metadata = dict(normalized.get("metadata") or {})
            metadata.update(
                {
                    "transport": transport,
                    "execution_mode": mode,
                    "runtime_episode_id": episode.runtime_episode_id,
                    "trace_id": episode.trace_id,
                    "status": "completed" if status_code < 400 and not data.get("error") else "failed",
                    "stop_reason": str(metadata.get("stop_reason") or (StopReason.COMPLETED.value if status_code < 400 else StopReason.TOOL_ERROR.value)),
                    "source_mode": mode_value,
                }
            )
            trajectory = serialize_trajectory(
                session_id=str(normalized.get("session_id") or request_id),
                query=str(normalized.get("query") or data.get("query") or data.get("message") or "http request"),
                final_answer=str(normalized.get("final_answer") or data.get("answer") or ""),
                steps=normalized.get("steps") or [],
                model=str(normalized.get("model") or ""),
                metadata=metadata,
            )
        else:
            reason = StopReason.COMPLETED if status_code < 400 and not data.get("error") else StopReason.TOOL_ERROR
            trajectory = _trajectory(
                episode=episode,
                answer=str(data.get("answer") or ""),
                steps=data.get("agent_steps") or [],
                stop_reason=reason,
                metadata={"http_status": status_code},
            )
        assert_valid(trajectory)
        reason = RuntimeEpisode._coerce_stop_reason(
            trajectory.get("metadata", {}).get("stop_reason", StopReason.TOOL_ERROR.value)
        )
        status = "completed" if status_code < 400 and not data.get("error") and data.get("ok", True) is not False else "failed"
        if reason == StopReason.POLICY_DENIED:
            status = "refused"
        elif reason == StopReason.TIMEOUT:
            status = "timeout"
        elif reason == StopReason.CANCELLED:
            status = "cancelled"
        elif reason in {StopReason.MAX_STEPS, StopReason.PARSE_ERROR}:
            status = "failed"
        episode.finish(
            trajectory=trajectory,
            stop_reason=reason,
            status=status,
            metrics={"http_status": status_code, "steps": len(trajectory["steps"])},
        )
        data["runtime_episode_id"] = episode.runtime_episode_id
        data["execution_mode"] = mode
        data["runtime_episode"] = episode.to_dict()
        data["trajectory"] = episode.trajectory
        return data, episode


__all__ = ["HttpRunnerAdapter", "ReactLoopAdapter", "WorkflowAdapter"]
