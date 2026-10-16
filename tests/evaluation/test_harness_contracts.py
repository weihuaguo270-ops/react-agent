"""Shared Harness contract and policy tests."""
from __future__ import annotations

import json
import pytest


def test_tool_call_normalizes_mapping_arguments():
    from react_agent.harness import ToolCall

    call = ToolCall.from_mapping({"name": "calculator", "args": {"expression": "2+2"}})
    assert call.name == "calculator"
    assert call.arguments == '{"expression": "2+2"}'


def test_tool_call_rejects_non_object_json():
    from react_agent.harness import ToolCall

    with pytest.raises(ValueError, match="must be an object"):
        ToolCall(name="calculator", arguments="[]")


def test_tool_boundary_applies_schema_and_output_contract():
    from react_agent.harness.tool_boundary import ToolBoundary

    boundary = ToolBoundary(
        {"demo": lambda value: "x" * value},
        definitions=[
            {
                "type": "function",
                "function": {
                    "name": "demo",
                    "parameters": {
                        "type": "object",
                        "properties": {"value": {"type": "integer"}},
                        "required": ["value"],
                    },
                },
            }
        ],
    )
    assert boundary.execute("demo", {"value": 4}) == "xxxx"
    from react_agent.harness.contracts import ToolCallError

    with pytest.raises(ToolCallError) as caught:
        boundary.execute("demo", {})
    assert caught.value.error.to_dict()["error_code"] == "invalid_arguments"
    assert boundary.execute("demo", {"value": 20}, max_output_chars=5).startswith("xxxxx")


def test_tool_boundary_timeout_has_shared_error_envelope():
    import time

    from react_agent.harness.contracts import ToolCallError
    from react_agent.harness.tool_boundary import ToolBoundary

    def slow_tool():
        time.sleep(0.05)
        return "late"

    boundary = ToolBoundary({"slow": slow_tool})
    with pytest.raises(ToolCallError) as caught:
        boundary.execute("slow", {}, timeout_seconds=0.001)
    assert caught.value.error.to_dict()["error_code"] == "timeout"
    assert caught.value.error.to_dict()["stop_reason"] == "timeout"


def test_tool_spec_formally_carries_execution_and_idempotency_constraints():
    from react_agent.harness import ToolSpec

    spec = ToolSpec.from_definition(
        {
            "type": "function",
            "function": {
                "name": "write_once",
                "parameters": {"type": "object"},
                "timeout_seconds": 0.25,
                "max_output_chars": 32,
                "idempotency_level": "required",
            },
        }
    )
    assert spec.timeout_seconds == 0.25
    assert spec.max_output_chars == 32
    assert spec.idempotency_level == "required"

    from react_agent.harness.tool_boundary import ToolBoundary

    boundary = ToolBoundary(
        {"write_once": lambda: "ok"},
        definitions=[
            {
                "name": "write_once",
                "parameters": {"type": "object"},
                "idempotency_level": "required",
            }
        ],
    )
    with pytest.raises(ValueError, match="idempotency key is required"):
        boundary.execute("write_once", {})
    assert boundary.execute("write_once", {}, idempotency_key="case-1") == "ok"


def test_registry_workflow_and_evaluation_use_the_same_tool_boundary(monkeypatch):
    from react_agent.eval import execution_scorer
    from react_agent.harness.tool_boundary import execute_registered_tool
    from react_agent.workflow.engine import Step, StepKind, WorkflowDef, WorkflowRunner

    seen = []

    def demo(**kwargs):
        seen.append(dict(kwargs))
        return "ok"

    registry = {"demo": demo}
    assert execute_registered_tool("demo", {"b": 2, "a": 1}, registry) == "ok"
    monkeypatch.setattr(execution_scorer, "TOOL_REGISTRY", registry)
    assert execution_scorer.execute_tool_step("demo", {"a": 1, "b": 2}) == "ok"

    workflow = WorkflowDef(
        name="r1-boundary",
        description="shared tool boundary test",
        steps=[
            Step(
                id="call",
                kind=StepKind.TOOL,
                tool="demo",
                args={"a": 1, "b": 2},
                output_key="result",
            )
        ],
    )
    result = WorkflowRunner(workflow, registry).run()
    assert result.ok is True
    assert len(seen) == 3
    assert all(item == {"a": 1, "b": 2} for item in seen)


