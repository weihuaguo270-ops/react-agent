"""Provider-independent structured model output contract.

This module deliberately operates on model content and response envelopes only.
Tool-call parsing remains in the runtime/tool boundary so a malformed final
answer cannot be mistaken for a successful tool invocation.
"""
from __future__ import annotations

import hashlib
import inspect
import json
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, Mapping, Sequence


STRUCTURED_OUTPUT_CONTRACT_VERSION = "structured-output/v1"


class StructuredOutputStatus(str, Enum):
    """Stable parse outcomes consumed by runtime and evaluation code."""

    PARSED = "parsed"
    INVALID = "invalid"
    MISSING = "missing"
    REFUSED = "refused"


@dataclass(frozen=True)
class ValidationIssue:
    """One deterministic schema or JSON parsing issue."""

    code: str
    message: str
    path: str = "$"

    def to_dict(self) -> dict[str, str]:
        return {"code": self.code, "path": self.path, "message": self.message}


@dataclass(frozen=True)
class StructuredOutputResult:
    """Parse result that cannot report an invalid output as business success."""

    contract_name: str
    contract_version: str
    status: StructuredOutputStatus
    value: Any = None
    issues: tuple[ValidationIssue, ...] = ()
    failure_type: str | None = None
    attempts: int = 1
    repair_applied: bool = False
    raw_response_retained: bool = False
    raw_response: str | None = None
    raw_response_sha256: str | None = None

    @property
    def ok(self) -> bool:
        """Whether the value passed parsing and schema validation."""
        return self.status is StructuredOutputStatus.PARSED

    @property
    def success(self) -> bool:
        """Alias used by callers that gate business completion."""
        return self.ok

    @property
    def business_success(self) -> bool:
        """Explicitly prevent invalid/refused output from being a success."""
        return self.ok

    @property
    def parse_status(self) -> str:
        """String form for JSON-facing callers."""
        return self.status.value

    @property
    def classification(self) -> str:
        """Stable failure classification, or ``parsed`` on success."""
        return self.failure_type or self.status.value

    @property
    def error_messages(self) -> tuple[str, ...]:
        return tuple(issue.message for issue in self.issues)

    def evidence(self) -> dict[str, Any]:
        """Return safe, trajectory-friendly evidence without raw content by default."""
        payload: dict[str, Any] = {
            "contract_name": self.contract_name,
            "contract_version": self.contract_version,
            "status": self.status.value,
            "attempts": self.attempts,
            "repair_applied": self.repair_applied,
            "raw_response_retained": self.raw_response_retained,
            "issues": [issue.to_dict() for issue in self.issues],
        }
        if self.failure_type:
            payload["failure_type"] = self.failure_type
        if self.raw_response_sha256:
            payload["raw_response_sha256"] = self.raw_response_sha256
        if self.raw_response_retained and self.raw_response is not None:
            payload["raw_response"] = self.raw_response
        return payload

    def to_dict(self) -> dict[str, Any]:
        payload = self.evidence()
        if self.ok:
            payload["value"] = self.value
        return payload

    def to_trajectory_event(self) -> dict[str, Any]:
        """Represent this result as a Format B-compatible evidence event."""
        return {"type": "structured_output", **self.evidence()}


