
"""
RAG — 检索增强生成模块
=======================
为 Agent 提供文档知识检索能力。
基于 BGE-small-zh-v1.5 语义搜索。

用法:
  rag = RAG()
  rag.ingest("doc.md")           # 加载一个文件
  rag.ingest_directory("docs/")  # 批量加载目录
  results = rag.query("如何配置API Key？", top_k=3)
"""

import json
import os
import glob

try:
    import numpy as np
    from sklearn.metrics.pairwise import cosine_similarity
    _HAS_VECTOR = True
except ImportError:  # pragma: no cover
    np = None
    cosine_similarity = None
    _HAS_VECTOR = False


class RAG:
    MAX_CHUNKS = 2000

    def __init__(self, save_path=None, chunk_size=500, chunk_overlap=50):
        if save_path is None:
            save_path = os.path.join(
                os.path.dirname(os.path.abspath(__file__)), "rag_index.json"
            )
        self.save_path = save_path
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.chunks = []     # 文本片段
        self.sources = []    # 每个片段对应的来源文件名
        self.vecs = []       # 向量
        self._model = None   # 懒加载
        self._load()

    def _get_model(self):
        """首次使用时加载 BGE 模型，后续复用"""
        if not _HAS_VECTOR:
            raise ImportError('RAG 需要: pip install -e ".[rag]"')
        if self._model is None:
            from sentence_transformers import SentenceTransformer
            self._model = SentenceTransformer('BAAI/bge-small-zh-v1.5')
        return self._model

    # ================================================================
    # 文本分块 (Chunking)
    # ================================================================
    def _chunk_text(self, text, source=""):
        """
        将长文本切成大小合适的块。
        策略: 先按段落(\n\n)分，超长段落按句子分。
        """
        paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
        chunks = []
        current = ""

        for para in paragraphs:
            # 当前段落加上后不超过 chunk_size → 继续累积
            if len(current) + len(para) < self.chunk_size:
                current += para + "\n\n"
            else:
                # 保存当前累积
                if current:
                    chunks.append(current.strip())
                # 段落本身超长 → 按句子切
                if len(para) > self.chunk_size:
                    for sent in self._split_sentences(para):
                        if len(current) + len(sent) < self.chunk_size:
                            current += sent
                        else:
                            if current:
                                chunks.append(current.strip())
                            current = sent
                else:
                    current = para + "\n\n"

        if current:
            chunks.append(current.strip())

        # 确保每个 chunk 有意义且有来源
        sources = [source] * len(chunks)
        return chunks, sources

    def _split_sentences(self, text):
        """按中文句号、感叹号、问号拆分句子"""
        import re
        parts = re.split(r'(?<=[。！？.!?])', text)
        return [p.strip() for p in parts if p.strip()]

    # ================================================================
    # 文档加载
    # ================================================================
    def ingest(self, file_path):
        """加载一个文件：读取 → 分块 → 向量化 → 去重存储"""
        if not os.path.exists(file_path):
            print(f"[RAG] 文件不存在: {file_path}")
            return False

        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
            text = f.read()

        if not text.strip():
            print(f"[RAG] 空文件: {file_path}")
            return False

        new_chunks, new_sources = self._chunk_text(text, os.path.basename(file_path))

        # 去重：不重复加载已有片段
        existing = set(self.chunks)
        added = 0
        use_vectors = _HAS_VECTOR and self._rag_mode() != "keyword"
        for chunk, src in zip(new_chunks, new_sources):
            if chunk not in existing:
                self.chunks.append(chunk)
                self.sources.append(src)
                if use_vectors:
                    try:
                        vec = self._get_model().encode(chunk)
                        self.vecs.append(vec)
                    except Exception:
                        self.vecs.append([])
                else:
                    self.vecs.append([])
                added += 1

        mode = "keyword" if not use_vectors else "semantic"
        print(
            f"[RAG] 从 {os.path.basename(file_path)} 加载了 "
            f"{added}/{len(new_chunks)} 个片段（{mode}）"
        )
        self._prune()
        self._save()
        return added > 0

    def ingest_text(self, text: str, source: str = "inline.txt") -> bool:
        """Ingest a raw string as one or more chunks (for ephemeral RAG eval)."""
        if not (text or "").strip():
            return False
        new_chunks, new_sources = self._chunk_text(text, source)
        existing = set(self.chunks)
        added = 0
        use_vectors = _HAS_VECTOR and self._rag_mode() != "keyword"
        for chunk, src in zip(new_chunks, new_sources):
            if chunk not in existing:
                self.chunks.append(chunk)
                self.sources.append(src)
                if use_vectors:
                    try:
                        vec = self._get_model().encode(chunk)
                        self.vecs.append(vec)
                    except Exception:
                        self.vecs.append([])
                else:
                    self.vecs.append([])
                added += 1
        self._prune()
        # Ephemeral corpora: avoid writing eval docs into the default on-disk index
        return added > 0

    def ingest_directory(self, dir_path):
        """批量加载目录中所有支持的文档 (.md .py .txt .yaml .yml)"""
        if not os.path.exists(dir_path):
            print(f"[RAG] 目录不存在: {dir_path}")
            return 0

        supported = ["*.md", "*.py", "*.txt", "*.yaml", "*.yml"]
        total = 0
        for ext in supported:
            for f in sorted(glob.glob(os.path.join(dir_path, ext))):
                if self.ingest(f):
                    total += 1
        print(f"[RAG] 目录加载完成，共 {len(self.chunks)} 个片段")
        return total

    # ================================================================
    # 检索
    # ================================================================
    @staticmethod
    def _rag_mode() -> str:
        """semantic | keyword | auto（缺依赖时 keyword）"""
        return os.environ.get("REACT_AGENT_RAG_MODE", "auto").strip().lower() or "auto"

    def _keyword_query(self, question, top_k=5):
        """无向量依赖的离线检索（与 Memory 关键词策略同类）。"""
        q = (question or "").strip().lower()
        if not q or not self.chunks:
            return []
        # 中英：空白词 + 中文二元组（无空格查询也能命中）
        tokens = [t for t in q.replace("？", " ").replace("?", " ").split() if len(t) > 1]
        cjk = [c for c in q if "\u4e00" <= c <= "\u9fff"]
        for i in range(len(cjk) - 1):
            tokens.append(cjk[i] + cjk[i + 1])
        tokens = list(dict.fromkeys(tokens))  # 保序去重
        scored = []
        for i, chunk in enumerate(self.chunks):
            cl = chunk.lower()
            hit = sum(1 for t in tokens if t in cl) if tokens else 0
            if q and q in cl:
                hit += 2
            if hit > 0:
                scored.append((hit, i))
        scored.sort(key=lambda x: -x[0])
        out = []
        for hit, idx in scored[:top_k]:
            out.append({
                "content": self.chunks[idx],
                "source": self.sources[idx] if idx < len(self.sources) else "",
                "score": float(hit),
            })
        return out

    def query(self, question, top_k=5, min_score=0.25):
        """
        根据问题搜索最相关的文档片段。
        返回: [{"content": str, "source": str, "score": float}, ...]

        模式：
          - REACT_AGENT_RAG_MODE=keyword → 仅关键词
          - semantic / auto + 已装 [rag] → 向量检索，失败回退关键词
        """
        if not self.chunks:
            return []
        mode = self._rag_mode()
        force_kw = mode == "keyword" or not _HAS_VECTOR
        if force_kw:
            return self._keyword_query(question, top_k=top_k)
        try:
            if not self.vecs or len(self.vecs) != len(self.chunks):
                return self._keyword_query(question, top_k=top_k)
            q_vec = self._get_model().encode(question)
            scores = cosine_similarity([q_vec], self.vecs)[0]

            results = []
            for idx in scores.argsort()[::-1]:
                if len(results) >= top_k:
                    break
                if scores[idx] >= min_score:
                    results.append({
                        "content": self.chunks[idx],
                        "source": self.sources[idx],
                        "score": float(scores[idx]),
                    })
            return results or self._keyword_query(question, top_k=top_k)
        except Exception as e:
            print(f"[RAG] 语义检索出错，回退关键词: {e}")
            return self._keyword_query(question, top_k=top_k)
    def format_context(self, results):
        """将检索结果格式化为 LLM 可用的上下文字符串"""
        if not results:
            return ""
        parts = ["以下是从文档中检索到的相关信息：\n"]
        for i, r in enumerate(results, 1):
            parts.append(f"[{i}] 来源: {r['source']} (相关度: {r['score']:.2f})")
            parts.append(r['content'])
            parts.append("---")
        return "\n".join(parts)

    def list_sources(self):
        """列出所有已加载的文档来源"""
        seen = set()
        for src in self.sources:
            if src not in seen:
                seen.add(src)
                count = self.sources.count(src)
                print(f"  📄 {src} ({count} 个片段)")
        return list(seen)

    # ================================================================
    # 持久化
    # ================================================================
    def _save(self):
        data = {
            "chunks": self.chunks,
            "sources": self.sources,
            "vecs": [[round(float(x), 4) for x in v] for v in self.vecs],
        }
        with open(self.save_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, separators=(",", ":"))

    def _load(self):
        try:
            with open(self.save_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.chunks = data.get("chunks", [])
            self.sources = data.get("sources", [])
            self.vecs = (
                [np.array(v) for v in data.get("vecs", [])]
                if _HAS_VECTOR and np is not None
                else data.get("vecs", [])
            )
            mode = "语义" if _HAS_VECTOR else "无向量依赖"
            print(f"[RAG] 已加载 {len(self.chunks)} 个文档片段（{mode}，模型懒加载）")
        except Exception:
            self.chunks = []
            self.sources = []
            self.vecs = []

    def _prune(self):
        while len(self.chunks) > self.MAX_CHUNKS:
            self.chunks.pop(0)
            self.sources.pop(0)
            self.vecs.pop(0)

    def clear(self):
        self.chunks.clear()
        self.sources.clear()
        self.vecs.clear()
        self._save()
        print("[RAG] 已清空所有文档索引")


# ================================================================
# 模块化导出：全局实例 + Agent 工具函数 + 工具定义
# ================================================================
# Agent 只需 import + 注册，不需要了解 RAG 内部细节

RAG_INDEX = RAG()


def rag_query(query: str, top_k: int = 3) -> str:
    """
    Agent 工具函数：从本地文档库中检索与问题相关的知识。
    当用户问到产品文档、API 文档、项目知识库内容时使用。

    无 [rag] 依赖时自动走关键词检索（REACT_AGENT_RAG_MODE=keyword）。
    """
    if not RAG_INDEX.chunks:
        return (
            "[RAG] 文档库为空。可用 examples/demo_rag.py 加载 fixtures/rag_corpus，"
            "或调用 ingest / ingest_directory。"
        )
    results = RAG_INDEX.query(query, top_k=top_k)
    if not results:
        return "未在本地文档中找到相关信息"
    return RAG_INDEX.format_context(results)

RAG_TOOL_DEFINITION = {
    "type": "function",
    "function": {
        "name": "rag_query",
        "description": "从本地文档库中检索与问题相关的知识。"
                       "当用户问到产品文档、API文档、项目知识库内容时使用",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "搜索关键词或问题"
                },
                "top_k": {
                    "type": "integer",
                    "description": "返回结果数量（默认3）"
                }
            },
            "required": ["query"],
        },
    },
}
