from __future__ import annotations

from react_agent.harness import (
    ReactLoopAdapter,
    StructuredOutputContract,
    StructuredOutputStatus,
    attach_structured_output_evidence,
)


SCHEMA = {
    "type": "object",
    "required": ["answer", "confidence"],
    "properties": {
        "answer": {"type": "string"},
        "confidence": {"type": "number"},
    },
}


def test_valid_json_is_parsed_without_tool_call_handling():
    result = StructuredOutputContract("answer", SCHEMA).parse(
        '{"answer":"ok","confidence":0.9}'
    )

    assert result.status is StructuredOutputStatus.PARSED
    assert result.ok is True
    assert result.business_success is True
    assert result.value == {"answer": "ok", "confidence": 0.9}
    assert result.to_trajectory_event()["type"] == "structured_output"


def test_missing_field_and_type_error_are_stable_invalid_categories():
    contract = StructuredOutputContract("answer", SCHEMA)

    missing = contract.parse('{"answer":"ok"}')
    wrong_type = contract.parse('{"answer":3,"confidence":"high"}')

    assert missing.status is StructuredOutputStatus.INVALID
    assert missing.failure_type == "schema_validation"
    assert {issue.code for issue in missing.issues} == {"missing_field"}
    assert wrong_type.status is StructuredOutputStatus.INVALID
    assert wrong_type.failure_type == "schema_validation"
    assert {issue.code for issue in wrong_type.issues} == {"type_error"}
    assert missing.business_success is False


def test_refusal_and_missing_output_do_not_become_success():
    contract = StructuredOutputContract("answer", SCHEMA)

    refused = contract.parse({"refusal": "I cannot comply"})
    missing = contract.parse(None)

    assert refused.status is StructuredOutputStatus.REFUSED
    assert refused.failure_type == "model_refusal"
    assert missing.status is StructuredOutputStatus.MISSING
    assert missing.failure_type == "missing_output"
    assert not refused.ok and not missing.ok


def test_truncated_response_is_invalid_even_when_finish_reason_is_explicit():
    contract = StructuredOutputContract("answer", SCHEMA)
    result = contract.parse(
        {"content": '{"answer":"ok"', "finish_reason": "length"}
    )

    assert result.status is StructuredOutputStatus.INVALID
    assert result.failure_type == "truncated"
    assert any(issue.code == "invalid_json" for issue in result.issues)


def test_provider_envelope_and_fenced_json_are_supported():
    contract = StructuredOutputContract("answer", SCHEMA)
    result = contract.parse(
        {"choices": [{"message": {"content": '```json\n{"answer":"ok","confidence":1}\n```'}}]}
    )

    assert result.status is StructuredOutputStatus.PARSED
    assert result.value["answer"] == "ok"


def test_repair_is_bounded_and_evidence_can_be_attached_to_trajectory():
    calls: list[int] = []

    def repair(raw: str, previous):
        calls.append(previous.attempts)
        return '{"answer":"fixed","confidence":0.5}'

    contract = StructuredOutputContract("answer", SCHEMA, max_repair_attempts=1, repair=repair)
    result = contract.parse("not json")
    trajectory = {
        "session_id": "s1",
        "query": "q",
        "steps": [{"step": 1, "observation": "q"}],
        "final_answer": "",
    }
    enriched = attach_structured_output_evidence(trajectory, result)

    assert result.status is StructuredOutputStatus.PARSED
    assert result.attempts == 2
    assert result.repair_applied is True
    assert calls == [1]
    event = enriched["metadata"]["structured_output_events"][0]
    assert event["status"] == "parsed"
    assert event["attempts"] == 2
    assert "structured_output_events" not in trajectory


def test_raw_retention_requires_redaction_and_preserves_only_redacted_value():
    contract = StructuredOutputContract(
        "answer",
        SCHEMA,
        retain_raw_response=True,
        redact_raw=lambda value: value.replace("secret", "[redacted]"),
    )
    result = contract.parse('{"answer":"secret","confidence":1}')

    assert result.raw_response_retained is True
    assert "secret" not in (result.raw_response or "")
    assert result.raw_response == '{"answer":"[redacted]","confidence":1}'
    assert result.raw_response_sha256


def test_react_adapter_maps_invalid_structured_output_to_parse_error_and_records_evidence():
    contract = StructuredOutputContract("answer", SCHEMA)
    episode = ReactLoopAdapter(loop=lambda query, **kwargs: {"answer": '{"answer":"ok"}'}).run(
        "q", structured_output_contract=contract
    )

    assert episode.stop_reason.value == "parse_error"
    assert episode.status == "failed"
    event = episode.trajectory["metadata"]["structured_output_events"][0]
    assert event["status"] == "invalid"
    assert event["failure_type"] == "schema_validation"