def test_four_execution_paths_share_the_same_error_envelope(monkeypatch):
    """The route may identify its source, but error semantics stay identical."""
    import json

    from react_agent.eval import execution_scorer
    from react_agent.mcp_client import MockMCPClient
    from react_agent.react_loop import _execute_tool_call_raw
    from react_agent.workflow.engine import Step, StepKind, WorkflowDef, WorkflowRunner

    monkeypatch.setattr(execution_scorer, "TOOL_REGISTRY", {})
    import react_agent.react_loop as react_loop

    monkeypatch.setattr(react_loop, "get_registry", lambda: {})
    monkeypatch.setattr(react_loop, "MCP_CLIENTS", [])

    react_payload = json.loads(
        _execute_tool_call_raw(
            {"function": {"name": "shared_missing", "arguments": "{}"}}
        )
    )
    workflow = WorkflowRunner(
        WorkflowDef(
            name="envelope",
            description="error envelope",
            steps=[Step(id="call", kind=StepKind.TOOL, tool="shared_missing")],
        ),
        {},
    ).run()
    workflow_payload = json.loads(workflow.steps[0].error)
    evaluation_payload = json.loads(
        execution_scorer.execute_tool_step("shared_missing", {})
    )
    mock = MockMCPClient()
    mock.connect()
    mock.discover_tools()
    try:
        mock.call_tool("shared_missing", {})
    except Exception as exc:
        mock_payload = exc.error.to_dict()
    else:
        raise AssertionError("expected mock MCP tool error")

    semantic_fields = ("error_code", "stop_reason", "retryable", "attempt", "tool_name")
    for payload in (react_payload, workflow_payload, evaluation_payload, mock_payload):
        assert set(semantic_fields) <= payload.keys()
        assert payload["error_code"] == "tool_not_found"
        assert payload["stop_reason"] == "tool_error"
        assert payload["retryable"] is False
        assert payload["attempt"] == 1
        assert payload["tool_name"] == "shared_missing"
    sources = {
        payload["source"]
        for payload in (react_payload, workflow_payload, evaluation_payload, mock_payload)
    }
    assert sources == {
        "react", "workflow", "runtime", "mcp"
    }


def test_episode_hash_is_stable_and_split_is_checked():
    from react_agent.harness import TaskEpisode

    episode = TaskEpisode("case-1", "q", ("answer",), split="held_out")
    assert episode.content_hash() == episode.content_hash()
    with pytest.raises(ValueError, match="unsupported"):
        TaskEpisode("case-2", "q", split="unknown")


def test_shared_trajectory_serializer_validates_format_b():
    from react_agent.harness import serialize_trajectory
    from react_agent.harness.schema import validate_trajectory

    trajectory = serialize_trajectory(
        session_id="run-1",
        query="q",
        steps=[{"step": 1, "observation": "ok"}],
        final_answer="done",
    )
    assert trajectory["schema_version"] == "1"
    assert validate_trajectory(trajectory) == []


def test_retry_policy_retries_only_retryable_errors():
    from react_agent.harness import RetryPolicy

    policy = RetryPolicy(max_attempts=2, base_delay=1, jitter_ratio=0)
    assert policy.should_retry("timeout", 1)
    assert not policy.should_retry("401 unauthorized", 1)
    assert policy.delay(2, random_fn=lambda: 0) == 2


def test_retry_policy_run_retries_and_returns_result():
    from react_agent.harness import RetryPolicy

    attempts = []
    sleeps = []

    def operation():
        attempts.append(1)
        if len(attempts) == 1:
            raise TimeoutError("timeout")
        return "ok"

    result = RetryPolicy(max_attempts=2, base_delay=0, jitter_ratio=0).run(
        operation, sleep_fn=sleeps.append, random_fn=lambda: 0
    )
    assert result == "ok"
    assert len(attempts) == 2
    assert sleeps == [0]


def test_idempotency_policy_binds_tool_and_payload():
    from react_agent.harness import IdempotencyPolicy

    policy = IdempotencyPolicy("required")
    policy.validate_key("episode-1")
    with pytest.raises(ValueError, match="required"):
        policy.validate_key(None)
    assert policy.payload_hash("calculator", {"expression": "2+2"}) == policy.payload_hash(
        "calculator", '{"expression":"2+2"}'
    )


