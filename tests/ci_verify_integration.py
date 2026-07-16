"""CI verification: Agent -> Eval integration (no pytest required)."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from react_agent.eval.scorer import score_with_eval_engine

traj = {
    "session_id": "ci_test",
    "query": "test",
    "steps": [
        {
            "step": 1,
            "thought": "search",
            "action": {"name": "web_search", "arguments": "{}"},
            "observation": "result",
        }
    ],
    "final_answer": "ok",
}

judge_fn = None
# 契约验证默认 mock（CI 可复现）；live Judge 仅当显式开启
if os.environ.get("REACT_AGENT_CI_LIVE_JUDGE") == "1":
    if os.environ.get("DEEPSEEK_API_KEY") or os.environ.get("JUDGE_API_KEY"):
        try:
            from eval_engine.judge.executor import JudgeExecutor

            judge_fn = JudgeExecutor()
            print("using live Judge LLM (REACT_AGENT_CI_LIVE_JUDGE=1)")
        except Exception as exc:
            print(f"live Judge unavailable: {exc}")

result = score_with_eval_engine(
    {"question": "test", "expected_tool": "web_search"},
    traj,
    judge_fn,
)
assert result is not None, "score_with_eval_engine returned None (eval-engine not installed?)"
assert result.get("status") == "success", result
assert result.get("eval_engine") is True, result
assert "error" not in result, result
assert result.get("total", 0) > 0, result
assert result.get("passed") is True, result
print(
    f"[PASS] eval-engine scoring: {result['total']}/{result['max_score']} "
    f"contract={result.get('api_contract')}"
)
