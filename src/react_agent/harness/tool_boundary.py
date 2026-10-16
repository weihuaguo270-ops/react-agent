"""统一执行 required 模式下的本地工具安全边界。"""
from __future__ import annotations

import json
from collections.abc import Callable, Mapping, MutableMapping
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from dataclasses import dataclass
from typing import Any

from react_agent.harness.sandbox import SANDBOX
from react_agent.harness.contracts import ToolCall, ToolCallError, ToolError
from react_agent.safety.permission_gate import permission_block_message

DEFAULT_MAX_OUTPUT_CHARS = 10_000
IDEMPOTENCY_LEVELS = frozenset({"none", "safe", "required"})


@dataclass(frozen=True)
class ToolSpec:
    """Execution constraints extracted from an OpenAI/MCP tool definition."""

    name: str
    parameters: Mapping[str, Any] | None = None
    max_output_chars: int = DEFAULT_MAX_OUTPUT_CHARS
    timeout_seconds: float | None = None
    idempotency_level: str = "none"
    retryable: bool | None = None

    def __post_init__(self) -> None:
        if not str(self.name).strip():
            raise ValueError("tool spec name must not be empty")
        if self.max_output_chars <= 0:
            raise ValueError("max_output_chars must be positive")
        if self.timeout_seconds is not None and self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        if self.idempotency_level not in IDEMPOTENCY_LEVELS:
            raise ValueError("idempotency_level must be none, safe or required")
        if self.retryable is not None and not isinstance(self.retryable, bool):
            raise ValueError("retryable must be a boolean when provided")

    @classmethod
    def from_definition(cls, definition: Mapping[str, Any]) -> "ToolSpec":
        function = definition.get("function")
        if not isinstance(function, Mapping):
            function = definition
        return cls(
            name=str(function.get("name") or ""),
            parameters=function.get("parameters") or function.get("inputSchema"),
            max_output_chars=int(
                function.get("max_output_chars", DEFAULT_MAX_OUTPUT_CHARS)
            ),
            timeout_seconds=(
                float(function["timeout_seconds"])
                if function.get("timeout_seconds") is not None
                else None
            ),
            idempotency_level=str(
                function.get("idempotency_level", function.get("idempotency", "none"))
            ),
            retryable=function.get("retryable"),
        )


def _schema_type_matches(value: Any, expected: str) -> bool:
    return {
        "object": isinstance(value, Mapping),
        "array": isinstance(value, list),
        "string": isinstance(value, str),
        "integer": isinstance(value, int) and not isinstance(value, bool),
        "number": isinstance(value, (int, float)) and not isinstance(value, bool),
        "boolean": isinstance(value, bool),
        "null": value is None,
    }.get(expected, True)


def validate_tool_arguments(
    arguments: Mapping[str, Any], schema: Mapping[str, Any] | None
) -> None:
    """Validate the JSON-Schema subset used by registry and MCP definitions."""
    if not schema:
        return
    expected_type = schema.get("type")
    if expected_type and not _schema_type_matches(arguments, str(expected_type)):
        raise ValueError(f"tool arguments must be {expected_type}")
    properties = schema.get("properties") or {}
    if not isinstance(properties, Mapping):
        raise ValueError("tool parameter schema properties must be an object")
    required = schema.get("required") or []
    missing = [name for name in required if name not in arguments]
    if missing:
        raise ValueError(f"missing required tool arguments: {', '.join(map(str, missing))}")
    if schema.get("additionalProperties") is False:
        unknown = sorted(set(arguments) - set(properties))
        if unknown:
            raise ValueError(f"unknown tool arguments: {', '.join(map(str, unknown))}")
    for name, value in arguments.items():
        rule = properties.get(name)
        if not isinstance(rule, Mapping):
            continue
        expected = rule.get("type")
        if expected and not _schema_type_matches(value, str(expected)):
            raise ValueError(f"tool argument {name!r} must be {expected}")
        if "enum" in rule and value not in rule["enum"]:
            raise ValueError(f"tool argument {name!r} is not an allowed value")


