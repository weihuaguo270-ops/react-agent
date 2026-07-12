"""
End-to-end integration: Agent -> Trajectory Recording -> Eval Scoring

Demonstrates the full pipeline from react-agent execution to
llm-eval-engine scoring on the same trajectory data.
"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from react_agent.harness import start_trajectory, finish_trajectory


def run_mock_agent(query: str) -> dict:
    """Simulate agent execution and produce a trajectory"""
    t = start_trajectory(query, model="mock-gpt")
    t.add_step(0, thought="User wants to know about Python sort")
    t.add_step(1, thought="Searching...",
               action_name="web_search",
               action_args='{"query": "Python sort function"}',
               observation="sort() is a list method, ascending by default")
    t.add_step(2, thought="Got enough info to answer",
               action_name="final_answer",
               action_args="{}",
               observation="")
    filepath = finish_trajectory("sort() is a Python list method...")
    return {"output": "sort() is a Python list method...", "trajectory_path": filepath}


def demo_eval_trajectory(trajectory_path: str):
    """Score a trajectory using llm-eval-engine"""
    try:
        from eval_engine.core.trajectory_parser import parse_trajectory
        from eval_engine.core.process_reward import ProcessRewardScorer
    except ImportError:
        print("llm-eval-engine not installed - skipping scoring")
        print("Run: pip install -e /path/to/llm-eval-engine")
        return None, None

    with open(trajectory_path, "r") as f:
        raw = json.load(f)

    dag = parse_trajectory(raw)

    def mock_judge(prompt: str) -> dict:
        return {"score": 4.5, "reasoning": "Reasonable steps", "details": []}

    scorer = ProcessRewardScorer(judge_fn=mock_judge)
    report = scorer.score_trajectory(dag, fast_mode=True)
    return report, dag


if __name__ == "__main__":
    print("Agent to Eval Integration Demo")
    query = "How to use Python sort?"
    print("Step 1: Agent execution")
    result = run_mock_agent(query)
    traj_path = result["trajectory_path"]
    print("  trajectory saved to:", traj_path)

    print("Step 2: Eval scoring")
    report, dag = demo_eval_trajectory(traj_path)
    if report:
        print("  score:", report.overall_score)
        print("  steps:", report.num_steps)
        print("  pass rate:", report.pass_rate)

    if os.path.exists(traj_path):
        os.remove(traj_path)
    print("Done")
