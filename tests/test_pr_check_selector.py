import json
from pathlib import Path

from scripts.ci.select_pr_checks import load_registry, select_checks


def test_mapped_source_change_selects_only_deterministic_subset():
    report = select_checks(
        ["src/react_agent/cot.py"],
        base_sha="a" * 40,
        head_sha="b" * 40,
        pr_number=184,
        event_name="pull_request",
    )

    assert report["status"] == "mapped"
    assert report["selected_checks"] == ["pr-ready", "lint", "test"]
    assert report["selected_test_paths"] == ["tests/core/test_orchestrator_isolation.py", "tests/test_legacy_smoke.py"]
    assert report["unmapped_paths"] == []
    assert report["blocking"] is False
    assert report["base_sha"] == "a" * 40
    assert report["head_sha"] == "b" * 40
    assert report["pr_number"] == 184
    assert report["event_name"] == "pull_request"


def test_unmapped_path_falls_back_to_complete_deterministic_ci():
    registry = load_registry()
    report = select_checks(["new_area/file.xyz"], registry)

    assert report["status"] == "fallback"
    assert report["fallback_scope"] == "deterministic_pr_ci"
    assert report["selected_checks"] == registry["deterministic_pr_checks"]
    assert report["selected_test_paths"] == ["tests/"]
    assert report["unmapped_paths"] == ["new_area/file.xyz"]
    assert "evaluation.yml" in report["excluded_workflows"]
    assert report["blocking"] is False


def test_selector_error_preserves_changed_paths_in_blocked_fallback():
    from scripts.ci.select_pr_checks import fallback_report

    report = fallback_report("registry failed", changed_files=["new_area/file.py"])

    assert report["blocking"] is True
    assert report["changed_files"] == ["new_area/file.py"]


def test_workflow_change_includes_container_and_security_checks():
    report = select_checks([".github/workflows/test.yml"])

    assert report["status"] == "mapped"
    assert "docker-smoke" in report["selected_checks"]
    assert "security" in report["selected_checks"]


def test_registry_is_unique_and_has_expected_schema():
    path = Path("docs/specs/ci/pr-check-registry.json")
    payload = json.loads(path.read_text(encoding="utf-8"))

    assert payload["schema_version"] == "ci-pr-check-registry/v1"
    assert len(payload["rules"]) == len({rule["id"] for rule in payload["rules"]})
    assert set(payload["deterministic_pr_checks"]) >= {"pr-ready", "test", "security"}


def test_changed_test_file_runs_itself_without_full_fallback():
    report = select_checks(["tests/core/test_context_manage.py"])

    assert report["status"] == "mapped"
    assert report["selected_test_paths"] == ["tests/core/test_context_manage.py"]


def test_shared_test_configuration_falls_back_to_full_suite():
    report = select_checks(["tests/conftest.py"])

    assert report["status"] == "fallback"
    assert report["fallback_scope"] == "deterministic_pr_ci"
    assert report["selected_test_paths"] == ["tests/"]


def test_missing_or_mismatched_head_input_falls_back_blocked():
    from scripts.ci.select_pr_checks import fallback_report

    missing = fallback_report("base ref is required")
    mismatch = fallback_report("checked out head SHA mismatch")

    for report in (missing, mismatch):
        assert report["status"] == "fallback"
        assert report["selected_test_paths"] == ["tests/"]
        assert report["blocking"] is True
        assert report["selection_error"]


def test_cli_missing_base_emits_blocked_fallback(monkeypatch, capsys):
    import sys

    from scripts.ci.select_pr_checks import main

    monkeypatch.setattr(
        sys,
        "argv",
        ["select_pr_checks.py", "--changed-file", "src/react_agent/cot.py"],
    )

    assert main() == 0
    report = json.loads(capsys.readouterr().out)
    assert report["status"] == "fallback"
    assert report["blocking"] is True
    assert "base ref is required" in report["selection_error"]


def test_cli_head_sha_mismatch_emits_blocked_fallback(monkeypatch, capsys):
    import sys

    import scripts.ci.select_pr_checks as selector

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "select_pr_checks.py",
            "--base",
            "base",
            "--head",
            "head",
            "--expected-head-sha",
            "b" * 40,
            "--changed-file",
            "src/react_agent/cot.py",
        ],
    )
    monkeypatch.setattr(
        selector,
        "resolve_commit",
        lambda ref: "a" * 40 if ref == "base" else "c" * 40,
    )

    assert selector.main() == 0
    report = json.loads(capsys.readouterr().out)
    assert report["status"] == "fallback"
    assert report["blocking"] is True
    assert "head SHA mismatch" in report["selection_error"]
