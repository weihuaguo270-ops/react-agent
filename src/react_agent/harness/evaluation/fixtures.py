"""Adapters that attach legacy dataset outputs to Shared Harness Contracts.

The existing loaders remain source-compatible. New evaluation code can use a
``FixtureBundle`` to carry both the parsed value and immutable fixture metadata.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Generic, Mapping, Sequence, TypeVar

from react_agent.harness.contracts import (
    EvaluationEpisode,
    FixtureManifest,
)

T = TypeVar("T")


@dataclass(frozen=True)
class FixtureBundle(Generic[T]):
    """Parsed loader output plus the exact fixture manifest used to load it."""

    value: T
    manifest: FixtureManifest


def build_fixture_manifest(
    path: str | Path,
    *,
    fixture_id: str | None = None,
    version: str = "v1",
    dependencies: Mapping[str, Any] | None = None,
    setup_command: tuple[str, ...] = (),
    cleanup_command: tuple[str, ...] = (),
    environment: Mapping[str, Any] | None = None,
) -> FixtureManifest:
    """Build a manifest from file bytes without modifying the fixture."""
    source = Path(path)
    if not source.is_file():
        raise FileNotFoundError(f"fixture not found: {source}")
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    safe_id = fixture_id or f"dataset:{source.stem}"
    # Keep manifests portable: absolute checkout paths are machine-specific
    # and make otherwise identical fixture evidence differ across runners.
    env = {"source_name": source.name}
    env.update({str(k): str(v) for k, v in (environment or {}).items()})
    return FixtureManifest(
        fixture_id=safe_id,
        version=version,
        data_sha256=digest,
        dependencies={str(k): str(v) for k, v in (dependencies or {}).items()},
        setup_command=setup_command,
        cleanup_command=cleanup_command,
        environment=env,
    )


def build_fixture_manifest_from_value(
    value: Any,
    *,
    fixture_id: str,
    version: str = "v1",
    source_name: str = "in-memory-fixture.json",
    dependencies: Mapping[str, Any] | None = None,
    setup_command: tuple[str, ...] = (),
    cleanup_command: tuple[str, ...] = (),
    environment: Mapping[str, Any] | None = None,
) -> FixtureManifest:
    """Build a portable manifest for a parsed fixture value.

    This is used by direct Runner callers that do not retain the dataset path;
    canonical JSON keeps the content hash identical across machines.
    """
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    env = {"source_name": source_name}
    env.update({str(k): str(v) for k, v in (environment or {}).items()})
    return FixtureManifest(
        fixture_id=fixture_id,
        version=version,
        data_sha256=hashlib.sha256(encoded).hexdigest(),
        dependencies={str(k): str(v) for k, v in (dependencies or {}).items()},
        setup_command=setup_command,
        cleanup_command=cleanup_command,
        environment=env,
    )


def load_json_fixture_bundle(
    path: str | Path,
    *,
    fixture_id: str | None = None,
    version: str = "v1",
    dependencies: Mapping[str, Any] | None = None,
) -> FixtureBundle[Any]:
    """Load a JSON fixture and preserve its byte hash in a manifest."""
    source = Path(path)
    manifest = build_fixture_manifest(
        source,
        fixture_id=fixture_id,
        version=version,
        dependencies=dependencies,
    )
    value = json.loads(source.read_text(encoding="utf-8"))
    return FixtureBundle(value=value, manifest=manifest)


def episode_from_case(
    case: Mapping[str, Any],
    *,
    fixture_manifest: FixtureManifest,
    runner: str,
    batch_id: str,
    trajectory: Mapping[str, Any] | None = None,
    score: Mapping[str, Any] | None = None,
    environment: Mapping[str, Any] | None = None,
    artifacts: Sequence[Mapping[str, Any] | Any] = (),
) -> EvaluationEpisode:
    """Convert legacy case dictionaries into a validated evaluation episode."""
    episode = EvaluationEpisode(
        episode_id=str(case.get("id") or case.get("task_id") or case.get("case_id") or ""),
        query=str(case.get("question") or case.get("query") or case.get("task") or ""),
        acceptance_criteria=tuple(
            str(item)
            for item in (
                case.get("acceptance_criteria")
                or case.get("must_contain")
                or case.get("must_contain_any")
                or ()
            )
        ),
        split=str(case.get("split") or "dev"),
        fixture_ref=fixture_manifest.fixture_ref,
        model_ref=str(case.get("model_ref") or case.get("model") or "") or None,
        runner=runner,
        batch_id=batch_id,
        trajectory=dict(trajectory or {}),
        score=dict(score or {}),
        artifacts=tuple(artifacts),
        environment=dict(environment or {}),
        fixture_manifest=fixture_manifest,
    )
    episode.validate_for_runner()
    return episode


__all__ = [
    "FixtureBundle",
    "build_fixture_manifest",
    "build_fixture_manifest_from_value",
    "load_json_fixture_bundle",
    "episode_from_case",
]
