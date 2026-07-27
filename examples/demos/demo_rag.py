"""Offline RAG demo：关键词检索 fixtures/rag_corpus（无需 [rag] 向量依赖）。

用法:
  set REACT_AGENT_RAG_MODE=keyword
  python examples/demos/demo_rag.py
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

os.environ.setdefault("REACT_AGENT_RAG_MODE", "keyword")

from react_agent.rag import RAG


def main():
    corpus = ROOT / "fixtures" / "rag_corpus"
    with tempfile.TemporaryDirectory() as td:
        rag = RAG(save_path=str(Path(td) / "demo_rag.json"))
        rag.clear()
        rag.ingest_directory(str(corpus))
        queries = [
            "餐饮报销上限是多少？",
            "如何配置 API Key？",
            "金额超过 1000 谁审批？",
        ]
        for q in queries:
            print(f"\n=== Q: {q}")
            hits = rag.query(q, top_k=2)
            if not hits:
                print("  (无命中)")
                continue
            for h in hits:
                snippet = h["content"].replace("\n", " ")[:120]
                print(f"  [{h['score']:.0f}] {h['source']}: {snippet}...")
        print("\nAgent 工具入口: rag_query(query)（文档库非空时）")


if __name__ == "__main__":
    main()
