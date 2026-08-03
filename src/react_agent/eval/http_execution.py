"""Run execution suite tasks through HTTP /v1/chat (app=default)."""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any, Callable

from react_agent.eval.execution_scorer import load_execution_dataset, score_agent_task

HttpChatFn = Callable[[str, dict], tuple[int, dict]]


def http_chat(base_url: str, body: dict, *, timeout: float = 60) -> tuple[int, dict]:
    url = base_url.rstrip("/") + "/v1/chat"
    req = urllib.request.Request(
        url,
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8")
        try:
            return e.code, json.loads(raw)
        except json.JSONDecodeError:
            return e.code, {"error": {"message": raw[:300]}}


def _http_agent_runner_factory(base_url: str) -> Callable[..., tuple]:
    def runner(
        question: str,
        timeout: int = 90,
        max_steps: int | None = None,
        provider: str | None = None,
    ) -> tuple[str, dict | None, int, float]:
        del provider
        status, payload = http_chat(
            base_url,
            {
                "app": "default",
                "message": question,
                "max_steps": max_steps or 6,
            },
            timeout=float(timeout),
        )
        if status != 200:
            err = (payload.get("error") or {}).get("message", str(payload))
            return err, None, 1, 0.0

        answer = str(payload.get("answer") or "")
        tools = list(payload.get("tools_called") or [])
        steps = payload.get("agent_steps") or []
        traj_steps = [
            {"step": i + 1, "action": {"name": s.get("tool")}, "observation": s.get("observation", "")}
            for i, s in enumerate(steps)
        ]
        stdout_parts = [f"[调工具] {t}()" for t in tools]
        stdout_parts.append(f"FINAL ANSWER: {answer}")
        stdout = "\n".join(stdout_parts)
        trajectory = {"final_answer": answer, "steps": traj_steps}
        return stdout, trajectory, 0, 0.0

    return runner


def score_http_agent_task(
    task: dict,
    base_url: str,
    *,
    chat_fn: HttpChatFn | None = None,
) -> dict[str, Any]:
    """Score one agent task via HTTP; reuses agent outcome checks."""
    runner = _http_agent_runner_factory(base_url)
    result = score_agent_task(task, agent_runner=runner)
    result["transport"] = "http"
    result["base_url"] = base_url
    return result


def run_execution_http_smoke(
    base_url: str,
    *,
    only_ids: set[str] | None = None,
    difficulties: list[str] | None = None,
    smoke_ids: tuple[str, ...] = (
        "agent_calc_17x19",
        "agent_calc_100_minus_37",
        "agent_get_time",
    ),
) -> dict[str, Any]:
    """Run a small execution subset through POST /v1/chat app=default."""
    tasks = load_execution_dataset()
    wanted = set(smoke_ids)
    if only_ids:
        wanted = only_ids
    tasks = [t for t in tasks if t.get("mode") == "agent" and str(t.get("id")) in wanted]
    if difficulties:
        wanted_d = set(difficulties)
        tasks = [t for t in tasks if (t.get("difficulty") or "") in wanted_d]

    results = [score_http_agent_task(t, base_url) for t in tasks]
    passed = sum(1 for r in results if r.get("passed"))
    total = len(results)
    return {
        "summary": {
            "total": total,
            "passed": passed,
            "failed": total - passed,
            "pass_rate": round(100.0 * passed / total, 1) if total else 0.0,
        },
        "base_url": base_url,
        "transport": "http",
        "app": "default",
        "results": results,
    }
