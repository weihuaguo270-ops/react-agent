"""Flaky tool injection for live reliability harness.

Env:
  REACT_AGENT_INJECT_FLAKY=calculator:2,execute_python:1

Means: first N calls to that tool raise a timeout-like Exception
so ToolGuard can retry; after N failures the real tool runs.
"""

from __future__ import annotations

import os
from typing import Callable


_INSTALLED = False
_COUNTERS: dict[str, int] = {}


def parse_flaky_spec(spec: str) -> dict[str, int]:
    out: dict[str, int] = {}
    for part in (spec or "").split(","):
        part = part.strip()
        if not part or ":" not in part:
            continue
        name, n_s = part.split(":", 1)
        name = name.strip()
        try:
            n = int(n_s.strip())
        except ValueError:
            continue
        if name and n > 0:
            out[name] = n
    return out


def install_flaky_tools(registry: dict, spec: str | None = None) -> dict[str, int]:
    """Wrap TOOL_REGISTRY entries in-place. Idempotent per process."""
    global _INSTALLED
    if _INSTALLED:
        return dict(_COUNTERS)
    raw = spec if spec is not None else os.environ.get("REACT_AGENT_INJECT_FLAKY", "")
    plan = parse_flaky_spec(raw)
    if not plan:
        return {}

    for name, fail_n in plan.items():
        if name not in registry:
            print(f"  [FlakyInject] skip unknown tool: {name}")
            continue
        original: Callable = registry[name]
        _COUNTERS[name] = 0

        def _make(orig: Callable, tool: str, n: int) -> Callable:
            def wrapped(**kwargs):
                _COUNTERS[tool] = _COUNTERS.get(tool, 0) + 1
                if _COUNTERS[tool] <= n:
                    raise Exception(f"timeout (injected flaky #{_COUNTERS[tool]}/{n})")
                return orig(**kwargs)

            return wrapped

        registry[name] = _make(original, name, fail_n)
        print(f"  [FlakyInject] {name}: fail first {fail_n} call(s)")

    _INSTALLED = True
    return dict(plan)


def flaky_call_counts() -> dict[str, int]:
    return dict(_COUNTERS)
