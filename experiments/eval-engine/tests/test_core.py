"""测试 trajectory_parser + process_reward 核心流程

用模拟轨迹数据验证解析和评分流程是否正常。
"""

import sys
import os

# 确保可以 import eval-engine
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.contract import VerifierContract
from core.trajectory_parser import parse_trajectory, dag_to_text, dag_summary
from core.dynamic_rubric import build_step_context, build_step_judge_prompt


def test_contract():
    """VerifierContract 基础功能"""
    v = VerifierContract(
        name="faithfulness",
        rubric="1=编造, 5=基于 context",
        min_score=4,
        weight=2.0,
    )
    assert v.name == "faithfulness"
    assert v.passed(4.5) is True
    assert v.passed(3.0) is False
    assert str(v.weight) == "2.0"
    print("✅ test_contract passed")


def test_parse_trajectory():
    """解析模拟轨迹"""
    trajectory = {
        "session_id": "traj_test_001",
        "query": "帮我查一下Python的sort函数用法",
        "steps": [
            {"step_index": 0, "type": "thought",
             "content": "用户想知道Python sort函数用法，先搜索一下"},
            {"step_index": 1, "type": "action",
             "action": {"name": "web_search", "args": {"query": "Python sort函数用法"}},
             "content": "web_search(query='Python sort函数用法')"},
            {"step_index": 2, "type": "observation",
             "content": "搜索结果：sort()是列表的内置方法...",
             "observation": "搜索结果：sort()是列表的内置方法..."},
            {"step_index": 3, "type": "thought",
             "content": "已获得结果，可以回答了"},
            {"step_index": 4, "type": "final",
             "content": "Python的sort()是列表的内置方法，用于原地排序..."},
        ],
        "total_steps": 5,
        "total_tokens_estimated": 500,
        "final_answer": "Python的sort()是列表的内置方法，用于原地排序...",
    }

    dag = parse_trajectory(trajectory)
    assert dag.num_steps == 5
    assert dag.query == "帮我查一下Python的sort函数用法"
    assert dag.final_answer == "Python的sort()是列表的内置方法，用于原地排序..."
    assert dag.get_node(1).tool_name == "web_search"

    # 验证 DAG 边已自动构建
    assert len(dag.edges) >= 4  # 至少 control_flow 边
    print("✅ test_parse_trajectory passed")
    print(f"   DAG: {dag.num_steps} 步, {len(dag.edges)} 条边")
    print(f"   工具: {[n.tool_name for n in dag.nodes if n.tool_name]}")


def test_step_context():
    """构建单步评分上下文"""
    trajectory = {
        "session_id": "traj_test_002",
        "query": "对比Python和JavaScript的优缺点",
        "steps": [
            {"step_index": 0, "type": "thought",
             "content": "需要对比两种语言，先搜索各自优缺点"},
            {"step_index": 1, "type": "action",
             "action": {"name": "web_search",
                        "args": {"query": "Python vs JavaScript 优缺点对比"}},
             "content": "web_search..."},
            {"step_index": 2, "type": "observation",
             "content": "搜索结果：Python在数据科学方面更强...",
             "observation": "搜索结果：Python在数据科学方面更强..."},
            {"step_index": 3, "type": "final",
             "content": "Python和JavaScript各有优势..."},
        ],
        "total_steps": 4,
        "final_answer": "Python和JavaScript各有优势...",
    }

    dag = parse_trajectory(trajectory)

    # 构建 Step 1（action）的上下文
    ctx = build_step_context(dag, step_index=1)
    assert ctx.step_index == 1
    assert ctx.current_step.tool_name == "web_search"
    assert ctx.total_steps == 4
    assert len(ctx.previous_steps) == 1  # 前一步（thought）
    assert len(ctx.downstream_steps) >= 1  # 后续步骤

    # 生成 Judge prompt
    prompt = build_step_judge_prompt(ctx)
    assert "web_search" in prompt
    assert "对比Python和JavaScript" in prompt
    print("✅ test_step_context passed")


def test_dag_find_error_sources():
    """错误源头定位"""
    trajectory = {
        "session_id": "traj_test_003",
        "query": "计算 123*456 是多少",
        "steps": [
            {"step_index": 0, "type": "thought",
             "content": "用户想计算123乘以456"},
            {"step_index": 1, "type": "action",
             "action": {"name": "calculator", "args": {"expression": "123*456"}},
             "content": "calculator(123*456)"},
            {"step_index": 2, "type": "observation",
             "content": "56088", "observation": "56088"},
            {"step_index": 3, "type": "final",
             "content": "123*456=56088"},
        ],
        "total_steps": 4,
        "final_answer": "123*456=56088",
    }

    dag = parse_trajectory(trajectory)

    # 手动设置低分（模拟评分结果）
    dag.get_node(1).score = 0.3  # 工具调用有问题
    dag.get_node(2).score = 0.9
    dag.get_node(3).score = 0.5  # 最终答案受波及

    sources = dag.find_error_sources()
    assert 1 in [s.step_index for s in sources]
    print(f"✅ test_dag_find_error_sources passed: 根因 Step {[s.step_index for s in sources]}")


def test_summary():
    """DAG 摘要"""
    trajectory = {
        "session_id": "traj_test_004",
        "query": "测试摘要功能",
        "steps": [
            {"step_index": 0, "type": "thought", "content": "先想想"},
            {"step_index": 1, "type": "action",
             "action": {"name": "get_time", "args": {}},
             "content": "get_time()"},
            {"step_index": 2, "type": "observation",
             "content": "2026-07-10", "observation": "2026-07-10"},
            {"step_index": 3, "type": "final", "content": "现在是2026年7月"},
        ],
        "total_steps": 4,
        "final_answer": "现在是2026年7月",
    }
    dag = parse_trajectory(trajectory)
    summary = dag_summary(dag)
    assert summary["total_steps"] == 4
    assert "get_time" in summary["tools_used"]
    print(f"✅ test_summary passed: {summary['step_types']}")


if __name__ == "__main__":
    print("=" * 50)
    print("eval-engine 核心模块测试")
    print("=" * 50)
    test_contract()
    test_parse_trajectory()
    test_step_context()
    test_dag_find_error_sources()
    test_summary()
    print("\n" + "=" * 50)
    print("✅ 全部测试通过")
    print("=" * 50)