def limit_tool_output(value: Any, max_output_chars: int = DEFAULT_MAX_OUTPUT_CHARS) -> Any:
    """Apply one output-size policy while preserving small native values."""
    if max_output_chars <= 0:
        raise ValueError("max_output_chars must be positive")
    if isinstance(value, bytes):
        value = value.decode("utf-8", errors="replace")
    if isinstance(value, str):
        return (
            value
            if len(value) <= max_output_chars
            else value[:max_output_chars] + "\n[truncated]"
        )
    try:
        encoded = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    except (TypeError, ValueError):
        encoded = str(value)
    if len(encoded) <= max_output_chars:
        return value
    return encoded[:max_output_chars] + "\n[truncated]"


def invoke_with_timeout(
    operation: Callable[[], Any],
    timeout_seconds: float | None,
    *,
    tool_name: str,
    source: str = "runtime",
) -> Any:
    """Run one tool attempt and convert failures to the shared ToolError."""
    if timeout_seconds is None:
        try:
            return operation()
        except ToolCallError:
            raise
        except Exception as exc:
            raise ToolCallError(
                ToolError.from_exception(exc, tool_name=tool_name, source=source)
            ) from exc
    if timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be positive")
    executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="harness-tool")
    future = executor.submit(operation)
    try:
        return future.result(timeout=timeout_seconds)
    except FutureTimeoutError as exc:
        future.cancel()
        timeout = TimeoutError(f"tool {tool_name} timed out after {timeout_seconds}s")
        raise ToolCallError(
            ToolError.from_exception(timeout, tool_name=tool_name, source=source)
        ) from exc
    except ToolCallError:
        raise
    except Exception as exc:
        raise ToolCallError(
            ToolError.from_exception(exc, tool_name=tool_name, source=source)
        ) from exc
    finally:
        executor.shutdown(wait=False, cancel_futures=True)


