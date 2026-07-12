"""CI verification: Agent → Eval integration"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from react_agent.eval.scorer import score_with_eval_engine

traj = {
    "session_id": "ci_test",
    "query": "test",
    "steps": [
        {"step": 0, "thought": "search",
         "action": {"name": "web_search", "arguments": "{}"},
         "observation": "result"}
    ],
    "final_answer": "ok",
}

result = score_with_eval_engine({"question": "test", "expected_tool": "web_search"}, traj)
assert result is not None, "score_with_eval_engine returned None"
assert result.get("eval_engine") is True
print(f"✅ eval-engine scoring: {result['total']}/{result['max_score']}")
