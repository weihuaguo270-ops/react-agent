"""Shared retry and idempotency decisions for Harness calls."""
from __future__ import annotations

import hashlib
import json
import random
import time
from dataclasses import dataclass
from typing import Any, Callable, Mapping, TypeVar

from react_agent.resilience import classify_error, is_retryable

T = TypeVar("T")


@dataclass(frozen=True)
class RetryPolicy:
    max_attempts: int = 3
    base_delay: float = 1.0
    max_delay: float = 30.0
    jitter_ratio: float = 0.3

    def __post_init__(self) -> None:
        if self.max_attempts < 1 or self.base_delay < 0 or self.max_delay < 0:
            raise ValueError("invalid retry policy bounds")
        if self.jitter_ratio < 0:
            raise ValueError("jitter_ratio must be non-negative")

    def should_retry(self, error: Exception | str, attempt: int) -> bool:
        return attempt < self.max_attempts and is_retryable(classify_error(error))

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
    ) -> T:
        """Run an operation under this policy and re-raise the terminal error."""
        for attempt in range(1, self.max_attempts + 1):
            try:
                return operation()
            except Exception as exc:
                if not self.should_retry(exc, attempt):
                    raise
                wait = self.delay(attempt, random_fn=random_fn)
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
    """Bind an idempotency key to the tool name and canonical payload."""

    mode: str = "none"  # none | safe | required

    def __post_init__(self) -> None:
        if self.mode not in {"none", "safe", "required"}:
            raise ValueError("idempotency mode must be none, safe or required")

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


__all__ = ["RetryPolicy", "IdempotencyPolicy"]
