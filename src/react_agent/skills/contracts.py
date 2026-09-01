"""Contracts for business-scoped skills.

A skill narrows model/runtime behavior for one business scenario. It does not
replace deterministic workflow, policy, or side-effect enforcement.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from react_agent.skills.schema import schema_descriptor


SkillExecutor = Callable[[dict[str, Any]], dict[str, Any]]
SkillVerifier = Callable[[dict[str, Any]], dict[str, bool]]
SkillMatcher = Callable[[str, dict[str, Any]], int]


@dataclass(frozen=True)
class SkillDef:
    """A versioned business capability backed by deterministic code."""

    name: str
    scenario: str
    description: str
    executor: SkillExecutor = field(repr=False, compare=False)
    verifier: SkillVerifier = field(repr=False, compare=False)
    matcher: SkillMatcher = field(repr=False, compare=False)
    version: str = "1"
    workflow: str = ""
    risk_level: str = "read_only"
    agent_callable: bool = True
    required_inputs: tuple[str, ...] = ()
    required_outputs: tuple[str, ...] = ()
    allowed_tools: tuple[str, ...] = ()
    instructions: tuple[str, ...] = ()
    release_checks: tuple[str, ...] = ()
    input_schema: dict[str, Any] = field(default_factory=dict)
    output_schema: dict[str, Any] = field(default_factory=dict)
    status: str = "active"
    owner: str = "react-agent"
    supersedes: str = ""

    def descriptor(self) -> dict[str, Any]:
        """Return serializable discovery metadata without executable callables."""
        return {
            "name": self.name,
            "scenario": self.scenario,
            "description": self.description,
            "version": self.version,
            "workflow": self.workflow,
            "risk_level": self.risk_level,
            "agent_callable": self.agent_callable,
            "required_inputs": list(self.required_inputs),
            "required_outputs": list(self.required_outputs),
            "allowed_tools": list(self.allowed_tools),
            "instructions": list(self.instructions),
            "release_checks": list(self.release_checks),
            "status": self.status,
            "owner": self.owner,
            "supersedes": self.supersedes,
        }

    def context(self, level: str = "summary") -> dict[str, Any]:
        """Progressively disclose only the requested amount of Skill context."""
        if level not in {"summary", "instructions", "full"}:
            raise ValueError("context level must be summary, instructions, or full")
        out = self.descriptor()
        if level == "summary":
            out.pop("instructions", None)
            out.pop("release_checks", None)
            out.pop("allowed_tools", None)
            return out
        if level == "instructions":
            out.pop("release_checks", None)
            return out
        out["input_schema"] = schema_descriptor(self.input_schema)
        out["output_schema"] = schema_descriptor(self.output_schema)
        return out


@dataclass
class SkillResult:
    """Execution result separating contract validity from business outcome."""

    skill: str
    scenario: str
    workflow: str
    ok: bool
    output: dict[str, Any] = field(default_factory=dict)
    checks: dict[str, bool] = field(default_factory=dict)
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "skill": self.skill,
            "scenario": self.scenario,
            "workflow": self.workflow,
            "ok": self.ok,
            "checks": dict(self.checks),
            "error": self.error,
            "output": dict(self.output),
        }


@dataclass(frozen=True)
class SkillRoute:
    """Auditable result of deterministic business-intent routing."""

    skill: str
    score: int
    confidence: float
    candidates: tuple[tuple[str, int], ...] = ()
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "skill": self.skill,
            "score": self.score,
            "confidence": self.confidence,
            "candidates": [
                {"skill": name, "score": score}
                for name, score in self.candidates
            ],
            "reason": self.reason,
        }


@dataclass
class SkillPipelineResult:
    """Ordered composition of Skill contracts; stops on the first failure."""

    pipeline: tuple[str, ...]
    ok: bool
    results: list[SkillResult] = field(default_factory=list)
    output: dict[str, Any] = field(default_factory=dict)
    failed_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "pipeline": list(self.pipeline),
            "ok": self.ok,
            "failed_at": self.failed_at,
            "output": dict(self.output),
            "results": [item.to_dict() for item in self.results],
        }