class StructuredOutputContract:
    """Parse and validate provider responses against one named JSON contract.

    ``schema`` may be a JSON Schema-like mapping, a callable returning no
    issues/``True``/an issue sequence, or an object exposing ``validate``. A
    repair callback receives ``(raw_text, previous_result)`` and may return a
    replacement response. It is intentionally opt-in: automatic repair is
    bounded and never turns an unsuccessful parse into success without a
    subsequent valid parse.
    """

    def __init__(
        self,
        contract_name: str | None = None,
        schema: Mapping[str, Any] | Callable[[Any], Any] | Any = None,
        *,
        name: str | None = None,
        contract_version: str = STRUCTURED_OUTPUT_CONTRACT_VERSION,
        max_repair_attempts: int = 0,
        repair: Callable[..., str | bytes | Mapping[str, Any] | None] | None = None,
        retain_raw_response: bool = False,
        redact_raw: Callable[[str], str] | None = None,
    ) -> None:
        resolved_name = str(contract_name or name or "").strip()
        if not resolved_name:
            raise ValueError("structured output contract_name must not be empty")
        if not str(contract_version).strip():
            raise ValueError("structured output contract_version must not be empty")
        if max_repair_attempts < 0:
            raise ValueError("max_repair_attempts must be non-negative")
        if retain_raw_response and redact_raw is None:
            # Retention is explicit; callers that retain sensitive responses
            # must provide a redaction boundary rather than silently leaking it.
            raise ValueError("redact_raw is required when retaining raw responses")
        self.contract_name = resolved_name
        self.contract_version = contract_version
        self.schema = schema
        self.max_repair_attempts = max_repair_attempts
        self.repair = repair
        self.retain_raw_response = retain_raw_response
        self.redact_raw = redact_raw

    def parse(
        self,
        response: Any,
        *,
        repair: Callable[..., str | bytes | Mapping[str, Any] | None] | None = None,
        max_repair_attempts: int | None = None,
        refused: bool | str | None = None,
        truncated: bool | None = None,
        retain_raw_response: bool | None = None,
    ) -> StructuredOutputResult:
        """Parse one response, optionally applying bounded repair attempts."""
        limit = self.max_repair_attempts if max_repair_attempts is None else max_repair_attempts
        if limit < 0:
            raise ValueError("max_repair_attempts must be non-negative")
        repair_fn = repair or self.repair
        raw_text = _response_text(response)
        raw_for_hash = raw_text or _stable_json(response)
        retained = self.retain_raw_response if retain_raw_response is None else retain_raw_response
        if retained and self.redact_raw is None:
            raise ValueError("redact_raw is required when retaining raw responses")

        explicit_refusal = bool(refused) or _response_refusal(response)
        explicit_truncation = bool(truncated) if truncated is not None else _response_truncated(response)
        if explicit_refusal:
            return self._result(
                StructuredOutputStatus.REFUSED,
                attempts=1,
                failure_type="model_refusal",
                raw_text=raw_for_hash,
                retained=retained,
            )
        if raw_text is None or not raw_text.strip():
            return self._result(
                StructuredOutputStatus.MISSING,
                attempts=1,
                failure_type="missing_output",
                raw_text=raw_for_hash,
                retained=retained,
            )

        current: Any = response
        last = self._parse_once(current, truncated=explicit_truncation, retained=retained)
        attempts = 1
        while not last.ok and attempts <= limit and repair_fn is not None:
            replacement = _invoke_repair(repair_fn, raw_text or "", last)
            attempts += 1
            if replacement is None:
                break
            current = replacement
            raw_text = _response_text(current)
            last = self._parse_once(
                current,
                truncated=_response_truncated(current),
                retained=retained,
            )
        return self._with_attempts(last, attempts, repair_applied=attempts > 1)

    def parse_response(self, response: Any, **kwargs: Any) -> StructuredOutputResult:
        """Compatibility alias emphasizing provider response parsing."""
        return self.parse(response, **kwargs)

    def _parse_once(self, response: Any, *, truncated: bool, retained: bool) -> StructuredOutputResult:
        raw_text = _response_text(response)
        if raw_text is None or not raw_text.strip():
            return self._result(
                StructuredOutputStatus.MISSING,
                failure_type="missing_output",
                raw_text=raw_text,
                retained=retained,
            )
        candidate: Any
        normalized = raw_text.strip()
        if _is_json_fence(normalized):
            normalized = _strip_json_fence(normalized)
        try:
            candidate = _candidate_from_response(response, self.schema, normalized)
        except (json.JSONDecodeError, TypeError, ValueError) as exc:
            issue = ValidationIssue("invalid_json", f"response is not valid JSON: {exc}")
            return self._result(
                StructuredOutputStatus.INVALID,
                issues=(issue,),
                failure_type="truncated" if truncated else "invalid_json",
                raw_text=raw_text,
                retained=retained,
            )
        issues = tuple(_validate_schema(candidate, self.schema))
        if truncated:
            issues = issues + (
                ValidationIssue("truncated_response", "response was truncated by the provider"),
            )
        if issues:
            return self._result(
                StructuredOutputStatus.INVALID,
                issues=issues,
                failure_type="truncated" if truncated else "schema_validation",
                raw_text=raw_text,
                retained=retained,
            )
        return self._result(
            StructuredOutputStatus.PARSED,
            value=candidate,
            failure_type="truncated" if truncated else None,
            raw_text=raw_text,
            retained=retained,
        )

    def _result(
        self,
        status: StructuredOutputStatus,
        *,
        value: Any = None,
        issues: tuple[ValidationIssue, ...] = (),
        failure_type: str | None = None,
        attempts: int = 1,
        raw_text: str | None,
        retained: bool,
    ) -> StructuredOutputResult:
        safe_raw = None
        if retained and raw_text is not None:
            safe_raw = self.redact_raw(raw_text) if self.redact_raw else raw_text
        digest = hashlib.sha256((raw_text or "").encode("utf-8", errors="replace")).hexdigest()
        return StructuredOutputResult(
            contract_name=self.contract_name,
            contract_version=self.contract_version,
            status=status,
            value=value,
            issues=issues,
            failure_type=failure_type,
            attempts=attempts,
            raw_response_retained=retained,
            raw_response=safe_raw,
            raw_response_sha256=digest,
        )

    @staticmethod
    def _with_attempts(
        result: StructuredOutputResult, attempts: int, *, repair_applied: bool
    ) -> StructuredOutputResult:
        return StructuredOutputResult(
            **{
                **result.__dict__,
                "attempts": attempts,
                "repair_applied": repair_applied,
            }
        )


