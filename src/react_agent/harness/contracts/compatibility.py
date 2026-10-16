"""Versioned compatibility checks for optional cross-repository adapters."""
from __future__ import annotations

import importlib
from dataclasses import asdict, dataclass
from typing import Any

from ..schema import SCHEMA_VERSION


@dataclass(frozen=True)
class DependencyStatus:
    """Machine-readable status for one optional adapter dependency."""

    dependency: str
    status: str
    version: str = ""
    expected_version: str = ""
    contract: str = ""
    error: str = ""

    def to_dict(self) -> dict[str, str]:
        return {key: value for key, value in asdict(self).items() if value}


def check_dependency(
    dependency: str,
    module_name: str,
    *,
    expected_version: str = "",
    contract: str = "",
) -> DependencyStatus:
    """Import and version-check an optional sibling without hiding its state."""
    try:
        module = importlib.import_module(module_name)
    except (ImportError, ModuleNotFoundError) as exc:
        return DependencyStatus(
            dependency=dependency,
            status="dependency_unavailable",
            expected_version=expected_version,
            contract=contract,
            error=str(exc),
        )

    version = str(getattr(module, "__version__", "") or "")
    if expected_version and version and not version.startswith(expected_version):
        return DependencyStatus(
            dependency=dependency,
            status="version_incompatible",
            version=version,
            expected_version=expected_version,
            contract=contract,
        )
    return DependencyStatus(
        dependency=dependency,
        status="available",
        version=version,
        expected_version=expected_version,
        contract=contract,
    )


def sibling_compatibility_report() -> dict[str, Any]:
    """Return the pinned cross-repository compatibility matrix.

    The report is deliberately data-only so CI and evaluation artifacts can
    preserve dependency provenance without importing sibling internals.
    """
    statuses = [
        check_dependency(
            "trace-debugger",
            "trace_debugger",
            expected_version="0.6",
            contract=f"Format-B-reader@{SCHEMA_VERSION}",
        ),
        check_dependency(
            "llm-eval-engine",
            "eval_engine",
            expected_version="0.3",
            contract="ProcessRewardScorer.extra_contracts@0.3",
        ),
    ]
    return {
        "schema_version": "harness-compatibility/v1",
        "trajectory_schema": f"format-b@{SCHEMA_VERSION}",
        "evaluation_episode_schema": "evaluation-episode/v1",
        "dependencies": [status.to_dict() for status in statuses],
    }


__all__ = ["DependencyStatus", "check_dependency", "sibling_compatibility_report"]
