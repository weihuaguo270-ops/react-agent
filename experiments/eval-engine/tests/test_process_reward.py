"""测试 process_reward + eval_loop 集成流程

使用模拟的 Judge 函数测试评分流程和错误分析。
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.trajectory_parser import parse_trajectory
from core.process_reward import (
    ProcessRewardScorer,
    analyze_error_propagation,
    pack_revision_instructions,
)


def _mock_judge(prompt: str) -> dict:
    """模拟 Judge LLM 调用

    根据步骤类型（%5B 即 [ 的编码形式）区分评分结果。
    实际场景中，prompt 里会包含 [thought]、[action]、[observation]、[final]。
    """
    step_type_markers = {
        "thought": ("thought", 3.5, False, ["推理基本正确"]),
        "action": ("action", 4.25, False, ["选择了合适的工具", "参数合理"]),
        "observation": ("observation", 4.0, False, ["正确解读了返回结果"]),
        "final": ("final", 2.5, True, ["遗漏了关键信息", "部分基于搜索结果"]),
    }
    for marker, (_, score, needs_rev, reasons) in step_type_markers.items():
        type_marker = f"类型: {marker}"
        if type_marker in prompt:
            rubrics = [
                {"dimension": f"{marker}_quality", "criteria": f"{marker} 质量",
                 "score": score, "reason": reasons[i] if i < len(reasons) else "合格"}
                for i in range(len(reasons))
            ]
            return {
                "role_understanding": f"Agent 执行 {marker} 步骤",
                "rubrics": rubrics if rubrics else [{"dimension": "general", "criteria": "通用", "score": 3.0, "reason": "无明显问题"}],
                "step_score": score,
                "needs_revision": needs_rev,
            }
    return {
        "role_understanding": "未知步骤",
        "rubrics": [{"dimension": "general", "criteria": "通用", "score": 3.0, "reason": "无明显问题"}],
        "step_score": 3.0,
        "needs_revision": False,
    }


def _mock_bad_judge(prompt: str) -> dict:
    """模拟有错误的步骤（action 步骤有误导致 cascade）"""
    if "类型: action" in prompt:
        return {
            "role_understanding": "工具调用失败",
            "rubrics": [
                {"dimension": "tool_selection", "criteria": "工具选择", "score": 1.0, "reason": "工具参数错误，调用失败"},
                {"dimension": "argument_quality", "criteria": "参数质量", "score": 1.0, "reason": "参数为编造值"},
            ],
            "step_score": 1.0,
            "needs_revision": True,
        }
    return _mock_judge(prompt)


def test_process_reward_good():
    """正常评分的 Process Reward"""
    trajectory = {
        "session_id": "traj_test_pr_01",
        "query": "搜索Python的sort函数用法并总结",
        "steps": [
            {"step_index": 0, "type": "thought",
             "content": "先搜索Python sort函数用法"},
            {"step_index": 1, "type": "action",
             "action": {"name": "web_search", "args": {"query": "Python sort"}},
             "content": "web_search..."},
            {"step_index": 2, "type": "observation",
             "content": "搜索结果：sort()是列表内置方法...",
             "observation": "搜索结果：sort()是列表内置方法..."},
            {"step_index": 3, "type": "final",
             "content": "Python的sort()方法用于列表原地排序..."},
        ],
        "total_steps": 4,
        "final_answer": "Python的sort()方法用于列表原地排序...",
    }

    dag = parse_trajectory(trajectory)
    scorer = ProcessRewardScorer(judge_fn=_mock_judge, min_step_score=3.5)
    report = scorer.score_trajectory(dag, fast_mode=False)

    print(f"总分: {report.overall_score:.3f}")
    print(f"失败步骤: {report.num_failed_steps}")
    print(f"需修正: {report.needs_revision}")
    for s in report.per_step:
        print(f"  Step {s.step_index} [{s.step_type}]: {s.step_score:.2f} {'❌' if s.needs_revision else '✅'}")

    assert report.num_scored == 4
    assert report.num_failed_steps >= 1  # final step fails in mock

    # 错误传播分析
    error_analysis = analyze_error_propagation(report, dag)
    print(f"错误源头: {error_analysis['error_sources']}")

    # 修正指令
    fix = pack_revision_instructions(report, dag)
    print(f"\n修正指令预览:\n{fix[:300]}...")
    assert "需修正" in fix or "修正" in fix or "评估" in fix

    print("✅ test_process_reward_good passed")


def test_iteration_improvement():
    """模拟两次迭代分数提升"""
    trajectory = {
        "session_id": "traj_test_iter",
        "query": "计算 (23+45)*2",
        "steps": [
            {"step_index": 0, "type": "thought", "content": "先计算"},
            {"step_index": 1, "type": "action",
             "action": {"name": "calculator", "args": {"expression": "(23+45)*2"}},
             "content": "calculator"},
            {"step_index": 2, "type": "observation",
             "content": "136", "observation": "136"},
            {"step_index": 3, "type": "final",
             "content": "结果是136"},
        ],
        "total_steps": 4,
        "final_answer": "结果是136",
    }

    dag = parse_trajectory(trajectory)
    scorer = ProcessRewardScorer(judge_fn=_mock_judge)
    report = scorer.score_trajectory(dag)

    print(f"\n[迭代测试] 总分: {report.overall_score:.3f}")
    if report.needs_revision:
        fix = pack_revision_instructions(report, dag)
        print(f"修正指令长度: {len(fix)} 字符")

    print("✅ test_iteration_improvement passed")


if __name__ == "__main__":
    print("=" * 50)
    print("Process Reward + 错误分析 测试")
    print("=" * 50)
    test_process_reward_good()
    test_iteration_improvement()
    print("\n" + "=" * 50)
    print("✅ 全部测试通过")
    print("=" * 50)
