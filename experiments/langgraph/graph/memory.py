"""
记忆系统 — 语义记忆 + 自动遗忘 + 语义去重更新

核心功能：
  - add():          新增记忆（去重后追加）
  - add_or_update(): 语义去重后写入
  - query():        语义检索
  - remove()/clear(): 删除
  - _prune():       LRU 自动遗忘

注意：BGE 模型采用懒加载，首次写/查记忆时才会加载。
"""
import json
import os
import time
import numpy as np
from sklearn.metrics.pairwise import cosine_similarity


# 语义相似度阈值
EXACT_MATCH_THRESHOLD = 0.85    # 高于此值视为同一事实
CONFLICT_THRESHOLD = 0.60       # 高于此值视为主体相同，需检查是否冲突


class Memory:
    """语义记忆，支持增删查 + LRU 自动遗忘 + 语义去重更新"""

    MAX_FACTS = 100

    def __init__(self):
        _pkg_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        _repo_root = os.path.dirname(os.path.dirname(_pkg_dir))
        save_path = os.path.join(_repo_root, "memory.json")
        self.save_path = save_path
        self.facts = []
        self.vecs = []
        self.access_count = []
        self.last_access = []
        self._model = None  # 懒加载
        self._load()

    def _get_model(self):
        """首次使用时加载 BGE 模型，后续复用"""
        if self._model is None:
            from sentence_transformers import SentenceTransformer
            print("  [记忆] 加载语义模型...")
            self._model = SentenceTransformer('BAAI/bge-small-zh-v1.5')
        return self._model

    def _load(self):
        try:
            with open(self.save_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.facts = data.get("facts", [])
            self.vecs = [np.array(v) for v in data.get("vecs", [])]
            self.access_count = data.get("access_count", [0] * len(self.facts))
            self.last_access = data.get("last_access", [0] * len(self.facts))
            if self.facts:
                print(f"[记忆] 已加载 {len(self.facts)} 条记忆（模型懒加载）")
        except Exception:
            pass

    def _save(self):
        with open(self.save_path, "w", encoding="utf-8") as f:
            json.dump({
                "facts": self.facts,
                "vecs": [[round(float(x), 4) for x in v] for v in self.vecs],
                "access_count": self.access_count,
                "last_access": self.last_access,
            }, f, ensure_ascii=False, separators=(",", ":"))

    def add(self, fact: str) -> bool:
        if fact not in self.facts:
            self.facts.append(fact)
            self.vecs.append(self._get_model().encode(fact))
            self.access_count.append(0)
            self.last_access.append(0)
            self._prune()
            self._save()
            return True
        return False

    def add_or_update(self, new_fact: str) -> tuple:
        if not new_fact.strip():
            return ("skipped", "空内容")
        new_vec = self._get_model().encode(new_fact)
        if not self.facts:
            self.facts.append(new_fact)
            self.vecs.append(new_vec)
            self.access_count.append(0)
            self.last_access.append(0)
            self._save()
            return ("added", None)
        scores = cosine_similarity([new_vec], self.vecs)[0]
        best_idx = int(scores.argsort()[::-1][0])
        best_score = float(scores[best_idx])
        if best_score >= EXACT_MATCH_THRESHOLD:
            return ("skipped", f"与已有记忆重复（相似度 {best_score:.2f}）")
        if best_score >= CONFLICT_THRESHOLD:
            old_fact = self.facts[best_idx]
            self.facts[best_idx] = new_fact
            self.vecs[best_idx] = new_vec
            self.access_count[best_idx] = 0
            self.last_access[best_idx] = time.time()
            self._save()
            return ("updated", old_fact)
        self.facts.append(new_fact)
        self.vecs.append(new_vec)
        self.access_count.append(0)
        self.last_access.append(0)
        self._prune()
        self._save()
        return ("added", None)

    def query(self, question: str, top_k: int = 3) -> list:
        if not self.facts:
            return []
        try:
            q_vec = self._get_model().encode(question)
            scores = cosine_similarity([q_vec], self.vecs)[0]
            results = []
            for idx in scores.argsort()[::-1][:top_k]:
                if scores[idx] > 0.3:
                    results.append({"fact": self.facts[idx], "score": float(scores[idx])})
                    self.access_count[idx] += 1
                    self.last_access[idx] = time.time()
            if results:
                self._save()
            return results
        except Exception:
            return []

    def remove(self, fact_or_query: str) -> int:
        if fact_or_query in self.facts:
            self._remove_at(self.facts.index(fact_or_query))
            self._save()
            return 1
        for i, f in enumerate(self.facts):
            if fact_or_query in f:
                self._remove_at(i)
                self._save()
                return 1
        try:
            q_vec = self._get_model().encode(fact_or_query)
            scores = cosine_similarity([q_vec], self.vecs)[0]
            best = scores.argsort()[::-1][0]
            if scores[best] > 0.4:
                self._remove_at(best)
                self._save()
                return 1
        except Exception:
            pass
        return 0

    def _remove_at(self, idx: int):
        self.facts.pop(idx)
        self.vecs.pop(idx)
        self.access_count.pop(idx)
        self.last_access.pop(idx)

    def _prune(self):
        while len(self.facts) > self.MAX_FACTS:
            now = time.time()
            scores = []
            for i in range(len(self.facts)):
                age = now - self.last_access[i] if self.last_access[i] > 0 else 999999
                scores.append((self.access_count[i], -age, i))
            scores.sort()
            idx = scores[0][2]
            self._remove_at(idx)

    def clear(self):
        self.facts.clear()
        self.vecs.clear()
        self.access_count.clear()
        self.last_access.clear()
        self._save()


MEMORY = Memory()
