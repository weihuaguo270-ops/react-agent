"""Adapters for repair/reverify evidence bundles."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from react_agent.harness.contracts import ArtifactRef, serialize_trajectory
from react_agent.harness.evaluation.fixtures import build_fixture_manifest_from_value, episode_from_case


def build_repair_evidence(
    *,
    task_id: str,
    task: Mapping[str, Any],
    records: Mapping[str, Mapping[str, Any]],
    source_files: Mapping[str, Path],
    phase: str,
    reverified: bool,
    patch_file: Path | None = None,
    run_id: str,
) -> dict[str, Any]:
    """Create shared episodes and provenance for an existing repair bundle."""
    inputs: dict[str, Any] = {
        "task": dict(task),
        "records": {key: dict(value) for key, value in records.items()},
        "source_sha256": {
            key: hashlib.sha256(path.read_bytes()).hexdigest()
            for key, path in source_files.items()
            if path.is_file()
        },
    }
    if patch_file is not None and patch_file.is_file():
        inputs["patch_sha256"] = hashlib.sha256(patch_file.read_bytes()).hexdigest()
    if reverified:
        dataset_status = "executed"
    elif phase.startswith("fixture_"):
        dataset_status = "fixture_evidence"
    else:
        dataset_status = "historical_evidence"
    fixture = build_fixture_manifest_from_value(
        inputs,
        fixture_id=f"software-repair:{task_id}",
        version="repair-evidence/v1",
        dependencies={"adapter": "react_agent.harness.evaluation.repair_evidence"},
        environment={"dataset_status": dataset_status, "evaluation_phase": phase},
    )
    batch_id = f"repair-{hashlib.sha256(f'{fixture.content_hash()}:{run_id}:{phase}'.encode()).hexdigest()[:16]}"
    acceptance = ["recorded baseline, repair, and post-repair evidence are traceable"]
    episodes = []
    for stage, record in records.items():
        status = str(record.get("status") or record.get("evidence_kind") or "recorded")
        passed = None if not reverified else status in {"succeeded", "passed", "applied"}
        trajectory = serialize_trajectory(
            session_id=f"repair:{task_id}:{run_id}:{stage}",
            query=f"Review {stage} evidence for software task {task_id}.",
            model="software-repair-evidence-adapter/v1",
            steps=[{
                "step": 1,
                "thought": "Preserve the source record and its measured stage outcome.",
                "action": {"name": f"record_{stage}_evidence", "arguments": json.dumps({"task_id": task_id, "stage": stage}, sort_keys=True)},
                "observation": json.dumps({"status": status, "exit_code": record.get("exit_code")}, sort_keys=True),
            }],
            final_answer=status,
            metadata={
                "evidence_only": not reverified,
                "execution_status": "executed" if reverified else "not_run_by_adapter",
                "evaluation_phase": phase,
                "run_id": run_id,
            },
        )
        encoded = json.dumps(trajectory, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        artifacts = [ArtifactRef(
            id=f"trajectory:{task_id}:{run_id}:{stage}", media_type="document",
            uri=f"trajectory://software-repair/{task_id}/{run_id}/{stage}",
            mime_type="application/json", sha256=hashlib.sha256(encoded).hexdigest(),
            metadata={"format": "harness-trajectory/v1", "phase": phase},
        )]
        source = source_files.get(stage)
        if source is not None and source.is_file():
            artifacts.append(ArtifactRef(
                id=f"source:{task_id}:{run_id}:{stage}", media_type="evidence",
                uri=f"artifact://{source.name}", mime_type="application/json",
                sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
                metadata={"stage": stage, "dataset_status": dataset_status},
            ))
        episodes.append(episode_from_case(
            {
                "id": f"{task_id}:{run_id}:{stage}",
                "question": f"Review {stage} evidence for software task {task_id}.",
                "acceptance_criteria": acceptance,
                "split": str(task.get("split") or "held_out"),
                "model_ref": "software-repair-evidence-adapter/v1",
            },
            fixture_manifest=fixture,
            runner="software-repair-evidence",
            batch_id=batch_id,
            trajectory=trajectory,
            score={"status": status, "passed": passed},
            environment={"evidence_only": not reverified, "evaluation_phase": phase, "run_id": run_id},
            artifacts=tuple(artifacts),
        ).to_dict())
    return {
        "fixture_manifest": fixture.to_dict(),
        "batch_id": batch_id,
        "evaluation_episodes": episodes,
        "source_sha256": inputs["source_sha256"],
        "patch_sha256": inputs.get("patch_sha256"),
        "run_id": run_id,
        "phase": phase,
        "reverified": reverified,
    }


__all__ = ["build_repair_evidence"]
