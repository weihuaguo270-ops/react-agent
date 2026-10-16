"""Deterministic replay manifests for the runtime Harness.

``react_agent.harness.replay.Replay`` remains the legacy display helper.  This
module adds an execution-aware manifest with explicit integrity and safety
boundaries so a displayed trajectory cannot be mistaken for a replay run.
"""
from __future__ import annotations

import hashlib
import json
import os
import uuid
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from react_agent.harness.contracts import CONTRACT_VERSION, assert_valid


REPLAY_MANIFEST_VERSION = "replay-manifest/v1"
REPLAY_SCORING_INPUT_VERSION = "replay-scoring-input/v1"


class ReplayMode(str, Enum):
    RECORD = "record"
    REPLAY = "replay"
    INSPECT = "inspect"


class ReplayError(RuntimeError):
    """Base error for fail-closed replay operations."""


class ReplayFixtureUnavailable(ReplayError):
    """Raised when a replay cannot obtain its required Fixture."""


class ReplayIntegrityError(ReplayError):
    """Raised when manifest or component hashes do not match."""


class ReplaySideEffectDenied(ReplayError):
    """Raised when replay code attempts network or external side effects."""


class ReplayResourceExceeded(ReplayError):
    """Raised when a replay exceeds its deterministic resource budget."""


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha256(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _copy_json(value: Any) -> Any:
    """Copy and validate JSON-compatible evidence without preserving objects."""
    try:
        return json.loads(_canonical(value))
    except (TypeError, ValueError) as exc:
        raise ReplayIntegrityError(f"replay evidence must be JSON-compatible: {exc}") from exc


def _new_manifest_id() -> str:
    return f"replay-{uuid.uuid4().hex}"


def _component_hashes(
    trajectory: Mapping[str, Any], tool_results: Any, model_responses: Any, fixture: Any
) -> dict[str, str]:
    return {
        "trajectory_sha256": _sha256(trajectory),
        "tool_results_sha256": _sha256(tool_results),
        "model_responses_sha256": _sha256(model_responses),
        "fixture_sha256": _sha256(fixture) if fixture is not None else "",
    }


@dataclass(frozen=True)
class ReplayManifest:
    """Immutable record of all inputs required for deterministic replay."""

    manifest_id: str
    trajectory: dict[str, Any]
    tool_results: Any = field(default_factory=dict)
    model_responses: Any = field(default_factory=list)
    fixture: dict[str, Any] | None = None
    protocol_version: str = CONTRACT_VERSION
    code_version: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    trajectory_sha256: str = ""
    tool_results_sha256: str = ""
    model_responses_sha256: str = ""
    fixture_sha256: str = ""
    manifest_sha256: str = ""

    def __post_init__(self) -> None:
        if not str(self.manifest_id).strip():
            raise ValueError("replay manifest_id must not be empty")
        if not str(self.protocol_version).strip():
            raise ValueError("replay protocol_version must not be empty")
        if not isinstance(self.trajectory, Mapping):
            raise ValueError("replay trajectory must be an object")
        trajectory = _copy_json(dict(self.trajectory))
        assert_valid(trajectory)
        object.__setattr__(self, "trajectory", trajectory)
        object.__setattr__(self, "tool_results", _copy_json(self.tool_results))
        object.__setattr__(self, "model_responses", _copy_json(self.model_responses))
        if self.fixture is not None:
            fixture = _copy_json(dict(self.fixture))
            if not fixture:
                raise ValueError("replay fixture must not be empty")
            for required in ("fixture_id", "version", "data_sha256"):
                if not str(fixture.get(required) or "").strip():
                    raise ValueError(f"replay fixture.{required} must not be empty")
            object.__setattr__(self, "fixture", fixture)
        object.__setattr__(self, "metadata", _copy_json(dict(self.metadata or {})))
        hashes = _component_hashes(
            self.trajectory, self.tool_results, self.model_responses, self.fixture
        )
        for name, expected in hashes.items():
            supplied = str(getattr(self, name) or "")
            if supplied and supplied != expected:
                raise ReplayIntegrityError(f"replay {name} does not match manifest content")
            object.__setattr__(self, name, expected)
        expected_manifest_hash = _sha256(self._payload_with_hashes(hashes))
        if self.manifest_sha256 and self.manifest_sha256 != expected_manifest_hash:
            raise ReplayIntegrityError("replay manifest_sha256 does not match manifest content")
        object.__setattr__(self, "manifest_sha256", expected_manifest_hash)

    def _payload_with_hashes(self, hashes: Mapping[str, str]) -> dict[str, Any]:
        return {
            "schema_version": REPLAY_MANIFEST_VERSION,
            "manifest_id": self.manifest_id,
            "protocol_version": self.protocol_version,
            "code_version": self.code_version,
            "trajectory": self.trajectory,
            "tool_results": self.tool_results,
            "model_responses": self.model_responses,
            "fixture": self.fixture,
            "metadata": self.metadata,
            **dict(hashes),
        }

    def to_dict(self) -> dict[str, Any]:
        hashes = {
            "trajectory_sha256": self.trajectory_sha256,
            "tool_results_sha256": self.tool_results_sha256,
            "model_responses_sha256": self.model_responses_sha256,
            "fixture_sha256": self.fixture_sha256,
        }
        return {**self._payload_with_hashes(hashes), "manifest_sha256": self.manifest_sha256}

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "ReplayManifest":
        if not isinstance(value, Mapping):
            raise ValueError("replay manifest must be an object")
        version = str(value.get("schema_version") or "")
        if version != REPLAY_MANIFEST_VERSION:
            raise ValueError(f"unsupported replay manifest schema: {version}")
        return cls(
            manifest_id=str(value.get("manifest_id") or ""),
            trajectory=dict(value.get("trajectory") or {}),
            tool_results=value["tool_results"] if "tool_results" in value else {},
            model_responses=value["model_responses"] if "model_responses" in value else [],
            fixture=dict(value["fixture"]) if isinstance(value.get("fixture"), Mapping) else None,
            protocol_version=str(value.get("protocol_version") or ""),
            code_version=str(value.get("code_version") or ""),
            metadata=dict(value.get("metadata") or {}),
            trajectory_sha256=str(value.get("trajectory_sha256") or ""),
            tool_results_sha256=str(value.get("tool_results_sha256") or ""),
            model_responses_sha256=str(value.get("model_responses_sha256") or ""),
            fixture_sha256=str(value.get("fixture_sha256") or ""),
            manifest_sha256=str(value.get("manifest_sha256") or ""),
        )

    @classmethod
    def load(cls, path: str | os.PathLike[str]) -> "ReplayManifest":
        target = Path(path)
        try:
            payload = json.loads(target.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ReplayIntegrityError(f"unable to load replay manifest: {target}") from exc
        return cls.from_mapping(payload)

    def save(self, path: str | os.PathLike[str]) -> str:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps(self.to_dict(), ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        return str(target)

    def content_hash(self) -> str:
        return self.manifest_sha256

    @property
    def stop_reason(self) -> str | None:
        metadata = self.trajectory.get("metadata")
        if isinstance(metadata, Mapping) and metadata.get("stop_reason"):
            return str(metadata["stop_reason"])
        value = self.trajectory.get("stop_reason")
        return str(value) if value else None


@dataclass(frozen=True)
class ReplayResult:
    """Result of an inspect or execution replay with explicit provenance."""

    mode: ReplayMode
    execution_replay: bool
    display_only: bool
    manifest_id: str
    trajectory: dict[str, Any]
    tool_results: Any
    model_responses: Any
    scoring_input: dict[str, Any]
    stop_reason: str | None
    network_allowed: bool = False
    side_effects_allowed: bool = False
    resource_usage: dict[str, int] = field(default_factory=dict)

    @property
    def scoring_input_sha256(self) -> str:
        return _sha256(self.scoring_input)

    def to_scoring_input(self, *, runner: str = "") -> dict[str, Any]:
        """Return the runner-neutral payload consumed by any scorer.

        ``runner`` is provenance only; it does not alter the trajectory or
        recorded tool results, so ReAct, Workflow and HTTP adapters score the
        same manifest from the same canonical input.
        """
        if not self.execution_replay or self.display_only:
            raise ReplayError("display-only manifests cannot be used as scoring input")
        payload = _copy_json(self.scoring_input)
        payload["runner"] = str(runner or "")
        trajectory = payload.get("trajectory")
        if isinstance(trajectory, Mapping):
            payload["execution_mode"] = str(trajectory.get("execution_mode") or "")
            payload["transport"] = str(trajectory.get("transport") or "")
        return payload

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode.value,
            "execution_replay": self.execution_replay,
            "display_only": self.display_only,
            "manifest_id": self.manifest_id,
            "trajectory": self.trajectory,
            "tool_results": self.tool_results,
            "model_responses": self.model_responses,
            "scoring_input": self.scoring_input,
            "scoring_input_sha256": self.scoring_input_sha256,
            "stop_reason": self.stop_reason,
            "network_allowed": self.network_allowed,
            "side_effects_allowed": self.side_effects_allowed,
            "resource_usage": dict(self.resource_usage),
        }


@dataclass(frozen=True)
class ReplayLimits:
    """Upper bounds for manifest-driven replay work.

    Replay never calls a live tool. The limits still protect runners from
    malformed manifests containing unexpectedly large trajectories or result
    payloads.
    """

    max_steps: int = 1_000
    max_tool_calls: int = 1_000
    max_output_bytes: int = 1_048_576

    def __post_init__(self) -> None:
        for name in ("max_steps", "max_tool_calls", "max_output_bytes"):
            value = int(getattr(self, name))
            if value < 1:
                raise ValueError(f"replay limit {name} must be >= 1")
            object.__setattr__(self, name, value)


class RecordedToolExecutor:
    """Resolve tool calls from recorded manifest results only.

    This deliberately has no fallback callback: an unknown call is a hard
    replay failure instead of an opportunity to invoke a live tool.
    """

    def __init__(self, tool_results: Any):
        self._records = tool_results
        self._ordinal = 0

    def execute(self, action: Mapping[str, Any]) -> Any:
        self._ordinal += 1
        call_id = str(action.get("call_id") or action.get("id") or "")
        name = str(action.get("name") or action.get("tool") or "")
        record = _lookup_tool_result(self._records, call_id, name, self._ordinal)
        if record is _MISSING:
            label = call_id or name or f"ordinal-{self._ordinal}"
            raise ReplayIntegrityError(f"missing recorded tool result: {label}")
        return _extract_tool_result(record)


class DeterministicReplay:
    """Record, execute, or inspect a replay manifest with fail-closed guards."""

    def __init__(
        self,
        *,
        fixture_loader: Callable[[Mapping[str, Any]], Any] | None = None,
        network_allowed: bool = False,
        side_effects_allowed: bool = False,
        limits: ReplayLimits | None = None,
    ) -> None:
        self.fixture_loader = fixture_loader
        self.network_allowed = network_allowed
        self.side_effects_allowed = side_effects_allowed
        self.limits = limits or ReplayLimits()

    @staticmethod
    def record(
        trajectory: Mapping[str, Any],
        *,
        tool_results: Any = None,
        model_responses: Any = None,
        fixture: Mapping[str, Any] | None = None,
        protocol_version: str = CONTRACT_VERSION,
        code_version: str = "",
        metadata: Mapping[str, Any] | None = None,
        manifest_id: str | None = None,
    ) -> ReplayManifest:
        """Capture immutable replay inputs without executing any operation."""
        return ReplayManifest(
            manifest_id=manifest_id or _new_manifest_id(),
            trajectory=dict(trajectory),
            tool_results={} if tool_results is None else tool_results,
            model_responses=[] if model_responses is None else model_responses,
            fixture=dict(fixture) if fixture is not None else None,
            protocol_version=protocol_version,
            code_version=code_version,
            metadata=dict(metadata or {}),
        )

    def replay(
        self,
        manifest: ReplayManifest | Mapping[str, Any] | str | os.PathLike[str],
        *,
        fixture: Any = None,
    ) -> ReplayResult:
        """Replay recorded inputs only; no live model, network, or side effect."""
        parsed = _coerce_manifest(manifest)
        self._verify(parsed)
        fixture_value = self._resolve_fixture(parsed, fixture)
        replayed_trajectory, resource_usage = self._execute_recorded_trajectory(parsed)
        scoring_input = {
            "schema_version": REPLAY_SCORING_INPUT_VERSION,
            "source": "deterministic_replay",
            "manifest_id": parsed.manifest_id,
            "manifest_sha256": parsed.manifest_sha256,
            "protocol_version": parsed.protocol_version,
            "trajectory": replayed_trajectory,
            "tool_results": parsed.tool_results,
            "model_responses": parsed.model_responses,
            "fixture": parsed.fixture,
            "stop_reason": parsed.stop_reason,
            "resource_usage": resource_usage,
        }
        if fixture_value is not None:
            scoring_input["fixture_loaded_sha256"] = _fixture_value_hash(fixture_value)
        return ReplayResult(
            mode=ReplayMode.REPLAY,
            execution_replay=True,
            display_only=False,
            manifest_id=parsed.manifest_id,
            trajectory=replayed_trajectory,
            tool_results=parsed.tool_results,
            model_responses=parsed.model_responses,
            scoring_input=scoring_input,
            stop_reason=parsed.stop_reason,
            network_allowed=False,
            side_effects_allowed=False,
            resource_usage=resource_usage,
        )

    def inspect(
        self, manifest: ReplayManifest | Mapping[str, Any] | str | os.PathLike[str]
    ) -> ReplayResult:
        """Inspect a manifest; this never claims that execution occurred."""
        parsed = _coerce_manifest(manifest)
        self._verify(parsed)
        return ReplayResult(
            mode=ReplayMode.INSPECT,
            execution_replay=False,
            display_only=True,
            manifest_id=parsed.manifest_id,
            trajectory=parsed.trajectory,
            tool_results=parsed.tool_results,
            model_responses=parsed.model_responses,
            scoring_input={"manifest_id": parsed.manifest_id, "manifest_sha256": parsed.manifest_sha256},
            stop_reason=parsed.stop_reason,
        )

    def run(self, mode: ReplayMode | str, **kwargs: Any) -> ReplayManifest | ReplayResult:
        selected = ReplayMode(mode)
        if selected is ReplayMode.RECORD:
            return self.record(**kwargs)
        if selected is ReplayMode.REPLAY:
            return self.replay(**kwargs)
        if selected is ReplayMode.INSPECT:
            return self.inspect(**kwargs)
        raise ValueError(f"unsupported replay mode: {mode}")

    def assert_network_allowed(self, operation: str = "network request") -> None:
        if not self.network_allowed:
            raise ReplaySideEffectDenied(f"{operation} denied during deterministic replay")

    def assert_side_effect_allowed(self, operation: str = "side effect") -> None:
        if not self.side_effects_allowed:
            raise ReplaySideEffectDenied(f"{operation} denied during deterministic replay")

    def _verify(self, manifest: ReplayManifest) -> None:
        if not manifest.stop_reason:
            raise ReplayIntegrityError("replay manifest is missing stop_reason")
        if manifest.protocol_version != CONTRACT_VERSION:
            raise ReplayIntegrityError(
                f"unsupported replay protocol version: {manifest.protocol_version}"
            )

    def _execute_recorded_trajectory(
        self, manifest: ReplayManifest
    ) -> tuple[dict[str, Any], dict[str, int]]:
        trajectory = _copy_json(manifest.trajectory)
        steps = trajectory.get("steps") or []
        if not isinstance(steps, list):
            raise ReplayIntegrityError("replay trajectory steps must be an array")
        if len(steps) > self.limits.max_steps:
            raise ReplayResourceExceeded("replay max_steps exceeded")

        executor = RecordedToolExecutor(manifest.tool_results)
        tool_calls = 0
        output_bytes = 0
        replayed_steps: list[dict[str, Any]] = []
        for raw_step in steps:
            step = dict(raw_step or {})
            actions: list[Mapping[str, Any]] = []
            action = step.get("action")
            if isinstance(action, Mapping) and (action.get("name") or action.get("tool")):
                actions.append(action)
            for item in step.get("actions") or []:
                if isinstance(item, Mapping) and (item.get("name") or item.get("tool")):
                    actions.append(item)
            replay_results: list[Any] = []
            for item in actions:
                tool_calls += 1
                if tool_calls > self.limits.max_tool_calls:
                    raise ReplayResourceExceeded("replay max_tool_calls exceeded")
                result = executor.execute(item)
                replay_results.append(_copy_json(result))
                output_bytes += len(_canonical(result).encode("utf-8"))
                if output_bytes > self.limits.max_output_bytes:
                    raise ReplayResourceExceeded("replay max_output_bytes exceeded")
            if replay_results:
                step["replay_tool_results"] = replay_results
                if len(replay_results) == 1:
                    step["observation"] = _display_tool_result(replay_results[0])
            replayed_steps.append(step)
        trajectory["steps"] = replayed_steps
        metadata = dict(trajectory.get("metadata") or {})
        metadata["replay_execution"] = "recorded_tool_results"
        metadata["replay_tool_calls"] = tool_calls
        metadata["replay_output_bytes"] = output_bytes
        trajectory["metadata"] = metadata
        if _trajectory_stop_reason(trajectory) != manifest.stop_reason:
            raise ReplayIntegrityError("replay stop_reason changed during execution")
        return trajectory, {
            "steps": len(steps),
            "tool_calls": tool_calls,
            "output_bytes": output_bytes,
        }

    def _resolve_fixture(self, manifest: ReplayManifest, fixture: Any) -> Any:
        if manifest.fixture is None:
            raise ReplayFixtureUnavailable("replay requires a Fixture manifest")
        value = fixture
        if value is None and self.fixture_loader is not None:
            value = self.fixture_loader(manifest.fixture)
        if value is None:
            raise ReplayFixtureUnavailable(
                f"Fixture unavailable for replay: {manifest.fixture.get('fixture_id', 'unknown')}"
            )
        expected = str(manifest.fixture.get("data_sha256") or "").removeprefix("sha256:")
        if expected and _fixture_value_hash(value) != expected:
            raise ReplayIntegrityError("loaded Fixture hash does not match replay manifest")
        return value


def _fixture_value_hash(value: Any) -> str:
    if isinstance(value, bytes):
        return hashlib.sha256(value).hexdigest()
    if isinstance(value, (str, os.PathLike)):
        target = Path(value)
        if target.is_file():
            return hashlib.sha256(target.read_bytes()).hexdigest()
    return _sha256(value)


_MISSING = object()


def _lookup_tool_result(records: Any, call_id: str, name: str, ordinal: int) -> Any:
    if isinstance(records, Mapping):
        for key in (call_id, name, str(ordinal), ordinal):
            if key and key in records:
                return records[key]
        if ordinal == 1 and len(records) == 1:
            return next(iter(records.values()))
        return _MISSING
    if isinstance(records, Sequence) and not isinstance(records, (str, bytes, bytearray)):
        index = ordinal - 1
        if index < len(records):
            candidate = records[index]
            if isinstance(candidate, Mapping):
                candidate_id = str(candidate.get("call_id") or candidate.get("id") or "")
                candidate_name = str(candidate.get("tool") or candidate.get("name") or "")
                if (call_id and candidate_id and call_id != candidate_id) or (
                    name and candidate_name and name != candidate_name
                ):
                    return _MISSING
            return candidate
    return _MISSING


def _extract_tool_result(record: Any) -> Any:
    if isinstance(record, Mapping):
        if "error" in record:
            return {"error": record["error"], **dict(record)}
        for key in ("result", "output", "observation", "value"):
            if key in record:
                return record[key]
    return record


def _display_tool_result(value: Any) -> str:
    if isinstance(value, str):
        return value
    return _canonical(value)


def _trajectory_stop_reason(trajectory: Mapping[str, Any]) -> str | None:
    metadata = trajectory.get("metadata")
    if isinstance(metadata, Mapping) and metadata.get("stop_reason"):
        return str(metadata["stop_reason"])
    value = trajectory.get("stop_reason")
    return str(value) if value else None


def _coerce_manifest(
    value: ReplayManifest | Mapping[str, Any] | str | os.PathLike[str],
) -> ReplayManifest:
    if isinstance(value, ReplayManifest):
        return value
    if isinstance(value, (str, os.PathLike)):
        return ReplayManifest.load(value)
    return ReplayManifest.from_mapping(value)


__all__ = [
    "REPLAY_MANIFEST_VERSION",
    "REPLAY_SCORING_INPUT_VERSION",
    "ReplayMode",
    "ReplayManifest",
    "ReplayResult",
    "ReplayError",
    "ReplayFixtureUnavailable",
    "ReplayIntegrityError",
    "ReplaySideEffectDenied",
    "ReplayResourceExceeded",
    "ReplayLimits",
    "RecordedToolExecutor",
    "DeterministicReplay",
]
