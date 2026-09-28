from react_agent.apps.docs_troubleshoot.query_policy import classify_query_difficulty


def test_difficulty_uses_explainable_signals():
    trivial = classify_query_difficulty("法国首都是什么？")
    assert trivial["level"] == "trivial"
    assert trivial["requires_internal_retrieval"] is False

    complex_query = classify_query_difficulty(
        "服务返回 500，分析多服务调用链的根因并给出排障步骤",
        {"log_excerpt": "trace_id=abc"},
    )
    assert complex_query["level"] == "complex"
    assert complex_query["requires_internal_retrieval"] is True
    assert "structured_evidence" in complex_query["signals"]


def test_project_fact_is_standard_and_requires_evidence():
    result = classify_query_difficulty("项目的 API 默认超时是多少？")
    assert result["level"] == "standard"
    assert result["requires_internal_retrieval"] is True
    assert result["recommended_max_steps"] == 6
    assert result["dimensions"]["evidence"] == "项目资料"
