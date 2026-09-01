import json

from react_agent.eval.business_pilot import evaluate_pilot, load_pilot_dataset, redact_payload


def test_redact_payload_masks_credentials_and_email_without_mutating_input():
    payload = {"email": "alice@example.com", "api_key": "abc", "message": "token=xyz"}
    scrubbed = redact_payload(payload)
    assert payload["api_key"] == "abc"
    assert scrubbed["api_key"] == "<REDACTED>"
    assert "<REDACTED_EMAIL>" in scrubbed["email"]
    assert "<REDACTED>" in scrubbed["message"]


def test_pilot_requires_review_and_final_state_for_pass(tmp_path):
    path = tmp_path / "pilot.json"
    path.write_text(
        json.dumps(
            {
                "project": "demo",
                "baseline_version": "v1",
                "candidate_version": "v2",
                "tasks": [
                    {
                        "task_id": "t1",
                        "split": "held_out",
                        "redaction": {"applied": True},
                        "baseline": {"passed": False},
                        "candidate": {"passed": True},
                        "human_review": {"decision": "accepted"},
                        "final_status": "resolved",
                        "evidence": {"source_ref": "ticket://t1"},
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    report = evaluate_pilot(load_pilot_dataset(path))
    assert report["decision"] == "pass"
    assert report["evidence_status"] == "complete"
    assert report["metrics"]["candidate"]["task_success_rate"] == 1.0


def test_pilot_holds_pending_review(tmp_path):
    path = tmp_path / "pilot.json"
    path.write_text(
        json.dumps(
            {
                "tasks": [
                    {
                        "task_id": "t1",
                        "redaction": {"applied": True},
                        "baseline": {"passed": True},
                        "candidate": {"passed": True},
                        "human_review": {"decision": "pending"},
                        "final_status": "resolved",
                        "evidence": {"source_ref": "ticket://t1"},
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    report = evaluate_pilot(load_pilot_dataset(path))
    assert report["decision"] == "hold"
    assert report["review"]["counts"]["pending"] == 1
    assert "human_review_incomplete" in {item["issue"] for item in report["data_quality"]["issues"]}


def test_pilot_holds_candidate_regression(tmp_path):
    path = tmp_path / "pilot.json"
    path.write_text(
        json.dumps(
            {
                "tasks": [
                    {
                        "task_id": "t1",
                        "redaction": {"applied": True},
                        "baseline": {"passed": True},
                        "candidate": {"passed": False},
                        "human_review": {"decision": "accepted"},
                        "final_status": "resolved",
                        "evidence": {"source_ref": "ticket://t1"},
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    report = evaluate_pilot(load_pilot_dataset(path))
    assert report["decision"] == "hold"
    assert report["comparison"]["hard_metric_regressions"] == ["task_success_rate"]


def test_pilot_holds_missing_business_evidence():
    report = evaluate_pilot(
        {
            "tasks": [
                {
                    "task_id": "t1",
                    "split": "unknown",
                    "baseline": {"passed": True},
                    "candidate": {"passed": True},
                    "human_review": {"decision": "accepted"},
                    "final_status": "resolved",
                    "evidence": {},
                    "redaction": {"applied": False},
                }
            ]
        }
    )
    issues = {item["issue"] for item in report["data_quality"]["issues"]}
    assert report["decision"] == "hold"
    assert {"missing_or_invalid_split", "missing_source_ref", "redaction_not_confirmed"} <= issues


def test_expense_source_runs_existing_business_agent():
    from examples.eval.run_business_pilot import _load_expense_pilot

    dataset = _load_expense_pilot()
    report = evaluate_pilot(dataset)
    assert dataset["evidence_level"] == "controlled_fixture"
    assert dataset["baseline_provenance"]["mode"] == "fault_injection"
    assert dataset["baseline_provenance"]["expected_scope"] == "all_tasks_fail"
    assert report["decision"] == "pass"
    assert report["baseline_provenance"]["profile"] == "no_action"
    assert report["metrics"]["baseline"]["task_success_rate"] == 0.0
    assert report["metrics"]["candidate"]["task_success_rate"] == 1.0


def test_connector_redaction_requires_human_verification():
    report = evaluate_pilot(
        {
            "tasks": [
                {
                    "task_id": "t1",
                    "split": "dev",
                    "redaction": {"applied": True, "human_verified": False},
                    "baseline": {"passed": True},
                    "candidate": {"passed": True},
                    "human_review": {"decision": "accepted"},
                    "final_status": "resolved",
                    "evidence": {"source_ref": "jira://t1"},
                }
            ]
        }
    )
    assert report["decision"] == "hold"
    assert "redaction_human_review_incomplete" in {
        item["issue"] for item in report["data_quality"]["issues"]
    }
