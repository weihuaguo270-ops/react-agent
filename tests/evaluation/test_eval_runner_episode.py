from __future__ import annotations

import json

from react_agent.eval import EvalRunner
from react_agent.eval import runner as runner_module
from react_agent.eval.dataset import TestCase
from react_agent.eval.report import generate_report
from react_agent.harness.evaluation import (
    build_fixture_manifest_from_value,
    episode_from_case,
)


def test_run_batch_emits_episode_and_hashed_trajectory(monkeypatch):
    monkeypatch.setattr(
        runner_module,
        "run_single_case",
        lambda *_args, **_kwargs: (
            "4",
            {
                "session_id": "run-1",
                "query": "2+2",
                "steps": [],
                "final_answer": "4",
            },
            0,
            0.1,
        ),
    )
    case = TestCase({"id": "case-1", "question": "2+2", "must_contain": ["4"]})

    result = runner_module.run_batch([case])[0]

    episode = result["evaluation_episode"]
    assert episode["schema_version"] == "evaluation-episode/v1"
    assert episode["episode_id"] == "case-1#run-1"
    assert episode["artifacts"][0]["sha256"]
    assert episode["batch_id"].startswith("eval-batch-")


def test_eval_runner_load_dataset_retains_real_fixture_manifest(tmp_path):
    dataset = tmp_path / "cases.json"
    dataset.write_text(
        json.dumps([{"id": "case-1", "question": "2+2", "must_contain": ["4"]}]),
        encoding="utf-8",
    )

    runner = EvalRunner()
    runner.load_dataset(str(dataset))

    assert runner.cases[0].id == "case-1"
    assert runner.fixture_manifest is not None
    assert runner.fixture_manifest.environment["source_name"] == dataset.name


def test_run_batch_fails_closed_when_acceptance_is_missing(monkeypatch):
    monkeypatch.setattr(
        runner_module,
        "run_single_case",
        lambda *_args, **_kwargs: ("answer", None, 0, 0.1),
    )

    result = runner_module.run_batch(
        [TestCase({"id": "case-1", "question": "unconstrained"})]
    )[0]

    assert "evaluation_episode" not in result
    assert "acceptance_criteria" in result["evaluation_episode_error"]


def test_report_preserves_episode_and_writes_final_score():
    case = TestCase({"id": "case-1", "question": "2+2", "must_contain": ["4"]})
    fixture = build_fixture_manifest_from_value(
        [case.to_dict()], fixture_id="eval:test"
    )
    episode = episode_from_case(
        case.to_dict(),
        fixture_manifest=fixture,
        runner="test",
        batch_id="batch-1",
        trajectory={"session_id": "run-1"},
    )
    raw = {
        "case_id": "case-1",
        "question": "2+2",
        "stdout": "4",
        "trajectory": {
            "session_id": "run-1",
            "steps": [],
            "final_answer": "4",
        },
        "exit_code": 0,
        "duration_seconds": 0.1,
        "evaluation_episode": episode.to_dict(),
        "evaluation_episode_error": "legacy warning",
    }

    report = generate_report(
        [raw],
        [case],
        provider="test",
        fixture_manifest=fixture,
        batch_id="batch-1",
    )
    entry = report["results"][0]
    assert entry["evaluation_episode"]["score"] == entry["score"]
    assert entry["evaluation_episode_error"] == "legacy warning"
    assert entry["fixture_manifest"]["data_sha256"] == fixture.data_sha256
    assert entry["batch_id"] == "batch-1"
