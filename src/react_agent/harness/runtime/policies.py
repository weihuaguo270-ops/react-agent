"""Shared retry and idempotency decisions for Harness calls."""
from __future__ import annotations

import hashlib
import json
import random
import os
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from collections.abc import Iterator, MutableMapping
from typing import Any, Callable, Mapping, TypeVar

from react_agent.resilience import classify_error, is_retryable

T = TypeVar("T")


class JsonIdempotencyStore(MutableMapping[str, tuple[str, Any]]):
    """Small durable idempotency ledger for process and worker restarts."""

    def __init__(self, path: str | os.PathLike[str]) -> None:
        self.path = Path(path)
        self._data: dict[str, tuple[str, Any]] = {}
        if self.path.exists():
            try:
                payload = json.loads(self.path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise ValueError(f"unable to load idempotency store: {self.path}") from exc
            if not isinstance(payload, Mapping):
                raise ValueError("idempotency store must contain an object")
            for key, value in payload.items():
                if not isinstance(value, list) or len(value) != 2:
                    raise ValueError("idempotency store entries must be [payload_hash, result]")
                self._data[str(key)] = (str(value[0]), value[1])

    def __getitem__(self, key: str) -> tuple[str, Any]:
        return self._data[key]

    def __setitem__(self, key: str, value: tuple[str, Any]) -> None:
        if not isinstance(value, tuple) or len(value) != 2:
            raise ValueError("idempotency store values must be (payload_hash, result)")
        try:
            json.dumps(value[1], ensure_ascii=False)
        except (TypeError, ValueError) as exc:
            raise ValueError("idempotency result must be JSON serializable") from exc
        self._data[str(key)] = (str(value[0]), value[1])
        self._flush()

    def __delitem__(self, key: str) -> None:
        del self._data[key]
        self._flush()

    def __iter__(self) -> Iterator[str]:
        return iter(self._data)

    def __len__(self) -> int:
        return len(self._data)

    def _flush(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {key: [digest, result] for key, (digest, result) in self._data.items()}
        fd, temporary = tempfile.mkstemp(prefix=f".{self.path.name}.", dir=self.path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False, sort_keys=True)
                handle.write("\n")
            os.replace(temporary, self.path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)


class RetryBudgetExceeded(TimeoutError):
    """Raised when a retry policy cannot start another attempt within its budget."""


@dataclass(frozen=True)
class RetryPolicy:
    max_attempts: int = 3
    base_delay: float = 1.0
    max_delay: float = 30.0
    jitter_ratio: float = 0.3
    retryable_categories: frozenset[str] | None = None
    total_budget_seconds: float | None = None

    def __post_init__(self) -> None:
        if self.max_attempts < 1 or self.base_delay < 0 or self.max_delay < 0:
            raise ValueError("invalid retry policy bounds")
        if self.jitter_ratio < 0:
            raise ValueError("jitter_ratio must be non-negative")
        if self.total_budget_seconds is not None and self.total_budget_seconds <= 0:
            raise ValueError("total_budget_seconds must be positive")
        if self.retryable_categories is not None:
            object.__setattr__(
                self, "retryable_categories", frozenset(self.retryable_categories)
            )

    def should_retry(self, error: Exception | str, attempt: int) -> bool:
        category = classify_error(error)
        allowed = (
            is_retryable(category)
            if self.retryable_categories is None
            else category in self.retryable_categories
        )
        return attempt < self.max_attempts and allowed

    def with_max_attempts(self, max_attempts: int) -> "RetryPolicy":
        """Return a copy with a compatibility attempt limit override."""
        return RetryPolicy(
            max_attempts=max_attempts,
            base_delay=self.base_delay,
            max_delay=self.max_delay,
            jitter_ratio=self.jitter_ratio,
            retryable_categories=self.retryable_categories,
            total_budget_seconds=self.total_budget_seconds,
        )

    def delay(
        self, attempt: int, *, random_fn: Callable[[], float] | None = None
    ) -> float:
        base = min(self.base_delay * (2 ** max(0, attempt - 1)), self.max_delay)
        jitter = (random_fn or random.random)() * base * self.jitter_ratio
        return base + jitter

    def run(
        self,
        operation: Callable[[], T],
        *,
        on_retry: Callable[[int, int, float, str, str], None] | None = None,
        sleep_fn: Callable[[float], None] = time.sleep,
        random_fn: Callable[[], float] | None = None,
        monotonic_fn: Callable[[], float] = time.monotonic,
    ) -> T:
        """Run an operation under this policy and re-raise the terminal error."""
        started = monotonic_fn()
        for attempt in range(1, self.max_attempts + 1):
            if (
                self.total_budget_seconds is not None
                and monotonic_fn() - started >= self.total_budget_seconds
            ):
                raise RetryBudgetExceeded(
                    f"retry budget exhausted after {self.total_budget_seconds}s"
                )
            try:
                return operation()
            except Exception as exc:
                if not self.should_retry(exc, attempt):
                    raise
                wait = self.delay(attempt, random_fn=random_fn)
                if self.total_budget_seconds is not None:
                    elapsed = monotonic_fn() - started
                    remaining = self.total_budget_seconds - elapsed
                    if remaining <= 0 or wait > remaining:
                        raise RetryBudgetExceeded(
                            f"retry budget exhausted after {self.total_budget_seconds}s"
                        ) from exc
                if on_retry:
                    on_retry(
                        attempt,
                        self.max_attempts,
                        wait,
                        classify_error(exc),
                        str(exc),
                    )
                sleep_fn(wait)
        raise RuntimeError("retry policy exhausted without a result")


@dataclass(frozen=True)
class IdempotencyPolicy:
    """Bind a key to a canonical payload and define duplicate-call behavior."""

    mode: str = "none"  # none | safe | required
    key_source: str = "explicit"  # explicit | call_id | explicit_or_call_id | payload_hash
    replay_behavior: str = "return_cached"  # return_cached | reject | execute
    bind_payload: bool = True

    def __post_init__(self) -> None:
        if self.mode not in {"none", "safe", "required"}:
            raise ValueError("idempotency mode must be none, safe or required")
        if self.key_source not in {
            "explicit",
            "call_id",
            "explicit_or_call_id",
            "payload_hash",
        }:
            raise ValueError("unsupported idempotency key source")
        if self.replay_behavior not in {"return_cached", "reject", "execute"}:
            raise ValueError("unsupported idempotency replay behavior")

    def payload_hash(self, tool_name: str, arguments: Mapping[str, Any] | str) -> str:
        args = json.loads(arguments) if isinstance(arguments, str) else dict(arguments)
        raw = json.dumps(
            {"tool": tool_name, "arguments": args},
            sort_keys=True,
            ensure_ascii=False,
            separators=(",", ":"),
        )
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def validate_key(self, key: str | None) -> None:
        if self.mode == "required" and not str(key or "").strip():
            raise ValueError("idempotency key is required")

    def resolve_key(
        self,
        key: str | None,
        *,
        call_id: str | None = None,
        tool_name: str = "",
        arguments: Mapping[str, Any] | str | None = None,
    ) -> str | None:
        """Resolve the configured key source before validating or recording it."""
        if self.key_source == "call_id":
            resolved = call_id
        elif self.key_source == "explicit_or_call_id":
            resolved = key or call_id
        elif self.key_source == "payload_hash":
            resolved = self.payload_hash(tool_name, arguments or {})
        else:
            resolved = key
        resolved = str(resolved or "").strip() or None
        self.validate_key(resolved)
        return resolved

    def lookup(
        self,
        ledger: MutableMapping[str, tuple[str, Any]],
        tool_name: str,
        arguments: Mapping[str, Any] | str,
        *,
        key: str | None = None,
        call_id: str | None = None,
    ) -> tuple[str | None, str, Any | None, bool]:
        """Return ``(resolved_key, payload_hash, cached_result, replayed)``."""
        payload_digest = self.payload_hash(tool_name, arguments)
        resolved_key = self.resolve_key(
            key,
            call_id=call_id,
            tool_name=tool_name,
            arguments=arguments,
        )
        if not resolved_key or self.mode == "none":
            return resolved_key, payload_digest, None, False
        previous = ledger.get(resolved_key)
        if previous is None or self.replay_behavior == "execute":
            return resolved_key, payload_digest, None, False
        previous_hash, previous_result = previous
        if self.bind_payload and previous_hash != payload_digest:
            raise ValueError("idempotency key conflicts with a different payload")
        if self.replay_behavior == "reject":
            raise ValueError("idempotent replay rejected")
        return resolved_key, payload_digest, previous_result, True

    def record(
        self,
        ledger: MutableMapping[str, tuple[str, Any]],
        key: str | None,
        payload_digest: str,
        result: Any,
    ) -> None:
        if key and self.mode != "none":
            ledger[key] = (payload_digest, result)


__all__ = ["IdempotencyPolicy", "JsonIdempotencyStore", "RetryBudgetExceeded", "RetryPolicy"]
