"""Shared Runtime/Evaluation Harness contracts."""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping

from .trajectory import serialize_trajectory
from .parser import (
    SCHEMA_VERSION,
    TrajectorySchemaError,
    assert_valid,
    load_and_validate,
    normalize_trajectory,
    parse_trajectory,
    validate_trajectory,
)
from .compatibility import DependencyStatus, check_dependency, sibling_compatibility_report

CONTRACT_VERSION = "harness-contracts/v1"
EVALUATION_EPISODE_VERSION = "evaluation-episode/v1"
FIXTURE_MANIFEST_VERSION = "fixture-manifest/v1"


class StopReason(str, Enum):
    """Stable termination values shared by runtime and evaluation adapters."""

    COMPLETED = "completed"
    MAX_STEPS = "max_steps"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"
    POLICY_DENIED = "policy_denied"
    TOOL_ERROR = "tool_error"
    PARSE_ERROR = "parse_error"


@dataclass(frozen=True)
class ToolError:
    """Stable error envelope shared by runtime and evaluation tool calls.

    The legacy string-valued ``error`` field is intentionally retained so old
    agents can still display the failure, while consumers can use the typed
    fields for routing, retry and trajectory classification.
    """

    code: str
    message: str
    stop_reason: StopReason = StopReason.TOOL_ERROR
    retryable: bool = False
    tool_name: str = ""
    source: str = "runtime"
    attempt: int = 1
    details: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not str(self.code).strip():
            raise ValueError("tool error code must not be empty")
        if self.attempt < 1:
            raise ValueError("tool error attempt must be >= 1")
        object.__setattr__(self, "details", dict(self.details or {}))

    @classmethod
    def from_exception(
        cls,
        exc: BaseException,
        *,
        tool_name: str = "",
        source: str = "runtime",
        attempt: int = 1,
    ) -> "ToolError":
        message = str(exc).strip() or type(exc).__name__
        if isinstance(exc, PermissionError):
            code, reason, retryable = "policy_denied", StopReason.POLICY_DENIED, False
        elif isinstance(exc, TimeoutError):
            code, reason, retryable = "timeout", StopReason.TIMEOUT, True
        elif "-32602" in message or "invalid params" in message.lower():
            code, reason, retryable = "invalid_arguments", StopReason.PARSE_ERROR, False
        elif isinstance(exc, (ValueError, TypeError)):
            code, reason, retryable = "invalid_arguments", StopReason.PARSE_ERROR, False
        elif (
            isinstance(exc, KeyError)
            or "-32601" in message
            or "unknown mock tool" in message.lower()
        ):
            code, reason, retryable = "tool_not_found", StopReason.TOOL_ERROR, False
        elif message.lower().startswith("mcp "):
            code, reason, retryable = "mcp_error", StopReason.TOOL_ERROR, True
        else:
            code, reason, retryable = "tool_error", StopReason.TOOL_ERROR, False
        return cls(
            code=code,
            message=message[:500],
            stop_reason=reason,
            retryable=retryable,
            tool_name=str(tool_name or ""),
            source=source,
            attempt=attempt,
            details={"exception_type": type(exc).__name__},
        )

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "error": self.message,
            "error_code": self.code,
            "stop_reason": self.stop_reason.value,
            "retryable": self.retryable,
            "source": self.source,
            "attempt": self.attempt,
        }
        if self.tool_name:
            payload["tool_name"] = self.tool_name
        if self.details:
            payload["details"] = dict(self.details)
        return payload

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, sort_keys=True)


class ToolCallError(RuntimeError):
    """Exception wrapper for direct MCP/runtime callers needing typed detail."""

    def __init__(self, error: ToolError):
        self.error = error
        super().__init__(error.message)


def tool_error_from_exception(
    exc: BaseException,
    *,
    tool_name: str = "",
    source: str = "runtime",
    attempt: int = 1,
) -> dict[str, Any]:
    """Return a JSON-compatible shared error payload for a caught exception."""
    existing = getattr(exc, "error", None)
    if isinstance(existing, ToolError):
        return existing.to_dict()
    return ToolError.from_exception(
        exc, tool_name=tool_name, source=source, attempt=attempt
    ).to_dict()


