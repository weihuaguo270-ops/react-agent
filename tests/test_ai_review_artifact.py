import json

from scripts.ai_review.validate_artifact import ArtifactError, validate_artifact


def _artifact(**overrides):
    payload = {
        "schema_version": "ai-review/v1",
        "base_sha": "base",
        "head_sha": "head",
        "pr_number": 1,
        "risk_level": "low",
        "ci": {"status": "pass", "head_sha": "head"},
        "security": {"status": "pass", "head_sha": "head"},
        "findings": [],
        "evidence": [],
    }
    payload.update(overrides)
    return payload


def test_clean_artifact_passes():
    result = validate_artifact(_artifact(), base_sha="base", head_sha="head")
    assert result["status"] == "pass"


def test_sha_mismatch_is_blocked():
    try:
        validate_artifact(_artifact(), head_sha="new-head")
    except ArtifactError as exc:
        assert "head_sha" in str(exc)
    else:
        raise AssertionError("expected SHA mismatch to be blocked")


def test_missing_artifact_is_rejected():
    try:
        validate_artifact(None)
    except ArtifactError as exc:
        assert "JSON object" in str(exc)
    else:
        raise AssertionError("expected missing artifact to be rejected")


def test_blocked_ci_is_blocked():
    artifact = _artifact(ci={"status": "blocked", "head_sha": "head"})
    assert validate_artifact(artifact)["status"] == "blocked"


def test_blocked_security_is_blocked():
    artifact = _artifact(security={"status": "blocked", "head_sha": "head"})
    assert validate_artifact(artifact)["status"] == "blocked"


def test_open_blocker_fails():
    finding = {
        "id": "AI-003",
        "severity": "blocker",
        "confidence": "high",
        "category": "security",
        "file": "src/example.py",
        "line": 1,
        "trigger": "input",
        "expected": "safe",
        "actual": "unsafe",
        "evidence": ["pytest tests/test_example.py"],
        "recommendation": "fix",
        "status": "open",
    }
    assert validate_artifact(_artifact(findings=[finding]))["status"] == "fail"


def test_new_commit_invalidates_old_head():
    try:
        validate_artifact(_artifact(), head_sha="new-commit")
    except ArtifactError as exc:
        assert "head_sha" in str(exc)
    else:
        raise AssertionError("expected old artifact to be invalid after a new commit")


def test_open_high_finding_fails():
    finding = {
        "id": "AI-001",
        "severity": "high",
        "confidence": "high",
        "category": "correctness",
        "file": "src/example.py",
        "line": 1,
        "trigger": "input",
        "expected": "ok",
        "actual": "bad",
        "evidence": ["pytest tests/test_example.py"],
        "recommendation": "fix",
        "status": "open",
    }
    assert validate_artifact(_artifact(findings=[finding]))["status"] == "fail"


def test_low_confidence_finding_requires_review():
    finding = {
        "id": "AI-002",
        "severity": "medium",
        "confidence": "low",
        "category": "maintenance",
        "file": "README.md",
        "line": 1,
        "trigger": "review",
        "expected": "clear",
        "actual": "unclear",
        "evidence": ["manual inspection"],
        "recommendation": "review",
        "status": "open",
    }
    assert validate_artifact(_artifact(findings=[finding]))["status"] == "review_required"
