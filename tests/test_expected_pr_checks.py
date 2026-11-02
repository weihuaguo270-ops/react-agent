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
