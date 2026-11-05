from __future__ import annotations

from scripts.ci.r9_runtime_probe import build_report


def _event(*, fork: bool) -> dict:
    head_repo = "external/react-agent" if fork else "weihuaguo270-ops/react-agent"
    return {
        "repository": {"full_name": "weihuaguo270-ops/react-agent"},
        "pull_request": {
            "base": {
                "sha": "b" * 40,
                "repo": {"full_name": "weihuaguo270-ops/react-agent"},
            },
            "head": {
                "sha": "a" * 40,
                "repo": {"full_name": head_repo},
            },
        },
    }


def test_probe_passes_only_for_external_fork_and_binds_both_shas() -> None:
    report = build_report(_event(fork=True), run_id="123")

    assert report["status"] == "passed"
    assert report["is_fork"] is True
    assert report["head_sha"] == "a" * 40
    assert report["base_sha"] == "b" * 40
    assert report["permission_contract"]["secrets"] == "not_requested"


def test_same_repository_run_does_not_claim_fork_isolation() -> None:
    report = build_report(_event(fork=False))

    assert report["status"] == "blocked"
    assert report["is_fork"] is False
    assert report["secret_observation"]["status"] == "not_observed"


def test_non_pull_request_payload_is_blocked() -> None:
    report = build_report({"repository": {"full_name": "x"}})

    assert report["status"] == "blocked"
