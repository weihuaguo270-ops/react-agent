"""R2 policy integration tests for the non-streaming LLM path."""
from __future__ import annotations

import json
from urllib.error import URLError

import pytest


def test_llm_non_stream_uses_injected_retry_policy(monkeypatch):
    import react_agent.llm as llm_module
    from react_agent.harness import RetryPolicy

    calls = []

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return json.dumps(
                {"choices": [{"message": {"role": "assistant", "content": "ok"}}]}
            ).encode()

    def fake_urlopen(request, timeout):
        calls.append((request, timeout))
        if len(calls) < 3:
            raise URLError("upstream timeout")
        return Response()

    monkeypatch.setattr(llm_module.req, "urlopen", fake_urlopen)
    llm = llm_module.LLM(
        provider="custom",
        retry_policy=RetryPolicy(max_attempts=3, base_delay=0, jitter_ratio=0),
    )
    llm.base_url = "http://test"
    result = llm.chat([{"role": "user", "content": "hi"}])
    assert result["content"] == "ok"
    assert len(calls) == 3


def test_llm_stream_does_not_invoke_retry_policy(monkeypatch):
    import react_agent.llm as llm_module

    class ExplodingPolicy:
        def run(self, operation, **kwargs):
            raise AssertionError("streaming must not use RetryPolicy")

    llm = llm_module.LLM(provider="custom", retry_policy=ExplodingPolicy())
    calls = []

    def stream(*args, **kwargs):
        calls.append(1)
        raise URLError("stream failed")

    monkeypatch.setattr(llm, "_chat_stream", stream)
    result = llm.chat(
        [{"role": "user", "content": "hi"}],
        on_delta=lambda _piece: None,
    )
    assert len(calls) == 1
    assert "LLM调用失败" in result["content"]


def test_json_idempotency_store_replays_across_tool_boundary_instances(tmp_path):
    from react_agent.harness import IdempotencyPolicy, JsonIdempotencyStore, ToolBoundary

    calls = []

    def write_once():
        calls.append(1)
        return {"written": True}

    store_path = tmp_path / "idempotency.json"
    first = ToolBoundary(
        {"write_once": write_once},
        definitions=[{"name": "write_once", "idempotency_level": "required"}],
        idempotency_policy=IdempotencyPolicy("required"),
        idempotency_store=JsonIdempotencyStore(store_path),
    )
    assert first.execute("write_once", {}, idempotency_key="key-1") == {"written": True}

    second = ToolBoundary(
        {"write_once": write_once},
        definitions=[{"name": "write_once", "idempotency_level": "required"}],
        idempotency_policy=IdempotencyPolicy("required"),
        idempotency_store=JsonIdempotencyStore(store_path),
    )
    assert second.execute("write_once", {}, idempotency_key="key-1") == {"written": True}
    assert len(calls) == 1
    with pytest.raises(ValueError, match="conflicts"):
        second.execute("write_once", {"changed": True}, idempotency_key="key-1")


def test_json_idempotency_store_serializes_concurrent_writes(tmp_path):
    from concurrent.futures import ThreadPoolExecutor

    from react_agent.harness import JsonIdempotencyStore

    store_path = tmp_path / "concurrent-idempotency.json"

    def write(index):
        store = JsonIdempotencyStore(store_path)
        store[f"key-{index}"] = (f"digest-{index}", {"index": index})

    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(write, range(12)))

    final = JsonIdempotencyStore(store_path)
    assert len(final) == 12
    assert final["key-11"] == ("digest-11", {"index": 11})
