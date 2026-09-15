from react_agent.eval.software_task_review import review_candidate


def test_candidate_requires_reproducible_review_fields():
    result = review_candidate({"issue_url": "https://github.com/a/b/issues/1", "base_commit": "1234567"})
    assert result["eligible"] is False
    assert "hidden_test" in result["missing"]


def test_complete_candidate_is_eligible():
    record = {field: "set" for field in (
        "issue_url", "base_commit", "public_test", "hidden_test",
        "allowed_paths", "license_confirmation", "runtime_image", "repository_cluster",
    )}
    record.update(issue_url="https://github.com/a/b/issues/1", base_commit="1234567")
    assert review_candidate(record) == {"eligible": True, "missing": []}


def test_empty_arrays_and_invalid_issue_are_rejected():
    record = {field: "set" for field in (
        "issue_url", "base_commit", "public_test", "hidden_test",
        "allowed_paths", "license_confirmation", "runtime_image", "repository_cluster",
    )}
    record.update(issue_url="https://example.com/issues/1", public_test=[], hidden_test=[])
    result = review_candidate(record)
    assert result["eligible"] is False
    assert "public_test" in result["missing"]
    assert "hidden_test" in result["missing"]
    assert "valid_issue_url" in result["missing"]
