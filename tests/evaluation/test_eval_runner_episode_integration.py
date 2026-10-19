"""Test that EvalRunner generates EvaluationEpisode instances.

P3 acceptance: EvalRunner must return EvaluationEpisode for each evaluated case.
"""
from __future__ import annotations

import pytest
import tempfile
import json
from pathlib import Path


def test_eval_runner_generates_evaluation_episodes():
    """EvalRunner attaches EvaluationEpisode to report."""
    from react_agent.eval import EvalRunner

    # Create a simple test dataset
    cases_data = [
        {
            "id": "test_eval_1",
            "question": "What is 2+2?",
            "expected_answer": "4",
            "tag": "math",
            "timeout": 10,
        }
    ]

    # Write to temp file
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False, encoding='utf-8') as f:
        json.dump(cases_data, f)
        dataset_path = f.name

    try:
        # Mock the runner to avoid real execution
        def mock_runner(question, timeout=60, provider=None, max_steps=None, extra_env=None):
            return (
                "The answer is 4",
                {
                    "session_id": "test_session_1",
                    "query": question,
                    "steps": [{"step": 1, "observation": "calculated"}],
                    "final_answer": "4",
                    "model": "mock-model",
                },
                0,  # exit_code
                0.5  # duration
            )

        # Patch run_single_case
        from react_agent.eval import runner as runner_module
        original = runner_module.run_single_case
        runner_module.run_single_case = mock_runner

        try:
            # Create runner and run
            runner = EvalRunner()
            runner.load_dataset(dataset_path)
            runner.run_all(provider="mock", progress=False)

            # Check report has evaluation_episodes field
            assert "evaluation_episodes" in runner.report, "P3: report must include evaluation_episodes field"
            episodes = runner.report["evaluation_episodes"]
            assert isinstance(episodes, list), "evaluation_episodes must be a list"

            # Should have at least one episode
            assert len(episodes) > 0, "should have generated at least one episode"

            first_episode = episodes[0]
            assert "schema_version" in first_episode
            assert first_episode["schema_version"] == "evaluation-episode/v1"
            assert "episode_id" in first_episode
            assert "query" in first_episode
            assert "runner" in first_episode
            assert first_episode["runner"].startswith("eval:")
            assert "batch_id" in first_episode
            assert "trajectory" in first_episode
            assert "score" in first_episode
            assert "fixture_manifest" in first_episode

        finally:
            runner_module.run_single_case = original

    finally:
        Path(dataset_path).unlink(missing_ok=True)


def test_eval_runner_episode_can_be_deserialized():
    """EvaluationEpisode from EvalRunner can round-trip through from_mapping."""
    from react_agent.eval import EvalRunner
    from react_agent.harness import EvaluationEpisode

    cases_data = [{"id": "test_eval_2", "question": "What is 3+3?", "expected_answer": "6", "tag": "math"}]

    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False, encoding='utf-8') as f:
        json.dump(cases_data, f)
        dataset_path = f.name

    try:
        def mock_runner(question, timeout=60, provider=None, max_steps=None, extra_env=None):
            return (
                "The answer is 6",
                {"session_id": "test_session_2", "query": question, "steps": [{"step": 1, "observation": "calc"}],
                 "final_answer": "6", "model": "mock"},
                0, 0.5
            )

        from react_agent.eval import runner as runner_module
        original = runner_module.run_single_case
        runner_module.run_single_case = mock_runner

        try:
            runner = EvalRunner()
            runner.load_dataset(dataset_path)
            runner.run_all(provider="mock", progress=False)

            episodes = runner.report.get("evaluation_episodes", [])
            assert len(episodes) > 0, "should have at least one episode"

            episode_dict = episodes[0]
            episode = EvaluationEpisode.from_mapping(episode_dict)

            assert episode.episode_id
            assert episode.query
            assert episode.runner.startswith("eval:")
            assert episode.batch_id
            assert episode.fixture_manifest is not None
            assert isinstance(episode.trajectory, dict)
            assert isinstance(episode.score, dict)

        finally:
            runner_module.run_single_case = original

    finally:
        Path(dataset_path).unlink(missing_ok=True)


def test_eval_runner_episode_preserved_in_legacy_results():
    """Episode is attached to individual results for backward compatibility."""
    from react_agent.eval import EvalRunner

    cases_data = [{"id": "test_eval_3", "question": "What is 5+5?", "expected_answer": "10", "tag": "math"}]

    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False, encoding='utf-8') as f:
        json.dump(cases_data, f)
        dataset_path = f.name

    try:
        def mock_runner(question, timeout=60, provider=None, max_steps=None, extra_env=None):
            return (
                "The answer is 10",
                {"session_id": "test_session_3", "query": question, "steps": [{"step": 1, "observation": "calc"}],
                 "final_answer": "10", "model": "mock"},
                0, 0.5
            )

        from react_agent.eval import runner as runner_module
        original = runner_module.run_single_case
        runner_module.run_single_case = mock_runner

        try:
            runner = EvalRunner()
            runner.load_dataset(dataset_path)
            runner.run_all(provider="mock", progress=False)

            results = runner.report.get("results", [])
            assert len(results) > 0, "should have at least one result"

            first_result = results[0]
            if "evaluation_episode" in first_result:
                # trajectory_file field exists for backward compatibility
                assert "trajectory_file" in first_result

                result_episode = first_result["evaluation_episode"]
                report_episodes = runner.report.get("evaluation_episodes", [])

                matching = [ep for ep in report_episodes if ep["episode_id"] == result_episode["episode_id"]]
                assert len(matching) == 1

        finally:
            runner_module.run_single_case = original

    finally:
        Path(dataset_path).unlink(missing_ok=True)


def test_eval_runner_fixture_manifest_consistency():
    """All episodes in a batch share the same fixture manifest."""
    from react_agent.eval import EvalRunner

    cases_data = [
        {"id": "test_eval_4", "question": "What is 1+1?", "expected_answer": "2", "tag": "math"},
        {"id": "test_eval_5", "question": "What is 2+2?", "expected_answer": "4", "tag": "math"},
    ]

    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False, encoding='utf-8') as f:
        json.dump(cases_data, f)
        dataset_path = f.name

    try:
        def mock_runner(question, timeout=60, provider=None, max_steps=None, extra_env=None):
            answer = "2" if "1+1" in question else "4"
            session_id = "session_4" if "1+1" in question else "session_5"
            return (
                f"The answer is {answer}",
                {"session_id": session_id, "query": question, "steps": [{"step": 1, "observation": "calc"}],
                 "final_answer": answer, "model": "mock"},
                0, 0.5
            )

        from react_agent.eval import runner as runner_module
        original = runner_module.run_single_case
        runner_module.run_single_case = mock_runner

        try:
            runner = EvalRunner()
            runner.load_dataset(dataset_path)
            runner.run_all(provider="mock", progress=False)

            episodes = runner.report.get("evaluation_episodes", [])
            assert len(episodes) >= 2, "should have at least 2 episodes"

            manifests = [ep["fixture_manifest"] for ep in episodes]
            first_sha = manifests[0]["data_sha256"]

            for manifest in manifests[1:]:
                assert manifest["data_sha256"] == first_sha

            report_manifest = runner.report.get("fixture_manifest", {})
            assert report_manifest.get("data_sha256") == first_sha

        finally:
            runner_module.run_single_case = original

    finally:
        Path(dataset_path).unlink(missing_ok=True)
