"""语义检索（向量）路径测试。

`REACT_AGENT_RAG_MODE` 默认是 ``auto``，但几乎所有入口（server / eval / apps）
都用 ``setdefault(..., "keyword")`` 把它钉在关键字模式，公共 RAG 基准也是——
所以向量检索这条路径此前没有任何测试覆盖。

这里用真实的本地嵌入模型把它跑通，并且刻意防住一种假通过：
``RAG.query`` 在异常时会静默回退关键字检索，因此「查询有结果」并不能证明语义
路径生效。真正有判别力的是「无词面重叠的同义改写」——关键字必然落空，只有
向量检索能命中，见 test_keyword_mode_misses_the_same_paraphrase 的对照。

离线：需要本地已有 BAAI/bge-small-zh-v1.5 缓存；``HF_HUB_OFFLINE=1`` 让
huggingface_hub 只读缓存、不联网校验（受限网络下 huggingface.co 不可达，
不设这个变量会卡在连接超时 + Hub 重试上）。模型缺失时整个模块 skip。
"""
from __future__ import annotations

import os
import tempfile

import pytest

from react_agent.rag import _HAS_VECTOR, RAG

_ENV_KEYS = ("REACT_AGENT_RAG_MODE", "HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE")

_DOCS = [
    ("travel.md", "差旅住宿标准\n\n一线城市每晚上限六百元，其他城市四百元。"),
    ("expense.md", "报销时限\n\n费用发生后三十日内提交。"),
    ("leave.md", "年假规定\n\n入职满一年享受五天年假。"),
]

# 与三篇文档都几乎没有词面重叠的同义改写：关键字检索必然落空。
_PARAPHRASE_QUERY = "去外地出差住酒店最多能报多少钱"
_EXPECTED_SOURCE = "travel.md"

# ingest_text 只写内存（rag.py 明确注释「避免把评测文档写进磁盘索引」），
# 因此这个路径不会被创建——测试既不碰真实的 rag_index.json，也不依赖
# pytest 的 tmp_path 机制（后者在某些受限沙箱下不可用）。
_INDEX_PATH = os.path.join(tempfile.gettempdir(), f"rag_semantic_test_{os.getpid()}.json")


def _build_rag(mode: str) -> RAG:
    os.environ["REACT_AGENT_RAG_MODE"] = mode
    rag = RAG(save_path=_INDEX_PATH)
    for source, body in _DOCS:
        rag.ingest_text(body, source=source)
    return rag


@pytest.fixture(scope="module")
def offline_env():
    """锁定语义模式 + HF 离线，模块结束后还原环境。"""
    saved = {key: os.environ.get(key) for key in _ENV_KEYS}
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    os.environ["REACT_AGENT_RAG_MODE"] = "semantic"
    try:
        yield
    finally:
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


@pytest.fixture(scope="module")
def embedding_model(offline_env):
    """真实的模型可用性探测：只有「模型确实加载不了」才 skip。

    刻意不把「ingest 后向量为空」当作 skip 依据——那会把「语义路径失效」这种
    应当失败的情况也一并跳过，让用例失去判别力。
    """
    if not _HAS_VECTOR:
        pytest.skip("缺少 [rag] 依赖（numpy / scikit-learn）")

    from sentence_transformers import SentenceTransformer

    try:
        return SentenceTransformer("BAAI/bge-small-zh-v1.5")
    except Exception as exc:  # 离线缓存缺失、依赖损坏等
        pytest.skip(f"本地嵌入模型不可用: {type(exc).__name__}: {str(exc)[:120]}")


@pytest.fixture(scope="module")
def semantic_rag(embedding_model):
    # 注入已加载的模型，避免 ingest 时再加载一次（本机约 11s）。
    rag = RAG(save_path=_INDEX_PATH)
    rag._model = embedding_model
    for source, body in _DOCS:
        rag.ingest_text(body, source=source)
    return rag


def test_semantic_ingest_produces_real_vectors(semantic_rag):
    """向量必须真的建出来。

    注意 len(vecs) == len(chunks) 在关键字模式下同样成立（每项是空列表），
    所以必须断言维度非零，否则这个用例会假通过。
    """
    assert len(semantic_rag.chunks) == len(_DOCS)
    assert len(semantic_rag.vecs) == len(semantic_rag.chunks)

    dims = {len(vec) for vec in semantic_rag.vecs}
    assert 0 not in dims, f"存在空向量，语义路径未生效: dims={dims}"
    assert len(dims) == 1, f"向量维度不一致: {dims}"
    assert dims.pop() > 1, "向量维度异常"


def test_semantic_finds_paraphrase_without_lexical_overlap(semantic_rag):
    """核心断言：向量检索能命中无词面重叠的同义改写。"""
    results = semantic_rag.query(_PARAPHRASE_QUERY, top_k=3)

    assert results, "语义检索应返回结果"
    assert results[0]["source"] == _EXPECTED_SOURCE, (
        f"应命中 {_EXPECTED_SOURCE}，实际: "
        f"{[(r['source'], r['score']) for r in results]}"
    )
    # 关键字模式给的是命中计数（整数），语义模式给的是余弦相似度（0~1 浮点）。
    assert 0.5 < results[0]["score"] <= 1.0, results[0]["score"]


def test_keyword_mode_misses_the_same_paraphrase(offline_env):
    """对照：同一查询在关键字模式下必然落空。

    没有这条对照，上面那条用例无法排除「语义路径静默回退关键字」导致的假通过。
    """
    saved = os.environ["REACT_AGENT_RAG_MODE"]
    try:
        rag = _build_rag("keyword")
        assert rag.query(_PARAPHRASE_QUERY, top_k=3) == [], (
            "关键字模式本不该命中这个同义改写；若命中，说明对照用例失去判别力"
        )
    finally:
        os.environ["REACT_AGENT_RAG_MODE"] = saved