def _json_arguments(value: Any) -> str:
    if value is None:
        return "{}"
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError as exc:
            raise ValueError("tool arguments must be valid JSON") from exc
        if not isinstance(parsed, dict):
            raise ValueError("tool arguments JSON must be an object")
        return value
    if isinstance(value, Mapping):
        return json.dumps(dict(value), ensure_ascii=False, sort_keys=True)
    raise ValueError("tool arguments must be a JSON string or object")


@dataclass(frozen=True)
class ToolCall:
    """Canonical tool invocation shared by runtime, evaluation and replay."""

    name: str
    arguments: str = "{}"
    call_id: str | None = None
    attempt: int = 1
    timeout_seconds: float | None = None
    idempotency_key: str | None = None
    source: str = "runtime"

    def __post_init__(self) -> None:
        if not str(self.name).strip():
            raise ValueError("tool call name must not be empty")
        if self.attempt < 1:
            raise ValueError("tool call attempt must be >= 1")
        object.__setattr__(self, "arguments", _json_arguments(self.arguments))

    @classmethod
    def from_mapping(
        cls, value: Mapping[str, Any], *, source: str = "runtime"
    ) -> "ToolCall":
        if not isinstance(value, Mapping):
            raise ValueError("tool call must be an object")
        function = value.get("function")
        if not isinstance(function, Mapping):
            function = value
        return cls(
            name=str(function.get("name") or ""),
            arguments=function.get("arguments", function.get("args", "{}")),
            call_id=value.get("call_id") or value.get("id"),
            attempt=int(value.get("attempt", 1)),
            timeout_seconds=value.get("timeout_seconds"),
            idempotency_key=value.get("idempotency_key"),
            source=str(value.get("source") or source),
        )

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "name": self.name,
            "arguments": self.arguments,
            "call_id": self.call_id,
            "attempt": self.attempt,
            "timeout_seconds": self.timeout_seconds,
            "idempotency_key": self.idempotency_key,
            "source": self.source,
        }
        return payload


@dataclass(frozen=True)
class ArtifactRef:
    id: str
    media_type: str
    uri: str
    mime_type: str | None = None
    sha256: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for field_name in ("id", "media_type", "uri"):
            if not str(getattr(self, field_name)).strip():
                raise ValueError(f"artifact.{field_name} must not be empty")
        if "data" in self.metadata or "base64" in self.metadata:
            raise ValueError("artifact metadata must not contain embedded media")

    def to_dict(self) -> dict[str, Any]:
        out = {"id": self.id, "media_type": self.media_type, "uri": self.uri}
        if self.mime_type:
            out["mime_type"] = self.mime_type
        if self.sha256:
            out["sha256"] = self.sha256
        if self.metadata:
            out["metadata"] = dict(self.metadata)
        return out


