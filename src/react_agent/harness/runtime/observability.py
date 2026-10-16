"""Local, replayable observability artifacts for runtime executions."""
from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping

from react_agent.safety.redaction import REDACTED, redact_text

from .episode import RuntimeEpisode

OBSERVABILITY_ARTIFACT_VERSION = "runtime-observability/v1"
UNKNOWN = "unknown"

_IDENTITY_KEYS = {
    "runtime_episode_id",
    "evaluation_episode_id",
    "trace_id",
    "session_id",
    "run_id",
}
_SENSITIVE_KEY_PARTS = (
    "password",
    "passwd",
    "secret",
    "token",
    "api_key",
    "apikey",
    "access_key",
    "private_key",
    "credential",
    "authorization",
    "cookie",
    "bearer",
)

_METRIC_ALIASES: dict[str, tuple[str, ...]] = {
    "steps": ("steps", "step_count"),
    "tool_calls": ("tool_calls", "tool_call_count"),
    "retry_count": ("retry_count", "retries", "retry_attempts"),
    "duration_seconds": ("duration_seconds", "duration"),
    "tokens": ("tokens", "tokens_estimated", "total_tokens_estimated"),
    "estimated_cost": ("estimated_cost", "cost", "cost_usd"),
    "denied": ("denied", "rejected", "policy_denied"),
    "cancelled": ("cancelled", "cancellations", "cancelled_count"),
}
_SAFE_METRIC_KEYS = set(_METRIC_ALIASES)


class ObservabilityArtifactError(ValueError):
    """Raised when a local observability artifact is invalid or inconsistent."""


@dataclass(frozen=True)
class RetentionPolicy:
    """Retention metadata without deleting evidence as a side effect."""

    retention_days: int | None = None

    def __post_init__(self) -> None:
        if self.retention_days is not None and self.retention_days < 1:
            raise ValueError("retention_days must be >= 1 when configured")

    def to_dict(self, *, emitted_at: float) -> dict[str, Any]:
        if self.retention_days is None:
            return {"retention_days": UNKNOWN, "expires_at": UNKNOWN}
        return {
            "retention_days": self.retention_days,
            "expires_at": emitted_at + self.retention_days * 86400,
        }


def _is_sensitive_key(key: str) -> bool:
    normalized = key.lower().replace("-", "_")
    return any(part in normalized for part in _SENSITIVE_KEY_PARTS)


def _redact(value: Any, *, key: str = "") -> Any:
    """Redact JSON-compatible values while preserving correlation IDs."""
    if (
        key
        and key.lower() not in _IDENTITY_KEYS
        and key.lower() not in _SAFE_METRIC_KEYS
        and _is_sensitive_key(key)
    ):
        return REDACTED
    if isinstance(value, Mapping):
        return {str(k): _redact(v, key=str(k)) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_redact(item, key=key) for item in value]
    if isinstance(value, str):
        return redact_text(value)
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return redact_text(str(value))


def _metric_value(metrics: Mapping[str, Any], aliases: tuple[str, ...]) -> Any:
    for name in aliases:
        if name in metrics and metrics[name] is not None:
            return metrics[name]
    return UNKNOWN


def normalize_runtime_metrics(metrics: Mapping[str, Any] | None) -> dict[str, Any]:
    """Return stable R6 metric names without inventing absent measurements."""
    source = dict(metrics or {})
    normalized = {
        name: _metric_value(source, aliases)
        for name, aliases in _METRIC_ALIASES.items()
    }
    extra = {
        str(name): _redact(value)
        for name, value in source.items()
        if name not in {alias for aliases in _METRIC_ALIASES.values() for alias in aliases}
    }
    if extra:
        normalized["extra"] = extra
    return normalized


def _known(value: Any) -> str:
    return str(value) if value not in (None, "") else UNKNOWN


