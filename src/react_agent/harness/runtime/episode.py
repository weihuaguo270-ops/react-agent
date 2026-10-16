"""Runtime execution contract shared by Agent adapters and HTTP transport."""
from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Mapping

from react_agent.harness.contracts import StopReason, assert_valid

RUNTIME_EPISODE_VERSION = "runtime-episode/v1"
_EXECUTION_MODES = {"react", "workflow"}
_TRANSPORTS = {"in_process", "http", "sse", "subprocess"}
_STATUSES = {"running", "completed", "failed", "timeout", "cancelled", "refused"}


def _new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex}"


@dataclass
class RuntimeEpisode:
    """One real runtime execution and its canonical trajectory evidence."""

    runtime_episode_id: str
    query: str
    execution_mode: str
    transport: str = "in_process"
    status: str = "running"
    stop_reason: StopReason | str | None = None
    trajectory: dict[str, Any] = field(default_factory=dict)
    metrics: dict[str, Any] = field(default_factory=dict)
    environment: dict[str, Any] = field(default_factory=dict)
    trace_id: str = ""
    session_id: str = ""
    run_id: str = ""
    created_at: float = field(default_factory=time.time)
    finished_at: float | None = None

    def __post_init__(self) -> None:
        if not str(self.runtime_episode_id).strip():
            raise ValueError("runtime_episode_id must not be empty")
        if not str(self.query).strip():
            raise ValueError("runtime episode query must not be empty")
        if self.execution_mode not in _EXECUTION_MODES:
            raise ValueError("execution_mode must be react or workflow")
        if self.transport not in _TRANSPORTS:
            raise ValueError("unsupported runtime transport")
        if self.status not in _STATUSES:
            raise ValueError("unsupported runtime status")
        if self.stop_reason is not None:
            self.stop_reason = self._coerce_stop_reason(self.stop_reason)
        self.metrics = dict(self.metrics or {})
        self.environment = dict(self.environment or {})
        self.trajectory = dict(self.trajectory or {})
        if self.trajectory:
            assert_valid(self.trajectory)

    @classmethod
    def start(
        cls,
        query: str,
        execution_mode: str,
        *,
        transport: str = "in_process",
        runtime_episode_id: str | None = None,
        trace_id: str | None = None,
        session_id: str | None = None,
        run_id: str | None = None,
        environment: Mapping[str, Any] | None = None,
    ) -> "RuntimeEpisode":
        runtime_id = runtime_episode_id or _new_id("runtime")
        return cls(
            runtime_episode_id=runtime_id,
            query=query,
            execution_mode=execution_mode,
            transport=transport,
            trace_id=trace_id or _new_id("trace"),
            session_id=session_id or _new_id("session"),
            run_id=run_id or _new_id("run"),
            environment=dict(environment or {}),
        )

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "RuntimeEpisode":
        """Reconstruct an episode from a local JSON artifact."""
        if not isinstance(value, Mapping):
            raise ValueError("runtime episode must be an object")
        version = str(value.get("schema_version") or RUNTIME_EPISODE_VERSION)
        if version != RUNTIME_EPISODE_VERSION:
            raise ValueError(f"unsupported runtime episode schema: {version}")
        return cls(
            runtime_episode_id=str(value.get("runtime_episode_id") or ""),
            query=str(value.get("query") or ""),
            execution_mode=str(value.get("execution_mode") or ""),
            transport=str(value.get("transport") or "in_process"),
            status=str(value.get("status") or "running"),
            stop_reason=value.get("stop_reason"),
            trajectory=dict(value.get("trajectory") or {}),
            metrics=dict(value.get("metrics") or {}),
            environment=dict(value.get("environment") or {}),
            trace_id=str(value.get("trace_id") or ""),
            session_id=str(value.get("session_id") or ""),
            run_id=str(value.get("run_id") or ""),
            created_at=float(value.get("created_at") or time.time()),
            finished_at=(
                float(value["finished_at"])
                if value.get("finished_at") is not None
                else None
            ),
        )

    @staticmethod
    def _coerce_stop_reason(value: StopReason | str) -> StopReason:
        if isinstance(value, StopReason):
            return value
        try:
            return StopReason(str(value))
        except ValueError as exc:
            raise ValueError(f"unsupported stop_reason: {value}") from exc

    @property
    def terminal(self) -> bool:
        return self.status != "running"

    def set_trajectory(self, trajectory: Mapping[str, Any]) -> None:
        normalized = dict(trajectory)
        assert_valid(normalized)
        self.trajectory = normalized
        self.session_id = str(normalized.get("session_id") or self.session_id)

    def finish(
        self,
        *,
        trajectory: Mapping[str, Any],
        stop_reason: StopReason | str = StopReason.COMPLETED,
        status: str = "completed",
        metrics: Mapping[str, Any] | None = None,
        environment: Mapping[str, Any] | None = None,
    ) -> "RuntimeEpisode":
        if status not in _STATUSES or status == "running":
            raise ValueError("finish requires a terminal runtime status")
        self.set_trajectory(trajectory)
        self.stop_reason = self._coerce_stop_reason(stop_reason)
        self.status = status
        self.finished_at = time.time()
        self.metrics.update(dict(metrics or {}))
        self.metrics.setdefault("duration_seconds", round(self.finished_at - self.created_at, 6))
        self.environment.update(dict(environment or {}))
        return self

    def fail(
        self,
        *,
        trajectory: Mapping[str, Any],
        stop_reason: StopReason | str,
        status: str = "failed",
        metrics: Mapping[str, Any] | None = None,
    ) -> "RuntimeEpisode":
        return self.finish(
            trajectory=trajectory,
            stop_reason=stop_reason,
            status=status,
            metrics=metrics,
        )

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "schema_version": RUNTIME_EPISODE_VERSION,
            "runtime_episode_id": self.runtime_episode_id,
            "trace_id": self.trace_id,
            "session_id": self.session_id,
            "run_id": self.run_id,
            "query": self.query,
            "execution_mode": self.execution_mode,
            "transport": self.transport,
            "status": self.status,
            "metrics": dict(self.metrics),
            "environment": dict(self.environment),
            "created_at": self.created_at,
        }
        if self.stop_reason is not None:
            payload["stop_reason"] = self._coerce_stop_reason(self.stop_reason).value
        if self.finished_at is not None:
            payload["finished_at"] = self.finished_at
        if self.trajectory:
            payload["trajectory"] = dict(self.trajectory)
        return payload

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, sort_keys=True)


__all__ = ["RUNTIME_EPISODE_VERSION", "RuntimeEpisode"]
