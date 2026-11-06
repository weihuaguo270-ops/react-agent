from __future__ import annotations

from datetime import date

from scripts.ci.aggregate_shadow_observation import aggregate


def _pair(number: int, day: str, change_class: str, *, head: str | None = None, improvement: float | None = None):
    head = head or f"{number:040x}"
    changed = [f"src/react_agent/apps/{change_class}/{number}.py"]
    selector = {
        "schema_version": "ci-pr-check-scope/v1",
        "generated_at": f"{day}T12:00:00+00:00",
        "base_sha": "a" * 40,
        "head_sha": head,
        "pr_number": number,
        "changed_files": changed,
        "status": "mapped",
        "selected_checks": ["pr-ready", "lint", "test"],
        "unmapped_paths": [],
    }
    if improvement is not None:
        selector["runtime_improvement"] = improvement
    expected = {
        "schema_version": "ci-expected-pr-checks/v1",
        "generated_at": f"{day}T12:00:01+00:00",
        "base_sha": "a" * 40,
        "head_sha": head,
        "pr_number": number,
        "changed_files": changed,
        "expected_checks": ["pr-ready", "lint", "test"],
        "change_class": change_class,
    }
    return selector, expected


def _write_pair(tmp_path, number, selector, expected):
    selector_path = tmp_path / f"selector-{number}.json"
    expected_path = tmp_path / f"expected-{number}.json"
    selector_path.write_text(__import__("json").dumps(selector), encoding="utf-8")
    expected_path.write_text(__import__("json").dumps(expected), encoding="utf-8")
    return selector_path, expected_path


def test_observation_passes_only_when_all_window_requirements_are_met(tmp_path):
    selectors = []
    expected = []
    for number, change_class in enumerate(("python", "docs", "config") * 4, start=1):
        selector, label = _pair(
            number,
            f"2026-11-{number:02d}",
            change_class,
            improvement=0.25,
        )
        selector_path, expected_path = _write_pair(tmp_path, number, selector, label)
        selectors.append(selector_path)
        expected.append(expected_path)

    report = aggregate(selectors, expected, today=date(2026, 11, 20))

    assert report["conclusion"] == "pass"
    assert report["metrics"]["subset_gate_eligible"] is True
    assert report["unique_head_sha_count"] == 12
    assert report["metrics"]["comparable_runtime_count"] == 12


def test_mismatched_expected_artifact_is_blocked(tmp_path):
    selector, expected = _pair(1, "2026-11-01", "python")
    expected["head_sha"] = "b" * 40
    selector_path, expected_path = _write_pair(tmp_path, 1, selector, expected)

    report = aggregate([selector_path], [expected_path], today=date(2026, 11, 20))

    assert report["conclusion"] == "blocked"
    assert report["invalid_samples"]
    assert report["metrics"]["criteria"]["no_invalid_samples"] is False


def test_duplicate_head_is_excluded_as_rerun(tmp_path):
    selector_a, expected_a = _pair(1, "2026-11-01", "python", head="c" * 40)
    selector_b, expected_b = _pair(2, "2026-11-02", "docs", head="c" * 40)
    selector_path_a, expected_path_a = _write_pair(tmp_path, 1, selector_a, expected_a)
    selector_path_b, expected_path_b = _write_pair(tmp_path, 2, selector_b, expected_b)

    report = aggregate(
        [selector_path_a, selector_path_b],
        [expected_path_a, expected_path_b],
        today=date(2026, 11, 20),
    )

    assert report["conclusion"] == "blocked"
    assert report["invalid_samples"] == []
    assert any("rerun" in item["reason"] for item in report["excluded_samples"])


def test_missing_expected_check_is_never_eligible(tmp_path):
    selector, expected = _pair(1, "2026-11-01", "python")
    selector["selected_checks"] = ["pr-ready"]
    selector_path, expected_path = _write_pair(tmp_path, 1, selector, expected)

    report = aggregate([selector_path], [expected_path], today=date(2026, 11, 20))

    assert report["conclusion"] == "blocked"
    assert report["metrics"]["missing_expected_checks"] == ["lint", "test"]
