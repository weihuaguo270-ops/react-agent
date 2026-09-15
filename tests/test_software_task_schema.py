from __future__ import annotations

import json
from pathlib import Path

import pytest

from react_agent.eval.software_task import SCHEMA_VERSION, SoftwareTask


def payload(**overrides):
    value = {
        "schema_version": SCHEMA_VERSION,
        "task_id": "issue-001",
        "repository": "https://github.com/example/project",
        "issue_url": "https://github.com/example/project/issues/1",
        "base_commit": "0123456789abcdef",
        "split": "golden",
        "test_command": ["python", "-m", "pytest", "-q"],
        "hidden_test_command": ["python", "-m", "pytest", "tests/hidden"],
        "acceptance_criteria": ["target test passes", "no unauthorized file changes"],
        "allowed_paths": ["src/", "tests/"],
        "timeout_seconds": 300,
    }
    value.update(overrides)
    return value


def test_task_round_trip_and_hash_are_stable():
    task = SoftwareTask.from_dict(payload())
    assert SoftwareTask.from_dict(task.to_dict()).to_dict() == task.to_dict()
    assert task.content_hash() == SoftwareTask.from_dict(task.to_dict()).content_hash()


@pytest.mark.parametrize(
    "overrides",
    [
        {"base_commit": ""},
        {"split": "production"},
        {"allowed_paths": []},
        {"test_command": []},
        {"timeout_seconds": 0},
        {"task_id": "bad id"},
    ],
)
def test_task_rejects_unreproducible_contracts(overrides):
    with pytest.raises(ValueError):
        SoftwareTask.from_dict(payload(**overrides))


def test_schema_document_matches_contract_shape():
    schema = json.loads((Path(__file__).parents[1] / "schemas" / "software_task.schema.json").read_text(encoding="utf-8"))
    assert schema["properties"]["schema_version"]["const"] == SCHEMA_VERSION
    assert set(schema["required"]) >= {"base_commit", "allowed_paths", "acceptance_criteria"}
