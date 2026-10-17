"""Local, replayable observability artifacts for runtime executions."""
from __future__ import annotations

import json
import os
import time
from contextvars import ContextVar, Token
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
    "input_tokens": ("input_tokens", "prompt_tokens"),
    "output_tokens": ("output_tokens", "completion_tokens"),
    "estimated_cost": ("estimated_cost", "cost", "cost_usd"),
    "denied": ("denied", "rejected", "policy_denied"),
    "cancelled": ("cancelled", "cancellations", "cancelled_count"),
}
_SAFE_METRIC_KEYS = set(_METRIC_ALIASES)
_CURRENT_METRICS: ContextVar["RuntimeMetricsCollector | None"] = ContextVar(
    "react_agent_runtime_metrics", default=None
)


class ObservabilityArtifactError(ValueError):
    """Raised when a local observability artifact is invalid or inconsistent."""


class RedisStreamObservabilityExporter:
    """Publish redacted RuntimeEpisode artifacts to a dedicated Redis Stream."""

    def __init__(
        self,
        *,
        url: str | None = None,
        stream: str = "react-agent:observability",
        maxlen: int | None = 100_000,
        client: Any | None = None,
    ) -> None:
        if not stream.strip():
            raise ValueError("observability stream must not be empty")
        if maxlen is not None and maxlen < 1:
            raise ValueError("observability stream maxlen must be positive")
        self.stream = stream
        self.maxlen = maxlen
        if client is None:
            redis_url = url or os.environ.get("REACT_AGENT_OBSERVABILITY_REDIS_URL") or os.environ.get(
                "REACT_AGENT_IDEMPOTENCY_REDIS_URL"
            ) or os.environ.get("REACT_AGENT_REDIS_URL")
            if not redis_url:
                raise ValueError("Redis URL is required for Redis Stream observability export")
            try:
                import redis
            except ImportError as exc:
                raise RuntimeError("install redis to use Redis Stream observability export") from exc
            client = redis.Redis.from_url(
                redis_url,
                decode_responses=True,
                socket_connect_timeout=float(
                    os.environ.get("REACT_AGENT_OBSERVABILITY_CONNECT_TIMEOUT", "3")
                ),
                socket_timeout=float(os.environ.get("REACT_AGENT_OBSERVABILITY_SOCKET_TIMEOUT", "3")),
            )
        self.client = client

    def __call__(self, artifact: Mapping[str, Any]) -> str:
        nested_artifact = artifact.get("artifact")
        links = artifact.get("links") or (
            nested_artifact.get("links") if isinstance(nested_artifact, Mapping) else {}
        ) or {}
        fields = {
            "event_type": str(
                artifact.get("event_type")
                or artifact.get("artifact_type")
                or "runtime_episode_observability"
            ),
            "schema_version": str(artifact.get("schema_version") or OBSERVABILITY_ARTIFACT_VERSION),
            "runtime_episode_id": str(links.get("runtime_episode_id") or UNKNOWN),
            "trace_id": str(links.get("trace_id") or UNKNOWN),
            "artifact": json.dumps(artifact, ensure_ascii=False, separators=(",", ":")),
        }
        options: dict[str, Any] = {}
        if self.maxlen is not None:
            options.update(maxlen=self.maxlen, approximate=True)
        return str(self.client.xadd(self.stream, fields, **options))

    def close(self) -> None:
        close = getattr(self.client, "close", None)
        if close:
            close()


def configured_runtime_observability() -> "RuntimeObservability":
    """Build the configured exporter; local artifact use remains the default."""
    backend = os.environ.get("REACT_AGENT_OBSERVABILITY_EXPORTER", "").strip().lower()
    if backend in {"", "none", "off", "disabled"}:
        return RuntimeObservability()
    if backend not in {"redis", "redis_stream", "redis-stream"}:
        raise ValueError(f"unsupported observability exporter: {backend}")

    primary = RedisStreamObservabilityExporter(
        stream=os.environ.get("REACT_AGENT_OBSERVABILITY_STREAM", "react-agent:observability"),
        maxlen=int(os.environ.get("REACT_AGENT_OBSERVABILITY_MAXLEN", "100000")),
    )
    failure = RedisStreamObservabilityExporter(
        stream=os.environ.get(
            "REACT_AGENT_OBSERVABILITY_FAILURE_STREAM", "react-agent:observability:failures"
        ),
        maxlen=int(os.environ.get("REACT_AGENT_OBSERVABILITY_FAILURE_MAXLEN", "10000")),
        client=primary.client,
    )
    from .policies import RetryPolicy

    attempts = int(os.environ.get("REACT_AGENT_OBSERVABILITY_RETRY_ATTEMPTS", "3"))
    retry = RetryPolicy(
        max_attempts=attempts,
        base_delay=float(os.environ.get("REACT_AGENT_OBSERVABILITY_RETRY_BASE_DELAY", "0.1")),
        max_delay=float(os.environ.get("REACT_AGENT_OBSERVABILITY_RETRY_MAX_DELAY", "2")),
    )
    return RuntimeObservability(
        exporter=primary,
        exporter_failure_policy=os.environ.get(
            "REACT_AGENT_OBSERVABILITY_FAILURE_POLICY", "ignore"
        ).strip().lower(),
        exporter_retry_policy=retry,
        exporter_queue=failure,
    )


