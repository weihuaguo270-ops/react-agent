from __future__ import annotations

import copy

from scripts.ci.registry_v2 import load_registry, select, validate_registry


def test_checked_in_registry_is_semantically_valid() -> None:
    assert validate_registry() == []


def test_duplicate_rule_ids_are_rejected() -> None:
    registry = load_registry()
    direction = registry["directions"]["ci"]
    direction["rules"].append(copy.deepcopy(direction["rules"][0]))
    assert any("duplicate or missing rule id" in error for error in validate_registry(registry))


def test_unknown_changed_path_fails_closed_with_safety_gate() -> None:
    result = select(["new-unmapped-area/file.xyz"])
    assert result["status"] == "blocked"
    assert result["unmapped_paths"] == ["new-unmapped-area/file.xyz"]
    assert result["safety_gate_rule_id"] == "ci-pr-readiness"


def test_ci_spec_change_selects_pr_readiness() -> None:
    result = select(["docs/specs/ci/spec.md"])
    assert result["status"] == "pass"
    assert "ci-pr-readiness" in result["selected_rules"]


def test_archive_is_excluded_from_rules() -> None:
    result = select(["docs/specs/ci/evidence/archive/2026-10-22/phase0-baseline.md"])
    assert result["status"] == "blocked"


def test_network_allowlist_without_hosts_is_rejected() -> None:
    registry = load_registry()
    gate = registry["directions"]["ci"]["rules"][0]["gate"]
    gate["network"] = "allowlist"
    assert any("needs allowed_domains" in error for error in validate_registry(registry))