def attach_structured_output_evidence(
    trajectory: Mapping[str, Any],
    result: StructuredOutputResult,
) -> dict[str, Any]:
    """Copy a Format B trajectory and append parse evidence to its metadata."""
    out = dict(trajectory)
    metadata = dict(out.get("metadata") or {})
    events = list(metadata.get("structured_output_events") or [])
    events.append(result.to_trajectory_event())
    metadata["structured_output_events"] = events
    out["metadata"] = metadata
    return out


def _stable_json(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    except (TypeError, ValueError):
        return str(value)


def _response_text(response: Any) -> str | None:
    if response is None:
        return None
    if isinstance(response, bytes):
        return response.decode("utf-8", errors="replace")
    if isinstance(response, str):
        return response
    if isinstance(response, Mapping):
        # Known provider envelopes are unwrapped; a plain JSON object remains
        # an object and is validated against the declared schema directly.
        for key in ("output_text", "content", "text"):
            if key in response and isinstance(response[key], (str, bytes)):
                return _response_text(response[key])
        choices = response.get("choices")
        if isinstance(choices, Sequence) and not isinstance(choices, (str, bytes)) and choices:
            return _response_text(choices[0])
        message = response.get("message")
        if isinstance(message, Mapping):
            return _response_text(message)
        if "refusal" in response or "refused" in response or "finish_reason" in response:
            return None
        return _stable_json(response)
    return _stable_json(response)


def _response_refusal(response: Any) -> bool:
    if not isinstance(response, Mapping):
        return False
    if bool(response.get("refusal")) or bool(response.get("refused")):
        return True
    message = response.get("message")
    return isinstance(message, Mapping) and bool(message.get("refusal") or message.get("refused"))


def _response_truncated(response: Any) -> bool:
    if not isinstance(response, Mapping):
        return False
    reason = str(response.get("finish_reason") or response.get("stop_reason") or "").lower()
    return bool(response.get("truncated")) or reason in {"length", "max_tokens", "truncated"}


def _candidate_from_response(response: Any, schema: Any, normalized: str) -> Any:
    """Prefer a plain object, then unwrap a provider envelope if needed."""
    if not isinstance(response, Mapping):
        return json.loads(normalized)
    direct_issues = _validate_schema(response, schema)
    if not direct_issues:
        return response
    envelope_text = _response_text(response)
    if envelope_text is None or envelope_text == _stable_json(response):
        return response
    return json.loads(_strip_json_fence(envelope_text.strip()) if _is_json_fence(envelope_text.strip()) else envelope_text)


def _is_json_fence(text: str) -> bool:
    return text.startswith("```") and text.endswith("```")


def _strip_json_fence(text: str) -> str:
    lines = text.splitlines()
    if len(lines) >= 2:
        return "\n".join(lines[1:-1]).strip()
    return text.strip("`").strip()


def _invoke_repair(callback: Callable[..., Any], raw_text: str, result: StructuredOutputResult) -> Any:
    try:
        signature = inspect.signature(callback)
    except (TypeError, ValueError):
        return callback(raw_text, result)
    positional = [
        p for p in signature.parameters.values()
        if p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD)
    ]
    return callback(raw_text, result) if len(positional) >= 2 else callback(raw_text)


