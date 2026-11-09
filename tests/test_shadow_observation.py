from __future__ import annotations

from datetime import date
from scripts.ci.collect_shadow_observation import runtime_observation
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


def test_runtime_observation_pairs_successful_jobs_from_one_attempt():
    selector = {
        "selected_checks": ["pr-ready", "lint"],
        "runtime_improvement": None,
    }
    jobs = [
        {
            "name": "PR ready audit",
            "started_at": "2026-11-06T10:00:00Z",
            "completed_at": "2026-11-06T10:02:00Z",
            "conclusion": "success",
        },
        {
            "name": "lint",
            "started_at": "2026-11-06T10:00:00Z",
            "completed_at": "2026-11-06T10:01:00Z",
            "conclusion": "success",
        },
        {
            "name": "test (3.11)",
            "started_at": "2026-11-06T10:00:00Z",
            "completed_at": "2026-11-06T10:05:00Z",
            "conclusion": "success",
        },
        {
            "name": "test-windows (3.11)",
            "started_at": "2026-11-06T10:00:00Z",
            "completed_at": "2026-11-06T10:06:00Z",
            "conclusion": "success",
        },
        {
            "name": "typecheck",
            "started_at": "2026-11-06T10:00:00Z",
            "completed_at": "2026-11-06T10:02:30Z",
            "conclusion": "success",
        },
        {
            "name": "security",
            "started_at": "2026-11-06T10:00:00Z",
            "completed_at": "2026-11-06T10:03:00Z",
            "conclusion": "success",
        },
        {
            "name": "docker-smoke",
            "started_at": "2026-11-06T10:00:00Z",
            "completed_at": "2026-11-06T10:04:00Z",
            "conclusion": "success",
        },
        {"name": "unrelated", "conclusion": "failure"},
    ]

    result = runtime_observation(
        selector,
        jobs,
        {"id": 42, "run_attempt": 1},
        expected_checks={"pr-ready", "lint", "test"},
    )

    assert result["runtime_comparable"] is True
    assert result["runtime_full_seconds"] == 1410.0
    assert result["runtime_selected_seconds"] == 180.0
    assert result["runtime_improvement"] == 0.8723


def test_runtime_comparison_uses_full_matrix_not_expected_policy():
    selector = {"selected_checks": ["pr-ready", "lint", "security"]}
    jobs = [
        {
            "name": name,
            "started_at": "2026-11-06T10:00:00Z",
            "completed_at": f"2026-11-06T10:{minutes:02d}:00Z",
            "conclusion": "success",
        }
        for name, minutes in (
            ("PR ready audit", 2),
            ("lint", 1),
            ("test (3.11)", 5),
            ("test-windows (3.11)", 6),
            ("typecheck", 3),
            ("security", 4),
            ("docker-smoke", 7),
        )
    ]

    result = runtime_observation(
        selector,
        jobs,
        {"id": 45, "run_attempt": 1},
        expected_checks={"pr-ready", "lint"},
    )

    assert result["runtime_comparable"] is True
    assert result["runtime_full_seconds"] == 1680.0
    assert result["runtime_selected_seconds"] == 420.0
    assert result["runtime_improvement"] == 0.75


def test_runtime_observation_blocks_failed_or_incomplete_jobs():
    selector = {"selected_checks": ["lint"]}
    jobs = [
        {
            "name": "lint",
            "started_at": "2026-11-06T10:00:00Z",
            "completed_at": "2026-11-06T10:01:00Z",
            "conclusion": "failure",
        },
        {
            "name": "test (3.10)",
            "started_at": "2026-11-06T10:00:00Z",
            "completed_at": None,
            "conclusion": "success",
        },
    ]

    result = runtime_observation(
        selector,
        jobs,
        {"id": 43, "run_attempt": 1},
        expected_checks={"lint", "test"},
    )

    assert result["runtime_comparable"] is False
    assert result["runtime_source"] is None
    assert result["runtime_selected_seconds"] is None
    assert result["runtime_incomplete"] is True


def test_runtime_observation_compares_against_full_matrix_when_policy_is_smaller():
    selector = {"selected_checks": ["docs-eval", "pr-ready", "lint", "test"]}
    jobs = [
        {
            "name": name,
            "started_at": "2026-11-06T10:00:00Z",
            "completed_at": "2026-11-06T10:01:00Z",
            "conclusion": "success",
        }
        for name in (
            "PR ready audit",
            "lint",
            "test (3.10)",
            "test-windows (3.10)",
            "typecheck",
            "security",
            "docker-smoke",
        )
    ]

    result = runtime_observation(
        selector,
        jobs,
        {"id": 45, "run_attempt": 1},
        expected_checks={"pr-ready"},
    )

    assert result["runtime_comparable"] is True
    assert result["runtime_missing_checks"] == []

