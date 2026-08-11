"""CI / unit tests for Harness Format B schema."""
import json
import os
import sys

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(ROOT, "src"))

from react_agent.harness.schema import (
    SCHEMA_VERSION,
    TrajectorySchemaError,
    assert_valid,
    normalize_trajectory,
    schema_major,
    validate_trajectory,
)

FIXTURE = os.path.join(ROOT, "examples", "fixtures", "harness_closed_loop.json")


def test_fixture_validates():
    with open(FIXTURE, encoding="utf-8") as f:
        data = json.load(f)
    assert validate_trajectory(data) == []
    assert_valid(data)


def test_rejects_zero_based_step():
    bad = {
        "session_id": "x",
        "query": "q",
        "final_answer": "a",
        "steps": [{"step": 0, "thought": "legacy"}],
    }
    issues = validate_trajectory(bad)
    assert any(">= 1" in i for i in issues)
    with pytest.raises(TrajectorySchemaError):
        assert_valid(bad)


def test_normalize_args_object_to_arguments_string():
    raw = {
        "session_id": "x",
        "query": "q",
        "final_answer": "a",
        "steps": [
            {
                "step": 1,
                "action": {"name": "web_search", "args": {"query": "hi"}},
                "observation": "ok",
            }
        ],
    }
    assert validate_trajectory(raw) == []
    norm = normalize_trajectory(raw)
    action = norm["steps"][0]["action"]
    assert isinstance(action["arguments"], str)
    assert "hi" in action["arguments"]


def test_actions_array_gets_singular_action():
    raw = {
        "session_id": "x",
        "query": "q",
        "final_answer": "a",
        "steps": [
            {
                "step": 1,
                "actions": [
                    {"name": "web_search", "arguments": "{}"},
                    {"name": "calculator", "arguments": "{\"expr\": \"1+1\"}"},
                ],
            }
        ],
    }
    norm = normalize_trajectory(raw)
    assert norm["steps"][0]["action"]["name"] == "web_search"


def test_schema_version_constant_is_major_1():
    assert schema_major(SCHEMA_VERSION) == "1"


def test_missing_schema_version_is_ok():
    raw = {
        "session_id": "x",
        "query": "q",
        "final_answer": "a",
        "steps": [{"step": 1, "thought": "t"}],
    }
    assert validate_trajectory(raw) == []


def test_incompatible_schema_major_fails():
    bad = {
        "session_id": "x",
        "query": "q",
        "final_answer": "a",
        "schema_version": "99",
        "steps": [{"step": 1, "thought": "t"}],
    }
    issues = validate_trajectory(bad)
    assert any("incompatible" in i for i in issues)
    with pytest.raises(TrajectorySchemaError):
        assert_valid(bad)


def test_normalize_stamps_schema_version():
    raw = {
        "session_id": "x",
        "query": "q",
        "final_answer": "a",
        "steps": [{"step": 1, "thought": "t"}],
    }
    norm = normalize_trajectory(raw)
    assert norm["schema_version"] == SCHEMA_VERSION
    assert "schema_version" not in raw

def test_multimodal_artifact_references_validate_and_normalize():
    raw = {
        "session_id": "media-1",
        "query": "describe the image",
        "final_answer": "a chart",
        "input_artifacts": [
            {
                "id": "image-1",
                "media_type": "image",
                "uri": "artifacts/input.png",
                "mime_type": "image/png",
                "width": 640,
                "height": 480,
                "metadata": {"source": "fixture"},
            }
        ],
        "output_artifacts": [],
        "steps": [
            {
                "step": 1,
                "thought": "inspect",
                "artifacts": [
                    {
                        "id": "frame-1",
                        "media_type": "image",
                        "uri": "artifacts/frame-1.png",
                    }
                ],
            }
        ],
    }
    assert validate_trajectory(raw) == []
    normalized = normalize_trajectory(raw)
    assert normalized["input_artifacts"][0]["width"] == 640


def test_multimodal_artifact_rejects_embedded_data():
    raw = {
        "session_id": "media-2",
        "query": "q",
        "final_answer": "a",
        "input_artifacts": [
            {
                "id": "image-1",
                "media_type": "image",
                "uri": "memory://image-1",
                "base64": "not-allowed",
            }
        ],
        "steps": [{"step": 1}],
    }
    issues = validate_trajectory(raw)
    assert any("embedded media data" in issue for issue in issues)
