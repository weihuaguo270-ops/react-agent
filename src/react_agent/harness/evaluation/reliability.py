"""Adapters for reliability reports into the shared evaluation contract."""
from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping

from react_agent.harness.contracts import ArtifactRef, FixtureManifest, serialize_trajectory

from .fixtures import build_fixture_manifest_from_value, episode_from_case


def build_reliability_manifest(
    value: Any,
    *,
    fixture_id: str,
    format_name: str,
    dependencies: Mapping[str, Any] | None = None,
) -> FixtureManifest:
    return build_fixture_manifest_from_value(
        value,
        fixture_id=fixture_id,
        dependencies={"format": format_name, **dict(dependencies or {})},
        source_name=f"{fixture_id.replace(':', '_')}.json",
    )


def reliability_episode(
    *,
    episode_id: str,
    query: str,
    acceptance: list[str] | tuple[str, ...],
    result: Mapping[str, Any],
    fixture_manifest: FixtureManifest,
    batch_id: str,
    runner: str,
    split: str = "dev",
) -> dict[str, Any]:
    """Create one auditable Episode for a reliability scenario or HTTP run."""
    raw_trajectory = result.get("trajectory")
    if isinstance(raw_trajectory, Mapping) and raw_trajectory.get("steps"):
        steps = list(raw_trajectory["steps"])
        session_id = str(raw_trajectory.get("session_id") or f"reliability:{episode_id}")
        final_answer = str(raw_trajectory.get("final_answer") or "")
    else:
        steps = [{
            "step": 1,
            "action": {
                "name": "reliability_probe",
                "arguments": json.dumps(
                    {"guard_on": result.get("guard_on"), "mode": result.get("mode")},
                    ensure_ascii=False,
                    sort_keys=True,
                ),
            },
            "observation": json.dumps(dict(result), ensure_ascii=False, sort_keys=True)[:4000],
        }]
        session_id = f"reliability:{episode_id}"
        final_answer = "passed" if result.get("passed") else "failed"
    trajectory = serialize_trajectory(
        session_id=session_id,
        query=query,
        steps=steps,
        final_answer=final_answer,
        metadata={
            "transport": "reliability",
            "runner": runner,
            "guard_on": result.get("guard_on"),
        },
    )
    encoded = json.dumps(
        trajectory, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    episode = episode_from_case(
        {
            "id": episode_id,
            "question": query,
            "acceptance_criteria": list(acceptance),
            "split": split,
        },
        fixture_manifest=fixture_manifest,
        runner=runner,
        batch_id=batch_id,
        trajectory=trajectory,
        score={
            "passed": bool(result.get("passed")),
            "status": "passed" if result.get("passed") else "failed",
        },
        environment={
            "mode": str(result.get("mode") or ""),
            "exit_code": str(result.get("exit_code", "")),
            "duration_seconds": str(result.get("duration_seconds", "")),
        },
        artifacts=(ArtifactRef(
            id=f"trajectory:{session_id}",
            media_type="document",
            uri=f"trajectory://{session_id}",
            mime_type="application/json",
            sha256=hashlib.sha256(encoded).hexdigest(),
            metadata={"format": "harness-trajectory/v1", "reliability_runner": runner},
        ),),
    )
    return episode.to_dict()


__all__ = ["build_reliability_manifest", "reliability_episode"]