class ToolBoundary:
    """Canonical executor used by Registry, Workflow and Evaluation paths."""

    def __init__(
        self,
        registry: Mapping[str, Callable[..., Any]],
        *,
        definitions: list[Mapping[str, Any]] | None = None,
        default_timeout_seconds: float | None = None,
        default_max_output_chars: int = DEFAULT_MAX_OUTPUT_CHARS,
        risk_sandbox: bool = False,
        retry_policy=None,
        idempotency_policy=None,
        idempotency_store: MutableMapping[str, tuple[str, Any]] | None = None,
    ) -> None:
        from react_agent.harness.runtime import IdempotencyPolicy, RetryPolicy

        self.registry = registry
        self.default_timeout_seconds = default_timeout_seconds
        self.default_max_output_chars = default_max_output_chars
        self.risk_sandbox = risk_sandbox
        self.retry_policy = retry_policy or RetryPolicy(max_attempts=1)
        self.idempotency_policy = idempotency_policy or IdempotencyPolicy("none")
        self._idempotency_results = idempotency_store if idempotency_store is not None else {}
        self.specs = {
            spec.name: spec
            for spec in (ToolSpec.from_definition(item) for item in (definitions or []))
            if spec.name
        }

    def execute(
        self,
        tool_name: str,
        arguments: Mapping[str, Any] | str | None = None,
        *,
        timeout_seconds: float | None = None,
        max_output_chars: int | None = None,
        idempotency_key: str | None = None,
        call_id: str | None = None,
    ) -> Any:
        call = ToolCall(
            name=tool_name,
            arguments=arguments or {},
            timeout_seconds=timeout_seconds,
            idempotency_key=idempotency_key,
            call_id=call_id,
            source="runtime",
        )
        fn = self.registry.get(call.name)
        if fn is None:
            raise ToolCallError(
                ToolError(
                    code="tool_not_found",
                    message=f"unknown tool: {call.name}",
                    tool_name=call.name,
                    source="runtime",
                )
            )
        canonical_arguments = json.loads(call.arguments)
        # Permission and required-sandbox gates remain first-class exceptions
        # for compatibility with the existing approval and sandbox APIs.
        blocked = permission_block_message(call.name, canonical_arguments)
        if blocked is not None:
            raise PermissionError(blocked)
        spec = self.specs.get(
            call.name, ToolSpec(call.name, max_output_chars=self.default_max_output_chars)
        )
        policy = self.idempotency_policy
        if spec.idempotency_level != "none":
            policy = type(policy)(
                mode=spec.idempotency_level,
                key_source=policy.key_source,
                replay_behavior=policy.replay_behavior,
                bind_payload=policy.bind_payload,
            )
        key, payload_digest, cached, replayed = policy.lookup(
            self._idempotency_results,
            call.name,
            call.arguments,
            key=call.idempotency_key,
            call_id=call.call_id,
        )
        if replayed:
            return cached
        try:
            validate_tool_arguments(canonical_arguments, spec.parameters)
        except Exception as exc:
            raise ToolCallError(
                ToolError.from_exception(exc, tool_name=call.name, source="runtime")
            ) from exc

        from react_agent.harness.runtime import RetryPolicy

        required_sandbox = bool(getattr(SANDBOX, "required", False))
        effective_timeout = (
            call.timeout_seconds
            if call.timeout_seconds is not None
            else spec.timeout_seconds
            if spec.timeout_seconds is not None
            else self.default_timeout_seconds
        )
        use_sandbox = required_sandbox or (self.risk_sandbox and (
            getattr(SANDBOX, "strategy", "off") != "off"
            and SANDBOX.should_sandbox(call.name)
        ))
        def operation() -> Any:
            if use_sandbox:
                result = SANDBOX.run(
                    {"function": {"name": call.name, "arguments": call.arguments}}
                )
                if result == "__SANDBOX_DISABLED__":
                    if required_sandbox:
                        raise RuntimeError("required mode refused unsandboxed tool execution")
                    return invoke_with_timeout(
                        lambda: fn(**canonical_arguments),
                        effective_timeout,
                        tool_name=call.name,
                    )
                if isinstance(result, str) and result.startswith("[沙箱]"):
                    raise RuntimeError(result)
                return result
            return invoke_with_timeout(
                lambda: fn(**canonical_arguments),
                effective_timeout,
                tool_name=call.name,
            )

        retry_policy = self.retry_policy
        if spec.retryable is False or (policy.mode == "none" and retry_policy.max_attempts > 1):
            retry_policy = RetryPolicy(
                max_attempts=1,
                base_delay=retry_policy.base_delay,
                max_delay=retry_policy.max_delay,
                jitter_ratio=retry_policy.jitter_ratio,
                retryable_categories=retry_policy.retryable_categories,
                total_budget_seconds=retry_policy.total_budget_seconds,
            )
        result = retry_policy.run(operation)
        result = limit_tool_output(
            result,
            max_output_chars if max_output_chars is not None else spec.max_output_chars,
        )
        policy.record(self._idempotency_results, key, payload_digest, result)
        return result


def execute_registered_tool(
    tool_name: str,
    arguments: dict[str, Any] | str,
    registry: Mapping[str, Callable[..., Any]],
    *,
    definitions: list[Mapping[str, Any]] | None = None,
    timeout_seconds: float | None = None,
    max_output_chars: int | None = None,
    idempotency_key: str | None = None,
    call_id: str | None = None,
    risk_sandbox: bool = False,
    retry_policy=None,
    idempotency_policy=None,
    idempotency_store: MutableMapping[str, tuple[str, Any]] | None = None,
) -> Any:
    """兼容入口；所有本地工具调用均经过 :class:`ToolBoundary`."""
    if definitions is None:
        try:
            from react_agent.tools import get_tool_definitions

            definitions = get_tool_definitions()
        except Exception:
            definitions = []
    return ToolBoundary(
        registry,
        definitions=definitions,
        risk_sandbox=risk_sandbox,
        retry_policy=retry_policy,
        idempotency_policy=idempotency_policy,
        idempotency_store=idempotency_store,
    ).execute(
        tool_name,
        arguments,
        timeout_seconds=timeout_seconds,
        max_output_chars=max_output_chars,
        idempotency_key=idempotency_key,
        call_id=call_id,
    )


__all__ = [
    "DEFAULT_MAX_OUTPUT_CHARS",
    "IDEMPOTENCY_LEVELS",
    "ToolBoundary",
    "ToolSpec",
    "execute_registered_tool",
    "invoke_with_timeout",
    "limit_tool_output",
    "validate_tool_arguments",
]