@dataclass
class RuntimeMetricsCollector:
    """Context-local measurements gathered while one RuntimeEpisode executes."""

    retry_count: int = 0
    tokens: int | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    estimated_cost: float | None = None

    def record_retry(self) -> None:
        self.retry_count += 1

    def record_tokens(self, value: Any) -> None:
        if isinstance(value, bool):
            return
        try:
            amount = int(value)
        except (TypeError, ValueError):
            return
        if amount < 0:
            return
        self.tokens = amount if self.tokens is None else self.tokens + amount

    @staticmethod
    def _amount(value: Any) -> int | None:
        if isinstance(value, bool):
            return None
        try:
            amount = int(value)
        except (TypeError, ValueError):
            return None
        return amount if amount >= 0 else None

    def record_usage(
        self,
        usage: Mapping[str, Any],
        *,
        pricing: Mapping[str, Any] | None = None,
    ) -> None:
        """Record provider usage and calculate cost when an explicit price exists."""
        input_tokens = self._amount(usage.get("prompt_tokens", usage.get("input_tokens")))
        output_tokens = self._amount(
            usage.get("completion_tokens", usage.get("output_tokens"))
        )
        total = self._amount(usage.get("total_tokens"))
        if input_tokens is not None:
            self.input_tokens = (
                input_tokens
                if self.input_tokens is None
                else self.input_tokens + input_tokens
            )
        if output_tokens is not None:
            self.output_tokens = (
                output_tokens
                if self.output_tokens is None
                else self.output_tokens + output_tokens
            )
        call_total = total
        if input_tokens is not None and output_tokens is not None:
            call_total = input_tokens + output_tokens
        if call_total is not None:
            self.record_tokens(call_total)

        if not pricing:
            return
        input_rate = pricing.get("input_usd_per_million_tokens")
        output_rate = pricing.get("output_usd_per_million_tokens")
        if (
            input_tokens is not None
            and output_tokens is not None
            and isinstance(input_rate, (int, float))
            and not isinstance(input_rate, bool)
            and input_rate >= 0
            and isinstance(output_rate, (int, float))
            and not isinstance(output_rate, bool)
            and output_rate >= 0
        ):
            cost = (
                input_tokens * float(input_rate) + output_tokens * float(output_rate)
            ) / 1_000_000
            self.estimated_cost = round(
                cost if self.estimated_cost is None else self.estimated_cost + cost,
                12,
            )


def start_runtime_metrics() -> tuple[RuntimeMetricsCollector, Token]:
    collector = RuntimeMetricsCollector()
    return collector, _CURRENT_METRICS.set(collector)


def stop_runtime_metrics(token: Token) -> None:
    _CURRENT_METRICS.reset(token)


def current_runtime_metrics() -> RuntimeMetricsCollector | None:
    return _CURRENT_METRICS.get()


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