def test_evaluation_episode_round_trips_shared_contract():
    import json
    from pathlib import Path

    from react_agent.harness import ArtifactRef, EvaluationEpisode, FixtureManifest

    fixture = FixtureManifest(
        fixture_id="calc",
        version="v1",
        data_sha256="0" * 64,
        dependencies={"python": "3.11"},
        setup_command=("prepare",),
        cleanup_command=("cleanup",),
    )

    episode = EvaluationEpisode(
        episode_id="case-1",
        query="2+2",
        acceptance_criteria=("answer is 4",),
        fixture_ref="fixture://calc",
        runner="http",
        batch_id="batch-1",
        trajectory={"session_id": "run-1"},
        score={"task_pass": True},
        artifacts=(ArtifactRef("trace", "document", "artifacts/trace.json"),),
        environment={"python": "3.10"},
        fixture_manifest=fixture,
    )
    payload = episode.to_dict()
    restored = EvaluationEpisode.from_mapping(payload)
    assert payload["schema_version"] == "evaluation-episode/v1"
    schema = json.loads(
        (Path(__file__).parents[2] / "schemas" / "evaluation_episode.schema.json").read_text(
            encoding="utf-8"
        )
    )
    assert schema["properties"]["schema_version"]["const"] == "evaluation-episode/v1"
    assert restored.runner == "http"
    assert restored.artifacts[0].uri == "artifacts/trace.json"
    assert restored.fixture_manifest.fixture_ref == "fixture://calc@v1"
    restored.validate_for_runner()


def test_fixture_manifest_rejects_missing_hash():
    from react_agent.harness import FixtureManifest

    with pytest.raises(ValueError, match="SHA256"):
        FixtureManifest("calc", "v1", "missing")


def test_evaluation_episode_runner_validation_fails_closed():
    from react_agent.harness import EvaluationEpisode

    episode = EvaluationEpisode(
        episode_id="case-1",
        query="q",
        runner="offline",
        trajectory={},
    )
    with pytest.raises(ValueError, match="acceptance_criteria"):
        episode.validate_for_runner()


