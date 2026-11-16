from __future__ import annotations

import json
from pathlib import Path

import pytest

from react_agent.skills import (
    BusinessBoundary,
    BusinessBoundaryError,
    get_skill,
    list_business_boundaries,
    list_skills,
)


def test_builtin_boundaries_match_registered_skills():
    skills = {item["name"]: item for item in list_skills(detail="full")}
    boundaries = {item["name"]: item for item in list_business_boundaries([get_skill(name) for name in skills])}
    assert set(boundaries) == set(skills)
    for name, boundary in boundaries.items():
        assert boundary["workflow"] == skills[name]["workflow"]
        assert boundary["risk_level"] == skills[name]["risk_level"]
        assert boundary["required_steps"]
        assert boundary["success_conditions"]


def test_boundary_rejects_forbidden_explicit_action():
    boundary = get_skill("docs_troubleshoot").boundary
    assert boundary is not None
    assert boundary.validate_request({"requested_action": "restart_service"})
    assert boundary.validate_request({"requested_action": "search_docs"}) == []


def test_non_agent_boundary_rejects_agent_caller():
    boundary = BusinessBoundary(
        name="controlled_write",
        version="1",
        scenario="controlled",
        purpose="controlled write skill",
        workflow="controlled@1",
        risk_level="external_write",
        agent_callable=False,
        owner="platform",
        allowed_tools=(),
        required_steps=("prepare",),
        required_inputs=("payload",),
        required_outputs=("status",),
        success_conditions=("approved",),
        human_handoff_conditions=("needs approval",),
        forbidden_actions=("write_main_branch",),
    )
    assert "not callable by the Agent runtime" in " ".join(
        boundary.validate_request({"_caller": "agent"})
    )


def test_boundary_definition_requires_steps_and_success_conditions():
    boundary = BusinessBoundary(
        name="x", version="1", scenario="x", purpose="x",
    )
    with pytest.raises(BusinessBoundaryError):
        boundary.validate_definition()


def test_boundary_schema_is_checked_in():
    schema_path = Path(__file__).parents[2] / "schemas" / "business_boundary.schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    assert schema["$schema"].endswith("2020-12/schema")
    assert "forbidden_actions" in schema["required"]