@dataclass(frozen=True)
class TaskEpisode:
    episode_id: str
    query: str
    acceptance_criteria: tuple[str, ...] = ()
    split: str = "dev"
    fixture_ref: str | None = None
    model_ref: str | None = None
    tool_protocol_version: str = CONTRACT_VERSION

    def __post_init__(self) -> None:
        if not self.episode_id.strip() or not self.query.strip():
            raise ValueError("episode_id and query must not be empty")
        if self.split not in {"dev", "golden", "held_out", "production"}:
            raise ValueError("unsupported episode split")

    def to_dict(self) -> dict[str, Any]:
        return {
            "episode_id": self.episode_id,
            "query": self.query,
            "acceptance_criteria": list(self.acceptance_criteria),
            "split": self.split,
            "fixture_ref": self.fixture_ref,
            "model_ref": self.model_ref,
            "tool_protocol_version": self.tool_protocol_version,
        }

    def content_hash(self) -> str:
        raw = json.dumps(
            self.to_dict(), sort_keys=True, ensure_ascii=False, separators=(",", ":")
        )
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class FixtureManifest:
    """Immutable fixture inputs and lifecycle metadata for one evaluation run."""

    fixture_id: str
    version: str
    data_sha256: str
    dependencies: dict[str, str] = field(default_factory=dict)
    setup_command: tuple[str, ...] = ()
    cleanup_command: tuple[str, ...] = ()
    environment: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not str(self.fixture_id).strip() or not str(self.version).strip():
            raise ValueError("fixture_id and version must not be empty")
        digest = str(self.data_sha256).removeprefix("sha256:")
        if not re.fullmatch(r"[0-9a-fA-F]{64}", digest):
            raise ValueError("fixture data_sha256 must be a SHA256 hex digest")
        for name in ("dependencies", "environment"):
            value = getattr(self, name)
            if not isinstance(value, Mapping):
                raise ValueError(f"fixture {name} must be an object")
            object.__setattr__(self, name, {str(k): str(v) for k, v in value.items()})
        object.__setattr__(self, "setup_command", tuple(str(x) for x in self.setup_command))
        object.__setattr__(self, "cleanup_command", tuple(str(x) for x in self.cleanup_command))

    @property
    def schema_version(self) -> str:
        return FIXTURE_MANIFEST_VERSION

    @property
    def fixture_ref(self) -> str:
        return f"fixture://{self.fixture_id}@{self.version}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": FIXTURE_MANIFEST_VERSION,
            "fixture_id": self.fixture_id,
            "version": self.version,
            "fixture_ref": self.fixture_ref,
            "data_sha256": self.data_sha256,
            "dependencies": dict(self.dependencies),
            "setup_command": list(self.setup_command),
            "cleanup_command": list(self.cleanup_command),
            "environment": dict(self.environment),
        }

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "FixtureManifest":
        if not isinstance(value, Mapping):
            raise ValueError("fixture manifest must be an object")
        version = str(value.get("schema_version") or FIXTURE_MANIFEST_VERSION)
        if version != FIXTURE_MANIFEST_VERSION:
            raise ValueError(f"unsupported fixture manifest schema: {version}")
        return cls(
            fixture_id=str(value.get("fixture_id") or ""),
            version=str(value.get("version") or ""),
            data_sha256=str(value.get("data_sha256") or ""),
            dependencies=dict(value.get("dependencies") or {}),
            setup_command=tuple(value.get("setup_command") or ()),
            cleanup_command=tuple(value.get("cleanup_command") or ()),
            environment=dict(value.get("environment") or {}),
        )

    def content_hash(self) -> str:
        raw = json.dumps(self.to_dict(), sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class EvaluationEpisode(TaskEpisode):
    """Task episode plus the runner, evidence and environment of one run."""

    runner: str = ""
    batch_id: str = ""
    trajectory: dict[str, Any] = field(default_factory=dict)
    score: dict[str, Any] = field(default_factory=dict)
    artifacts: tuple[ArtifactRef, ...] = ()
    environment: dict[str, Any] = field(default_factory=dict)
    created_at: str = ""
    fixture_manifest: FixtureManifest | None = None

    def __post_init__(self) -> None:
        super().__post_init__()
        if not str(self.runner).strip():
            raise ValueError("evaluation episode runner must not be empty")
        if not isinstance(self.trajectory, Mapping):
            raise ValueError("evaluation episode trajectory must be an object")
        if not isinstance(self.score, Mapping) or not isinstance(self.environment, Mapping):
            raise ValueError("evaluation episode score and environment must be objects")
        refs: list[ArtifactRef] = []
        for artifact in self.artifacts:
            if isinstance(artifact, ArtifactRef):
                refs.append(artifact)
            elif isinstance(artifact, Mapping):
                refs.append(ArtifactRef(**dict(artifact)))
            else:
                raise ValueError("evaluation episode artifacts must be ArtifactRef objects")
        object.__setattr__(self, "artifacts", tuple(refs))
        object.__setattr__(self, "trajectory", dict(self.trajectory))
        object.__setattr__(self, "score", dict(self.score))
        object.__setattr__(self, "environment", dict(self.environment))
        if self.fixture_manifest is not None and not isinstance(self.fixture_manifest, FixtureManifest):
            if isinstance(self.fixture_manifest, Mapping):
                object.__setattr__(self, "fixture_manifest", FixtureManifest.from_mapping(self.fixture_manifest))
            else:
                raise ValueError("fixture_manifest must be a FixtureManifest object")

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "schema_version": EVALUATION_EPISODE_VERSION,
            "episode": super().to_dict(),
            "episode_id": self.episode_id,
            "query": self.query,
            "acceptance_criteria": list(self.acceptance_criteria),
            "split": self.split,
            "fixture_ref": (
                self.fixture_manifest.fixture_ref
                if self.fixture_manifest is not None
                else self.fixture_ref
            ),
            "model_ref": self.model_ref,
            "tool_protocol_version": self.tool_protocol_version,
            "runner": self.runner,
            "batch_id": self.batch_id,
            "trajectory": dict(self.trajectory),
            "score": dict(self.score),
            "artifacts": [artifact.to_dict() for artifact in self.artifacts],
            "environment": dict(self.environment),
            "created_at": self.created_at,
        }
        if self.fixture_manifest is not None:
            payload["fixture_manifest"] = self.fixture_manifest.to_dict()
        return payload

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "EvaluationEpisode":
        if not isinstance(value, Mapping):
            raise ValueError("evaluation episode must be an object")
        version = str(value.get("schema_version") or EVALUATION_EPISODE_VERSION)
        if version.split("/", 1)[-1].split(".", 1)[0] != "v1":
            raise ValueError(f"unsupported evaluation episode schema: {version}")
        episode = value.get("episode") if isinstance(value.get("episode"), Mapping) else value
        return cls(
            episode_id=str(value.get("episode_id") or episode.get("episode_id") or ""),
            query=str(value.get("query") or episode.get("query") or ""),
            acceptance_criteria=tuple(value.get("acceptance_criteria") or episode.get("acceptance_criteria") or ()),
            split=str(value.get("split") or episode.get("split") or "dev"),
            fixture_ref=value.get("fixture_ref", episode.get("fixture_ref")),
            model_ref=value.get("model_ref", episode.get("model_ref")),
            tool_protocol_version=str(value.get("tool_protocol_version") or episode.get("tool_protocol_version") or CONTRACT_VERSION),
            runner=str(value.get("runner") or ""),
            batch_id=str(value.get("batch_id") or ""),
            trajectory=dict(value.get("trajectory") or {}),
            score=dict(value.get("score") or {}),
            artifacts=tuple(value.get("artifacts") or ()),
            environment=dict(value.get("environment") or {}),
            created_at=str(value.get("created_at") or ""),
            fixture_manifest=value.get("fixture_manifest"),
        )

    def validate_for_runner(self) -> None:
        """Reject an episode that cannot produce reproducible evaluation evidence."""
        missing: list[str] = []
        if not self.acceptance_criteria:
            missing.append("acceptance_criteria")
        if not self.fixture_ref and self.fixture_manifest is None:
            missing.append("fixture_ref or fixture_manifest")
        if not self.tool_protocol_version:
            missing.append("tool_protocol_version")
        if not self.batch_id:
            missing.append("batch_id")
        if missing:
            raise ValueError("evaluation episode missing required runner fields: " + ", ".join(missing))


__all__ = [
    "CONTRACT_VERSION",
    "EVALUATION_EPISODE_VERSION",
    "FIXTURE_MANIFEST_VERSION",
    "StopReason",
    "ToolError",
    "ToolCallError",
    "tool_error_from_exception",
    "ToolCall",
    "ArtifactRef",
    "TaskEpisode",
    "FixtureManifest",
    "EvaluationEpisode",
    "serialize_trajectory",
    "SCHEMA_VERSION",
    "TrajectorySchemaError",
    "assert_valid",
    "load_and_validate",
    "normalize_trajectory",
    "parse_trajectory",
    "validate_trajectory",
    "DependencyStatus",
    "check_dependency",
    "sibling_compatibility_report",
]