def test_fixture_bundle_adapts_legacy_case_loader(tmp_path):
    import json

    from react_agent.eval.dataset import load_dataset_bundle
    from react_agent.harness.evaluation import episode_from_case

    dataset = tmp_path / "cases.json"
    dataset.write_text(
        json.dumps(
            [{"id": "case-1", "question": "2+2", "must_contain": ["4"]}],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    bundle = load_dataset_bundle(str(dataset))
    assert bundle.value[0].id == "case-1"
    assert bundle.manifest.data_sha256
    episode = episode_from_case(
        bundle.value[0].to_dict(),
        fixture_manifest=bundle.manifest,
        runner="offline",
        batch_id="batch-1",
    )
    assert episode.fixture_ref == bundle.manifest.fixture_ref
    assert episode.to_dict()["schema_version"] == "evaluation-episode/v1"


def test_fixture_bundle_preserves_software_dataset_metadata():
    from pathlib import Path

    from react_agent.eval.software_task_dataset import load_software_task_dataset_bundle

    path = Path(__file__).parents[2] / "eval" / "software_task_dataset_manifest.json"
    bundle = load_software_task_dataset_bundle(path)
    assert bundle.value.dataset_id
    assert bundle.manifest.version == bundle.value.version
    assert bundle.manifest.dependencies["schema"] == "software-task-dataset/v1"


def test_execution_fixture_bundle_uses_portable_manifest_metadata():
    from react_agent.eval.execution_scorer import load_execution_dataset_bundle

    bundle = load_execution_dataset_bundle()
    assert isinstance(bundle.value, list)
    assert bundle.value
    assert bundle.manifest.dependencies["format"] == "execution-case/v1"
    assert bundle.manifest.environment["source_name"] == "execution_dataset.json"
    assert "source_path" not in bundle.manifest.environment


def test_public_rag_fixture_bundle_preserves_case_container():
    from react_agent.eval.public_rag_benchmark import load_public_rag_benchmark_bundle

    bundle = load_public_rag_benchmark_bundle()
    assert isinstance(bundle.value["cases"], list)
    assert bundle.value["cases"]
    assert bundle.manifest.dependencies["format"] == "public-rag/v1"
    assert bundle.manifest.environment["source_name"] == "public_rag_benchmark_subset.json"


def test_software_task_fixture_bundle_uses_manifest_version_and_name():
    from pathlib import Path

    from react_agent.eval.software_task_dataset import load_software_task_dataset_bundle

    path = Path(__file__).parents[2] / "eval" / "software_task_dataset_manifest.json"
    bundle = load_software_task_dataset_bundle(path)
    assert bundle.manifest.environment["source_name"] == path.name
    assert bundle.manifest.environment["dataset_status"] == bundle.value.status
    assert "source_path" not in bundle.manifest.environment


def test_recorder_uses_shared_trajectory_serializer():
    from react_agent.harness.recorder import Trajectory
    from react_agent.harness.schema import assert_valid

    trajectory = Trajectory("q", model="mock")
    trajectory.add_step(1, observation="ok")
    payload = trajectory.to_dict()
    assert_valid(payload)
    assert payload["metadata"]["execution_mode"] == "react"


def test_recorder_materializes_terminal_step_for_no_tool_run():
    from react_agent.harness.recorder import Trajectory

    payload = Trajectory("q", model="mock").to_dict()
    assert len(payload["steps"]) == 1
    assert payload["steps"][0]["step"] == 1
    assert payload["steps"][0]["thought"] == "terminal_without_tool_step"


def test_contract_parser_is_the_canonical_normalize_validate_entrypoint(tmp_path):
    from react_agent.harness import parse_trajectory
    from react_agent.harness.contracts import (
        SCHEMA_VERSION,
        assert_valid,
        normalize_trajectory,
        validate_trajectory,
    )

    raw = {
        "session_id": "parser-contract",
        "query": "q",
        "final_answer": "a",
        "steps": [{"step": 1, "action": {"name": "tool", "args": {"x": 1}}}],
    }
    parsed = parse_trajectory(raw)
    assert parsed["schema_version"] == SCHEMA_VERSION
    assert parsed["steps"][0]["action"]["arguments"] == '{"x": 1}'
    assert validate_trajectory(parsed) == []
    assert_valid(parsed) == parsed
    assert normalize_trajectory(raw)["schema_version"] == SCHEMA_VERSION

    path = tmp_path / "trajectory.json"
    path.write_text(json.dumps(raw), encoding="utf-8")
    assert parse_trajectory(path)["session_id"] == "parser-contract"
    assert parse_trajectory(path.read_text(encoding="utf-8"))["session_id"] == "parser-contract"


def test_contracts_have_no_runtime_or_evaluation_dependency():
    from pathlib import Path

    contracts_root = Path(__file__).parents[2] / "src" / "react_agent" / "harness" / "contracts"
    forbidden = ("harness.evaluation", "harness.runtime", "react_agent.eval")
    for path in contracts_root.glob("*.py"):
        source = path.read_text(encoding="utf-8")
        assert not any(token in source for token in forbidden), path


def test_cross_repo_compatibility_report_is_versioned_and_explicit():
    from react_agent.harness.contracts import sibling_compatibility_report

    report = sibling_compatibility_report()
    assert report["schema_version"] == "harness-compatibility/v1"
    assert report["trajectory_schema"] == "format-b@1"
    dependencies = {item["dependency"]: item for item in report["dependencies"]}
    assert set(dependencies) == {"trace-debugger", "llm-eval-engine"}
    assert all(item["status"] in {"available", "dependency_unavailable", "version_incompatible"} for item in dependencies.values())
    assert dependencies["llm-eval-engine"]["contract"] == "ProcessRewardScorer.extra_contracts@0.3"


def test_missing_cross_repo_dependency_is_reported_explicitly():
    from react_agent.harness.contracts import check_dependency

    status = check_dependency("missing-sibling", "module_that_does_not_exist_for_harness")
    assert status.status == "dependency_unavailable"
    assert status.to_dict()["dependency"] == "missing-sibling"


def test_tool_error_contract_is_stable_across_exception_classes():
    from react_agent.harness.contracts import StopReason, ToolError, tool_error_from_exception

    timeout = ToolError.from_exception(TimeoutError("deadline"), tool_name="fetch")
    denied = ToolError.from_exception(PermissionError("blocked"), tool_name="write")
    missing = tool_error_from_exception(KeyError("unknown"), tool_name="missing")
    assert timeout.to_dict()["stop_reason"] == StopReason.TIMEOUT.value
    assert timeout.to_dict()["retryable"] is True
    assert denied.to_dict()["error_code"] == "policy_denied"
    assert denied.to_dict()["stop_reason"] == StopReason.POLICY_DENIED.value
    assert missing["error_code"] == "tool_not_found"
    assert {"error", "error_code", "stop_reason", "retryable", "source", "attempt"} <= set(missing)
