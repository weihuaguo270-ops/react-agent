"""CI verification: Agent → Eval integration"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from react_agent.eval.scorer import score_with_eval_engine

traj = {
    "session_id": "ci_test",
    "query": "test",
    "steps": [
        {"step": 1, "thought": "search",
         "action": {"name": "web_search", "arguments": "{}"},
         "observation": "result"}
    ],
    "final_answer": "ok",
}

# 有 API key 时尝试用真实 Judge
judge_fn = None
if os.environ.get("DEEPSEEK_API_KEY") or os.environ.get("JUDGE_API_KEY"):
    try:
        from eval_engine.judge.executor import JudgeExecutor
        judge_fn = JudgeExecutor()
        print("使用真实 Judge LLM")
    except Exception:
        pass

result = score_with_eval_engine({"question": "test", "expected_tool": "web_search"}, traj, judge_fn)
assert result is not None, "score_with_eval_engine returned None"
assert result.get("eval_engine") is True
print(f"\u2705 eval-engine scoring: {result['total']}/{result['max_score']}")