def test_runtime_observation_rejects_missing_expected_check():
    selector = {"selected_checks": ["lint"]}
    jobs = [
        {
            "name": "lint",
            "started_at": "2026-11-06T10:00:00Z",
            "completed_at": "2026-11-06T10:01:00Z",
            "conclusion": "success",
        }
    ]

    result = runtime_observation(
        selector,
        jobs,
        {"id": 44, "run_attempt": 1},
        expected_checks={"lint", "test"},
    )

    assert result["runtime_comparable"] is False
    assert result["runtime_missing_checks"] == ["test"]


def test_collect_excludes_artifacts_bound_to_another_head(tmp_path, monkeypatch):
    from scripts.ci import collect_shadow_observation as collector
    from contextlib import contextmanager

    runs = {
        "workflow_runs": [
            {"id": 1, "head_sha": "a" * 40, "created_at": "2026-11-06T10:00:00Z", "event": "pull_request"},
        ]
    }
    selector, expected = _pair(7, "2026-11-06", "python", head="b" * 40)
    selector_path = tmp_path / "selector.json"
    expected_path = tmp_path / "expected.json"
    selector_path.write_text(__import__("json").dumps(selector), encoding="utf-8")
    expected_path.write_text(__import__("json").dumps(expected), encoding="utf-8")

    monkeypatch.setattr(
        collector,
        "gh_json",
        lambda endpoint: runs if endpoint.endswith("/runs?event=pull_request&per_page=100") else {"jobs": []},
    )

    def fake_download(repo, run_id, destination):
        return selector_path, expected_path

    monkeypatch.setattr(collector, "download_artifact", fake_download)

    @contextmanager
    def local_tempdir(*args, **kwargs):
        scratch = tmp_path / "downloads"
        scratch.mkdir()
        yield str(scratch)

    monkeypatch.setattr(collector.tempfile, "TemporaryDirectory", local_tempdir)

    report = collector.collect("owner/repo", "test.yml", tmp_path / "report.json")
    assert report["sample_count"] == 0
    assert any("same head SHA" in item["reason"] for item in report["excluded_runs"])


def test_collect_records_workflow_provenance(tmp_path, monkeypatch):
    from scripts.ci import collect_shadow_observation as collector

    monkeypatch.setattr(collector, "gh_json", lambda endpoint: {"workflow_runs": []})
    monkeypatch.setenv("GITHUB_RUN_ID", "42494250302")
    monkeypatch.setenv("GITHUB_REPOSITORY", "owner/repo")
    monkeypatch.setenv("GITHUB_SERVER_URL", "https://github.example")
    monkeypatch.setenv("GITHUB_SHA", "A" * 40)

    report = collector.collect("fallback/repo", "test.yml", tmp_path / "report.json")

    assert report["repository"] == "owner/repo"
    assert report["run_id"] == 42494250302
    assert report["run_url"] == "https://github.example/owner/repo/actions/runs/42494250302"
    assert report["collector_head_sha"] == "a" * 40


def test_collect_can_use_older_attempt_when_newest_artifact_is_missing(tmp_path, monkeypatch):
    from scripts.ci import collect_shadow_observation as collector
    from contextlib import contextmanager

    runs = {
        "workflow_runs": [
            {"id": 2, "head_sha": "a" * 40, "created_at": "2026-11-06T11:00:00Z", "event": "pull_request"},
            {"id": 1, "head_sha": "a" * 40, "created_at": "2026-11-06T10:00:00Z", "event": "pull_request"},
        ]
    }
    selector, expected = _pair(7, "2026-11-06", "python")
    selector["head_sha"] = "a" * 40
    expected["head_sha"] = "a" * 40
    selector_path = tmp_path / "selector.json"
    expected_path = tmp_path / "expected.json"
    selector_path.write_text(__import__("json").dumps(selector), encoding="utf-8")
    expected_path.write_text(__import__("json").dumps(expected), encoding="utf-8")

    monkeypatch.setattr(collector, "gh_json", lambda endpoint: runs if endpoint.endswith("/runs?event=pull_request&per_page=100") else {"jobs": []})

    def fake_download(repo, run_id, destination):
        if run_id == 2:
            raise ValueError("scope artifact is missing selector or expected-check JSON")
        destination.mkdir(parents=True, exist_ok=True)
        return selector_path, expected_path

    monkeypatch.setattr(collector, "download_artifact", fake_download)

    @contextmanager
    def local_tempdir(*args, **kwargs):
        scratch = tmp_path / "downloads"
        scratch.mkdir()
        yield str(scratch)

    monkeypatch.setattr(collector.tempfile, "TemporaryDirectory", local_tempdir)

    report = collector.collect("owner/repo", "test.yml", tmp_path / "report.json")
    assert report["sample_count"] == 1
    assert any(item["run_id"] == 2 for item in report["excluded_runs"])
