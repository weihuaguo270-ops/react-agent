"""Business delivery boundaries shared by Skills and their workflows.

The boundary is deliberately small: it describes the business contract and
the actions that must never be inferred from a natural-language request. The
workflow and policy implementation remain the enforcement authority.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


class BusinessBoundaryError(ValueError):
    """Raised when a business boundary is incomplete or inconsistent."""


@dataclass(frozen=True)
class BusinessBoundary:
    name: str
    version: str
    scenario: str
    purpose: str
    allowed_tools: tuple[str, ...] = ()
    required_steps: tuple[str, ...] = ()
    required_inputs: tuple[str, ...] = ()
    required_outputs: tuple[str, ...] = ()
    success_conditions: tuple[str, ...] = ()
    human_handoff_conditions: tuple[str, ...] = ()
    forbidden_actions: tuple[str, ...] = ()
    risk_level: str = "read_only"
    agent_callable: bool = True
    workflow: str = ""
    owner: str = "react-agent"
    status: str = "active"
    supersedes: str = ""
    metadata: dict[str, Any] = field(default_factory=dict, compare=False)

    def validate_definition(self) -> None:
        if not self.name.strip() or not self.version.strip():
            raise BusinessBoundaryError("boundary name and version are required")
        if not self.scenario.strip() or not self.purpose.strip():
            raise BusinessBoundaryError("boundary scenario and purpose are required")
        if not self.required_steps:
            raise BusinessBoundaryError(f"boundary {self.name} must declare required_steps")
        if not self.success_conditions:
            raise BusinessBoundaryError(
                f"boundary {self.name} must declare success_conditions"
            )
        if self.risk_level not in {"read_only", "business_write", "external_write"}:
            raise BusinessBoundaryError(f"unsupported boundary risk level: {self.risk_level}")
        if self.status not in {"active", "experimental", "deprecated"}:
            raise BusinessBoundaryError(f"unsupported boundary status: {self.status}")
        if self.status == "deprecated" and not self.supersedes:
            raise BusinessBoundaryError("deprecated boundary must declare supersedes")
        if any(not item.strip() for item in self.forbidden_actions):
            raise BusinessBoundaryError("forbidden_actions cannot contain empty values")

    def validate_request(self, payload: dict[str, Any]) -> list[str]:
        """Return explicit request violations without guessing user intent."""
        violations: list[str] = []
        requested = payload.get("requested_action", payload.get("action"))
        if isinstance(requested, str) and requested.strip():
            action = requested.strip().lower()
            forbidden = {item.strip().lower() for item in self.forbidden_actions}
            if action in forbidden:
                violations.append(f"action {requested!r} is forbidden by boundary")
        if payload.get("_caller") == "agent" and not self.agent_callable:
            violations.append("boundary is not callable by the Agent runtime")
        return violations

    def context(self, level: str = "summary") -> dict[str, Any]:
        if level not in {"summary", "instructions", "full"}:
            raise ValueError("context level must be summary, instructions, or full")
        out: dict[str, Any] = {
            "name": self.name,
            "version": self.version,
            "scenario": self.scenario,
            "purpose": self.purpose,
            "risk_level": self.risk_level,
            "agent_callable": self.agent_callable,
            "workflow": self.workflow,
            "owner": self.owner,
            "status": self.status,
        }
        if level in {"instructions", "full"}:
            out.update(
                {
                    "allowed_tools": list(self.allowed_tools),
                    "required_steps": list(self.required_steps),
                    "human_handoff_conditions": list(self.human_handoff_conditions),
                    "forbidden_actions": list(self.forbidden_actions),
                }
            )
        if level == "full":
            out.update(
                {
                    "required_inputs": list(self.required_inputs),
                    "required_outputs": list(self.required_outputs),
                    "success_conditions": list(self.success_conditions),
                    "supersedes": self.supersedes,
                    "metadata": dict(self.metadata),
                }
            )
        return out


def validate_skill_boundary(skill: Any) -> None:
    """Check that a boundary and its SkillDef cannot drift apart."""
    boundary = getattr(skill, "boundary", None)
    if boundary is None:
        return
    boundary.validate_definition()
    mismatches = {
        "name": (boundary.name, skill.name),
        "scenario": (boundary.scenario, skill.scenario),
        "risk_level": (boundary.risk_level, skill.risk_level),
        "agent_callable": (boundary.agent_callable, skill.agent_callable),
        "workflow": (boundary.workflow, skill.workflow),
    }
    mismatches.update(
        {
            "required_inputs": (boundary.required_inputs, skill.required_inputs),
            "required_outputs": (boundary.required_outputs, skill.required_outputs),
            "allowed_tools": (boundary.allowed_tools, skill.allowed_tools),
        }
    )
    for field_name, (left, right) in mismatches.items():
        if left != right:
            raise BusinessBoundaryError(
                f"boundary {field_name} mismatch: {left!r} != {right!r}"
            )


def list_business_boundaries(skills: list[Any]) -> list[dict[str, Any]]:
    """Return full boundary contracts for documentation and audits."""
    return [skill.boundary.context("full") for skill in skills if skill.boundary]