def merge_runtime_metrics(
    metrics: Mapping[str, Any] | None,
    *,
    trajectory: Mapping[str, Any] | None = None,
    stop_reason: Any = None,
    collector: RuntimeMetricsCollector | None = None,
) -> dict[str, Any]:
    """Add measurements available at the runtime boundary without guessing."""
    merged = dict(metrics or {})
    active = collector or current_runtime_metrics()
    if active is not None and "retry_count" not in merged:
        merged["retry_count"] = active.retry_count
    if active is not None and active.tokens is not None and "tokens" not in merged:
        merged["tokens"] = active.tokens
    if active is not None and active.input_tokens is not None and "input_tokens" not in merged:
        merged["input_tokens"] = active.input_tokens
    if active is not None and active.output_tokens is not None and "output_tokens" not in merged:
        merged["output_tokens"] = active.output_tokens
    if active is not None and active.estimated_cost is not None and "estimated_cost" not in merged:
        merged["estimated_cost"] = active.estimated_cost

    steps = (trajectory or {}).get("steps") if isinstance(trajectory, Mapping) else None
    if isinstance(steps, list) and "tokens" not in merged:
        token_values = [
            step.get("tokens_estimated")
            for step in steps
            if isinstance(step, Mapping) and isinstance(step.get("tokens_estimated"), (int, float))
        ]
        if token_values:
            merged["tokens"] = sum(token_values)

    if isinstance(steps, list) and "denied" not in merged:
        denied = 0
        cancelled = 0
        for step in steps:
            if not isinstance(step, Mapping):
                continue
            observation = step.get("observation")
            if isinstance(observation, Mapping):
                error_code = observation.get("error_code")
                stop = observation.get("stop_reason")
                denied += int(error_code == "policy_denied" or stop == "policy_denied")
                cancelled += int(error_code == "cancelled" or stop == "cancelled")
            elif isinstance(observation, str):
                denied += int("policy_denied" in observation)
                cancelled += int('"error_code": "cancelled"' in observation)
        if denied:
            merged["denied"] = denied
        if cancelled and "cancelled" not in merged:
            merged["cancelled"] = cancelled

    reason = getattr(stop_reason, "value", stop_reason)
    if reason == "policy_denied" and "denied" not in merged:
        merged["denied"] = 1
    if reason == "cancelled" and "cancelled" not in merged:
        merged["cancelled"] = 1
    return merged


def _known(value: Any) -> str:
    return str(value) if value not in (None, "") else UNKNOWN


class RuntimeObservability:
    """Emit and reconstruct a self-contained RuntimeEpisode artifact."""

    def __init__(
        self,
        *,
        retention: RetentionPolicy | None = None,
        exporter: Callable[[Mapping[str, Any]], None] | None = None,
        exporter_failure_policy: str = "raise",
        exporter_retry_policy: Any | None = None,
        exporter_queue: Callable[[Mapping[str, Any]], None] | None = None,
        exporter_alert: Callable[[Mapping[str, Any]], None] | None = None,
    ) -> None:
        self.retention = retention or RetentionPolicy()
        self.exporter = exporter
        if exporter_failure_policy not in {"raise", "ignore"}:
            raise ValueError("exporter_failure_policy must be raise or ignore")
        self.exporter_failure_policy = exporter_failure_policy
        self.exporter_retry_policy = exporter_retry_policy
        self.exporter_queue = exporter_queue
        self.exporter_alert = exporter_alert

    def _export_failure_event(
        self,
        artifact: Mapping[str, Any],
        *,
        attempts: int,
        error: Exception,
    ) -> dict[str, Any]:
        return {
            "event_type": "observability_export_failed",
            "schema_version": OBSERVABILITY_ARTIFACT_VERSION,
            "attempts": attempts,
            "error": redact_text(str(error))[:500],
            "artifact": dict(artifact),
        }

    def _deliver_export(self, artifact: Mapping[str, Any]) -> None:
        if self.exporter is None:
            return
        policy = self.exporter_retry_policy
        if policy is None:
            from .policies import RetryPolicy

            policy = RetryPolicy(max_attempts=1, base_delay=0, jitter_ratio=0)
        attempts = 0
        last_error: Exception | None = None

        def operation() -> None:
            nonlocal attempts, last_error
            attempts += 1
            try:
                self.exporter(dict(artifact))
            except Exception as exc:
                last_error = exc
                raise

        metrics_token = _CURRENT_METRICS.set(None)
        try:
            try:
                policy.run(operation)
                return
            except Exception as exc:
                last_error = last_error or exc
        finally:
            _CURRENT_METRICS.reset(metrics_token)

        failure = self._export_failure_event(
            artifact,
            attempts=attempts,
            error=last_error or RuntimeError("unknown exporter failure"),
        )
        queued = self.exporter_queue is not None
        failure["queued"] = queued
        if self.exporter_queue is not None:
            try:
                self.exporter_queue(dict(failure))
            except Exception as queue_error:
                queued = False
                failure["queued"] = False
                failure["queue_error"] = redact_text(str(queue_error))[:500]
        if self.exporter_alert is not None:
            try:
                self.exporter_alert(dict(failure))
            except Exception as alert_error:
                failure["alert_error"] = redact_text(str(alert_error))[:500]
        if self.exporter_failure_policy == "raise":
            raise ObservabilityArtifactError(
                f"observability exporter failed after {attempts} attempt(s)"
            ) from last_error

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
        self._deliver_export(artifact)
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
    "RuntimeMetricsCollector",
    "RetentionPolicy",
    "RuntimeObservability",
    "current_runtime_metrics",
    "merge_runtime_metrics",
    "normalize_runtime_metrics",
    "start_runtime_metrics",
    "stop_runtime_metrics",
]
