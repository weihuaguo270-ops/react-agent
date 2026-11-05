from scripts.ci.expected_pr_checks import expected_checks


def test_docs_only_has_minimum_docs_checks():
    report = expected_checks(["README.md", "docs/guide.md"])
    assert report["checks"] == ["pr-ready", "docs-eval"]


def test_docs_troubleshoot_corpus_change_requires_tests():
    report = expected_checks(["src/react_agent/apps/docs_troubleshoot/git_docs_corpus_baseline.json"])
    assert report["checks"] == ["pr-ready", "docs-eval"]


def test_workflow_change_is_full_deterministic_suite():
    report = expected_checks([".github/workflows/test.yml"])
    assert report["checks"] == [
        "pr-ready", "lint", "test", "test-windows", "typecheck", "security", "docker-smoke", "docs-eval"
    ]


def test_mixed_docs_and_corpus_baseline_uses_union_not_full_fallback():
    report = expected_checks(["docs/guide.md", "src/react_agent/apps/docs_troubleshoot/git_docs_corpus_baseline.json"])
    assert report["checks"] == ["pr-ready", "docs-eval"]


def test_unclassified_path_requires_complete_deterministic_suite():
    report = expected_checks(["new-root-format.data"])
    assert report["checks"] == [
        "pr-ready", "lint", "test", "test-windows", "typecheck", "security", "docker-smoke", "docs-eval"
    ]


def test_evaluation_evidence_does_not_pull_in_runtime_ci():
    report = expected_checks(["eval/cross_repo_evidence/sample/manifest.json"])
    assert report["checks"] == ["pr-ready"]
    assert report["class"] == "evaluation_evidence"


def test_real_llm_source_remains_evidence_only():
    report = expected_checks(["tests/test_real_llm.py"])
    assert report["checks"] == ["pr-ready"]
    assert report["class"] == "real_llm_evidence"


def test_evaluation_dockerfile_keeps_container_security_checks():
    report = expected_checks(["eval/cross_repo_evidence/sample/Dockerfile"])
    assert report["checks"] == ["pr-ready", "security", "docker-smoke"]


def test_examples_readme_uses_project_metadata_scope():
    report = expected_checks(["examples/README.md"])
    assert report["checks"] == ["pr-ready"]
    assert report["class"] == "project_metadata"


def test_historical_experiment_and_example_paths_are_evidence_only():
    for path in (
        "experiments/langgraph/graph/agent.py",
        "examples/fixtures/software_tasks/tool_timeout.json",
        "examples/eval/run_failure_regression_pipeline.py",
    ):
        report = expected_checks([path])
        assert report["checks"] == ["pr-ready"]
        assert report["class"] == "evaluation_evidence"