def _validate_schema(value: Any, schema: Any, path: str = "$") -> list[ValidationIssue]:
    if callable(schema) and not isinstance(schema, Mapping):
        try:
            result = schema(value)
        except Exception as exc:
            return [ValidationIssue("schema_validation", str(exc) or type(exc).__name__, path)]
        if result is True or result is None:
            return []
        if result is False:
            return [ValidationIssue("schema_validation", "schema validator rejected value", path)]
        if isinstance(result, str):
            return [ValidationIssue("schema_validation", result, path)]
        return [
            item if isinstance(item, ValidationIssue) else ValidationIssue("schema_validation", str(item), path)
            for item in result
        ]
    validator = getattr(schema, "validate", None)
    if callable(validator):
        try:
            result = validator(value)
        except Exception as exc:
            return [ValidationIssue("schema_validation", str(exc) or type(exc).__name__, path)]
        return [] if result is None or result is True else [ValidationIssue("schema_validation", str(result), path)]
    if not isinstance(schema, Mapping):
        raise TypeError("schema must be a mapping, callable, or validator object")
    issues: list[ValidationIssue] = []
    expected_type = schema.get("type")
    if expected_type and not _matches_type(value, expected_type):
        return [ValidationIssue("type_error", f"expected {expected_type}, got {_type_name(value)}", path)]
    if "enum" in schema and value not in schema["enum"]:
        issues.append(ValidationIssue("enum_error", "value is not one of the allowed values", path))
    if isinstance(value, Mapping):
        for name in schema.get("required", ()):
            if name not in value:
                issues.append(ValidationIssue("missing_field", f"required field is missing: {name}", f"{path}.{name}"))
        properties = schema.get("properties") or {}
        for name, child in properties.items():
            if name in value:
                issues.extend(_validate_schema(value[name], child, f"{path}.{name}"))
    if isinstance(value, list):
        item_schema = schema.get("items")
        if item_schema:
            for index, item in enumerate(value):
                issues.extend(_validate_schema(item, item_schema, f"{path}[{index}]"))
    return issues


def _matches_type(value: Any, expected: Any) -> bool:
    expected_types = expected if isinstance(expected, (list, tuple)) else (expected,)
    return any(
        {
            "object": isinstance(value, Mapping),
            "array": isinstance(value, list),
            "string": isinstance(value, str),
            "integer": isinstance(value, int) and not isinstance(value, bool),
            "number": isinstance(value, (int, float)) and not isinstance(value, bool),
            "boolean": isinstance(value, bool),
            "null": value is None,
        }.get(kind, True)
        for kind in expected_types
    )


def _type_name(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, Mapping):
        return "object"
    if isinstance(value, list):
        return "array"
    return type(value).__name__


__all__ = [
    "STRUCTURED_OUTPUT_CONTRACT_VERSION",
    "StructuredOutputContract",
    "StructuredOutputResult",
    "StructuredOutputStatus",
    "ParseStatus",
    "StructuredOutputParseResult",
    "ValidationIssue",
    "attach_structured_output_evidence",
]

# Short aliases make the status contract convenient for integrations while the
# descriptive names remain the canonical public API.
ParseStatus = StructuredOutputStatus
StructuredOutputParseResult = StructuredOutputResult
