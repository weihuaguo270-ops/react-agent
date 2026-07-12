"""
端到端集成示例：Agent → 轨迹录制 → Eval 评分

演示如何将 react-agent 的执行轨迹送入 llm-eval-engine 进行评分。
使用 mock LLM 避免真实 API 调用，可在 CI 中运行。
"""

import json
import os
import sys

# 确保可以 import 两个包
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

# ------ Agent 部分 ------
from react_agent.harness import start_trajectory, finish_trajectory, current_trajectory


def run_mock_agent(query: str) -> dict:
    """模拟 Agent 执行，生成轨迹"""
    t = start_trajectory(query, model="mock-gpt")

    # Step 1: 思考
    t.add_step(0, thought="用户想了解 Python sort 的用法，我需要搜索一下")

    # Step 2: 搜索
    t.add_step(1, thought="执行搜索",
               action_name="web_search",
               action_args='{"query": "Python sort function"}',
               observation="sort() 是列表的内置方法，默认升序排序")

    # Step 3: 回答
    t.add_step(2, thought="已获取信息，可以回答",
               action_name="final_answer",
               action_args="{}",
               observation="")

    filepath = finish_trajectory("Python 的 sort() 方法是列表的内置排序函数...")
    return {"output": "Python 的 sort() 方法是列表的内置排序函数...", "trajectory_path": filepath}


# ------ Eval 部分 ------
def demo_eval_trajectory(trajectory_path: str):
    """读取轨迹并用 llm-eval-engine 评分"""
    try:
        from eval_engine.core.trajectory_parser import parse_trajectory
        from eval_engine.core.process_reward import ProcessRewardScorer
    except ImportError:
        print("⚠ llm-eval-engine 未安装，跳过评分
"
              "  运行: pip install -e /path/to/llm-eval-engine")
        return None, None

    with open(trajectory_path, "r") as f:
        raw = json.load(f)

    # 解析轨迹
    dag = parse_trajectory(raw)

    # Mock Judge（真实场景下换成 LLM API 调用）
    def mock_judge(prompt: str) -> dict:
        return {"score": 4.5, "reasoning": "步骤合理，回答准确", "details": []}

    # 评分
    scorer = ProcessRewardScorer(judge_fn=mock_judge)
    report = scorer.score_trajectory(dag, fast_mode=True)

    return report, dag


if __name__ == "__main__":
    print("=" * 50)
    print("Agent → Eval 端到端集成示例")
    print("=" * 50)

    # 1. Agent 执行
    query = "Python 的 sort 函数怎么用？"
    print(f"\n[1/3] Agent 执行: {query}")
    result = run_mock_agent(query)
    traj_path = result["trajectory_path"]
    print(f"      → 轨迹已保存: {traj_path}")

    # 2. Eval 评分
    print(f"\n[2/3] Eval 评分...")
    report, dag = demo_eval_trajectory(traj_path)

    if report:
        print(f"      → 评分完成")
        print(f"\n[3/3] 评估结果")
        print(f"{'='*40}")
        print(f"  Query:    {report.query}")
        print(f"  步骤数:   {report.num_steps}")
        print(f"  总分:     {report.overall_score:.2f}")
        print(f"  通过率:   {report.pass_rate:.1%}")
        print(f"  需修正:   {'是' if report.needs_revision else '否'}")

    # 清理
    if os.path.exists(traj_path):
        os.remove(traj_path)
        print(f"\n🧹 临时文件已清理")

    print("\n✅ 集成验证完成")