class RuntimeObservability:
    """Emit and reconstruct a self-contained RuntimeEpisode artifact."""

    def __init__(
        self,
        *,
        retention: RetentionPolicy | None = None,
        exporter: Callable[[Mapping[str, Any]], None] | None = None,
    ) -> None:
        self.retention = retention or RetentionPolicy()
        self.exporter = exporter

    def build_artifact(
        self,
        episode: RuntimeEpisode,
        *,
        evaluation_episode_id: str | None = None,
        emitted_at: float | None = None,
    ) -> dict[str, Any]:
        linked_evaluation_id = evaluation_episode_id or episode.evaluation_episode_id
        if evaluation_episode_id and episode.evaluation_episode_id and evaluation_episode_id != episode.evaluation_episode_id:
            raise ObservabilityArtifactError("evaluation_episode_id does not match RuntimeEpisode")
        emitted = float(emitted_at if emitted_at is not None else time.time())
        metrics = normalize_runtime_metrics(episode.metrics)
        runtime_payload = episode.to_dict()
        if linked_evaluation_id:
            runtime_payload["evaluation_episode_id"] = linked_evaluation_id
        runtime_payload["metrics"] = metrics
        runtime_payload = _redact(runtime_payload)
        links = {
            "runtime_episode_id": _known(episode.runtime_episode_id),
            "evaluation_episode_id": _known(linked_evaluation_id),
            "trace_id": _known(episode.trace_id),
            "session_id": _known(episode.session_id),
            "run_id": _known(episode.run_id),
        }
        return {
            "schema_version": OBSERVABILITY_ARTIFACT_VERSION,
            "artifact_type": "runtime_episode_observability",
            "emitted_at": emitted,
            "links": links,
            "metrics": metrics,
            "retention": self.retention.to_dict(emitted_at=emitted),
            "runtime_episode": runtime_payload,
        }

    def emit(
        self,
        episode: RuntimeEpisode,
        *,
        path: str | Path | None = None,
        evaluation_episode_id: str | None = None,
        emitted_at: float | None = None,
    ) -> dict[str, Any]:
        artifact = self.build_artifact(
            episode,
            evaluation_episode_id=evaluation_episode_id,
            emitted_at=emitted_at,
        )
        if path is not None:
            target = Path(path)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(
                json.dumps(artifact, ensure_ascii=False, indent=2, sort_keys=True),
                encoding="utf-8",
            )
        if self.exporter is not None:
            self.exporter(dict(artifact))
        return artifact

    @staticmethod
    def reconstruct(value: Mapping[str, Any] | str | Path) -> RuntimeEpisode:
        if isinstance(value, (str, Path)):
            try:
                value = json.loads(Path(value).read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise ObservabilityArtifactError("unable to load observability artifact") from exc
        if not isinstance(value, Mapping):
            raise ObservabilityArtifactError("observability artifact must be an object")
        if value.get("schema_version") != OBSERVABILITY_ARTIFACT_VERSION:
            raise ObservabilityArtifactError("unsupported observability artifact schema")
        runtime_payload = value.get("runtime_episode")
        links = value.get("links")
        metrics = value.get("metrics")
        if not isinstance(runtime_payload, Mapping) or not isinstance(links, Mapping) or not isinstance(metrics, Mapping):
            raise ObservabilityArtifactError("observability artifact is missing required sections")
        if dict(runtime_payload.get("metrics") or {}) != dict(metrics):
            raise ObservabilityArtifactError("observability metrics do not match RuntimeEpisode")
        try:
            episode = RuntimeEpisode.from_mapping(runtime_payload)
        except (TypeError, ValueError) as exc:
            raise ObservabilityArtifactError("embedded RuntimeEpisode is invalid") from exc
        for field in ("runtime_episode_id", "trace_id", "session_id", "run_id"):
            expected = str(links.get(field) or UNKNOWN)
            actual = str(getattr(episode, field) or UNKNOWN)
            if expected != actual:
                raise ObservabilityArtifactError(f"observability link mismatch: {field}")
        linked_evaluation = str(links.get("evaluation_episode_id") or UNKNOWN)
        embedded_evaluation = episode.evaluation_episode_id or UNKNOWN
        if linked_evaluation != embedded_evaluation:
            raise ObservabilityArtifactError("observability link mismatch: evaluation_episode_id")
        metadata = episode.trajectory.get("metadata") or {}
        if isinstance(metadata, Mapping):
            for field in ("runtime_episode_id", "trace_id", "run_id"):
                if field in metadata and str(metadata[field]) != str(getattr(episode, field)):
                    raise ObservabilityArtifactError(
                        f"observability trajectory mismatch: {field}"
                    )
            if episode.stop_reason is not None and "stop_reason" in metadata:
                if str(metadata["stop_reason"]) != episode.stop_reason.value:
                    raise ObservabilityArtifactError(
                        "observability trajectory mismatch: stop_reason"
                    )
            if episode.status != "running" and "status" in metadata:
                if str(metadata["status"]) != episode.status:
                    raise ObservabilityArtifactError(
                        "observability trajectory mismatch: status"
                    )
        return episode

    @staticmethod
    def load(path: str | Path) -> RuntimeEpisode:
        return RuntimeObservability.reconstruct(path)


__all__ = [
    "OBSERVABILITY_ARTIFACT_VERSION",
    "UNKNOWN",
    "ObservabilityArtifactError",
    "RetentionPolicy",
    "RuntimeObservability",
    "normalize_runtime_metrics",
]
