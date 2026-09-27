from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from react_agent.eval.software_task_dataset import (
    DATASET_SCHEMA_VERSION,
    SoftwareTaskDataset,
    SoftwareTaskDatasetError,
    import_software_task_records,
)


def task(task_id: str, split: str, cluster: str) -> dict:
    return {
        "schema_version": "software-task/v1",
        "task_id": task_id,
        "repository": "https://github.com/acme/project",
        "issue_url": f"https://github.com/acme/project/issues/{task_id}",
        "base_commit": "0123456789abcdef",
        "split": split,
        "test_command": ["python", "-m", "pytest", "-q"],
        "hidden_test_command": ["python", "-m", "pytest", "tests/hidden"],
        "hidden_test_asset": "fastapi-15764/test_route_tags.py",
        "acceptance_criteria": ["tests pass"],
        "allowed_paths": ["src/"],
        "repository_cluster": cluster,
        "source": {
            "kind": "external_issue",
            "issue_url": f"https://github.com/acme/project/issues/{task_id}",
            "license": "MIT",
            "provenance_url": "https://github.com/acme/project/commit/0123456789abcdef",
        },
        "build": {"runtime_image": "python:3.11-slim", "install": []},
    }


def manifest(tasks: list[dict]) -> dict:
    return {
        "schema_version": DATASET_SCHEMA_VERSION,
        "dataset_id": "test",
        "version": "1",
        "status": "active",
        "license": "CC-BY-4.0",
        "source_policy": "public and reviewed",
        "tasks": tasks,
    }


def test_packaged_manifest_loads_with_reviewed_task():
    path = Path(__file__).parents[1] / "eval" / "software_task_dataset_manifest.json"
    dataset = SoftwareTaskDataset.load(path)
    assert dataset.status == "active"
    assert dataset.split_counts() == {"dev": 3, "golden": 0, "held_out": 0}


def test_duplicate_ids_and_cross_split_cluster_are_rejected():
    first = task("one", "dev", "cluster-a")
    with pytest.raises(SoftwareTaskDatasetError, match="duplicate task_id"):
        SoftwareTaskDataset.from_dict(manifest([first, copy.deepcopy(first)]))

    with pytest.raises(SoftwareTaskDatasetError, match="crosses splits"):
        SoftwareTaskDataset.from_dict(manifest([first, task("two", "held_out", "cluster-a")]))


def test_metadata_source_and_missing_hidden_test_are_rejected():
    item = task("one", "golden", "cluster-a")
    item["source"]["kind"] = "github_metadata"
    with pytest.raises(SoftwareTaskDatasetError, match="only external_issue"):
        SoftwareTaskDataset.from_dict(manifest([item]))

    item = task("one", "held_out", "cluster-a")
    item["hidden_test_command"] = []
    with pytest.raises(SoftwareTaskDatasetError, match="requires hidden_test_command"):
        SoftwareTaskDataset.from_dict(manifest([item]))


def test_hash_is_stable_when_task_order_changes():
    left = SoftwareTaskDataset.from_dict(manifest([task("b", "dev", "b"), task("a", "golden", "a")]))
    raw = manifest([task("a", "golden", "a"), task("b", "dev", "b")])
    right = SoftwareTaskDataset.from_dict(raw)
    assert left.content_hash() == right.content_hash()
    assert [x["task_id"] for x in left.to_dict()["tasks"]] == ["a", "b"]


def test_manifest_schema_declares_required_dataset_fields():
    schema = json.loads((Path(__file__).parents[1] / "schemas" / "software_task_dataset.schema.json").read_text(encoding="utf-8"))
    assert schema["properties"]["schema_version"]["const"] == DATASET_SCHEMA_VERSION
    assert set(schema["required"]) >= {"dataset_id", "status", "tasks"}


def test_jsonl_records_can_be_imported_and_normalized(tmp_path):
    records = tmp_path / "reviewed.jsonl"
    records.write_text(json.dumps(task("one", "dev", "cluster-a")) + "\n", encoding="utf-8")
    output = tmp_path / "manifest.json"
    imported = import_software_task_records(records, output)
    assert imported.status == "active"
    assert imported.split_counts()["dev"] == 1
    loaded = SoftwareTaskDataset.load(output)
    assert loaded.content_hash() == imported.content_hash()
