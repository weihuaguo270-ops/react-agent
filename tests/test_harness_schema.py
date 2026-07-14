"""CI / unit tests for Harness Format B schema."""
import json
import os
import sys

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(ROOT, "src"))

from react_agent.harness.schema import (
    TrajectorySchemaError,
    assert_valid,
    normalize_trajectory,
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
