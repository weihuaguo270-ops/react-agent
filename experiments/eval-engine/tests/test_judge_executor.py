"""测试 judge/executor.py — JSON 解析 + Judge 初始化"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from judge.executor import _extract_json, JudgeExecutor, DEFAULT_JUDGE_SYSTEM_PROMPT


def test_extract_json_pure():
    """纯 JSON"""
    result = _extract_json('{"score": 4, "reason": "good"}')
    assert result["score"] == 4
    assert result["reason"] == "good"
    print("✅ test_extract_json_pure passed")


def test_extract_json_codeblock():
    """```json ... ``` 包裹"""
    text = """Here's my evaluation:
```json
{"score": 4.5, "rubrics": [{"dimension": "quality", "score": 4.5}]}
```
Done.
"""
    result = _extract_json(text)
    assert result["score"] == 4.5
    assert len(result["rubrics"]) == 1
    print("✅ test_extract_json_codeblock passed")


def test_extract_json_with_prefix():
    """JSON 前有文字"""
    text = """根据我的评估，结果如下：
{"score": 3, "rubrics": [{"dimension": "completeness", "score": 3, "reason": "缺了一些细节"}]}
这是最终结果。
"""
    result = _extract_json(text)
    assert result["score"] == 3
    print("✅ test_extract_json_with_prefix passed")


def test_extract_json_codeblock_no_marker():
    """``` ... ``` 无 json 标记"""
    text = """```
{"step_score": 2.5, "needs_revision": true}
```"""
    result = _extract_json(text)
    assert result["step_score"] == 2.5
    assert result["needs_revision"] is True
    print("✅ test_extract_json_codeblock_no_marker passed")


def test_extract_json_partial():
    """非标准 JSON 但有 score 字段"""
    text = """score: 4.5
reason: 做得好
"""
    result = _extract_json(text)
    # 应通过正则找到 score
    assert result["score"] == 4.5
    print("✅ test_extract_json_partial passed")


def test_extract_json_nested():
    """嵌套 JSON"""
    text = '{"per_step": [{"step": 0, "score": 4}, {"step": 1, "score": 3}], "overall": 3.5}'
    result = _extract_json(text)
    assert result["overall"] == 3.5
    assert len(result["per_step"]) == 2
    print("✅ test_extract_json_nested passed")


def test_judge_executor_init():
    """JudgeExecutor 初始化"""
    # 不用配置也能初始化（只是调用时会 fallback）
    judge = JudgeExecutor()
    assert judge is not None
    assert judge.temperature == 0.1
    assert judge.max_tokens == 1024
    print(f"✅ test_judge_executor_init passed: {judge}")


def test_judge_executor_fallback():
    """JudgeExecutor 无配置时的兜底行为

    通过传入一个不存在的 provider 强制走 fallback 路径。
    """
    # 清空环境变量，避免影响
    old_provider = os.environ.pop("JUDGE_PROVIDER", None)
    old_base = os.environ.pop("JUDGE_BASE_URL", None)

    # 没有 llm_config.json 的路径 → resolve 会失败 → fallback
    judge = JudgeExecutor(llm_config_path="/nonexistent/config.json")
    result = judge("这是一个测试 prompt")
    assert isinstance(result, dict)
    assert "rubrics" in result
    assert result.get("step_score") == 3.0  # 兜底分数
    assert result.get("needs_revision") is False
    print(f"✅ test_judge_executor_fallback passed: step_score={result.get('step_score')}")

    # 恢复环境变量
    if old_provider:
        os.environ["JUDGE_PROVIDER"] = old_provider
    if old_base:
        os.environ["JUDGE_BASE_URL"] = old_base


def test_judge_executor_custom_config():
    """通过环境变量配置 Judge（不设的话 fallback 也应该正常工作）"""
    # 模拟环境变量
    os.environ["JUDGE_MODEL"] = "deepseek-chat"

    judge = JudgeExecutor(provider="deepseek")
    assert judge.model_override == "deepseek-chat"
    # _model 需要在 _resolve 后才能访问，这里只检查不报错
    print(f"✅ test_judge_executor_custom_config passed")


def test_judge_executor_stats():
    """调用统计"""
    judge = JudgeExecutor()
    stats = judge.stats
    assert "total_calls" in stats
    assert "total_errors" in stats
    assert "avg_latency" in stats
    # 没调过，都是 0
    assert stats["total_calls"] == 0
    print(f"✅ test_judge_executor_stats passed")


if __name__ == "__main__":
    print("=" * 50)
    print("Judge Executor 测试")
    print("=" * 50)

    test_extract_json_pure()
    test_extract_json_codeblock()
    test_extract_json_with_prefix()
    test_extract_json_codeblock_no_marker()
    test_extract_json_partial()
    test_extract_json_nested()
    test_judge_executor_init()
    test_judge_executor_fallback()
    test_judge_executor_custom_config()
    test_judge_executor_stats()

    print("\n" + "=" * 50)
    print("✅ 全部 10 个测试通过")
    print("=" * 50)
