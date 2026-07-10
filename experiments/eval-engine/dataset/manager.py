"""manager — Golden Dataset 管理

Golden Dataset 是评估的核心基础设施——一组经过人工验证的、
覆盖典型场景的测试用例。每次修改 prompt/tool/model 后，
都在这个数据集上重新跑 eval，确保质量没有回退。

数据来源：
  1. 手动编写（覆盖常见场景）
  2. 从生产日志中提取真实用户问题 + 人工标注
  3. 从失败的回归用例中提取（每次失败→新增一条回归用例）

数据格式：
    golden.json:
    [
        {
            "id": "rag_001",
            "category": "rag",
            "query": "项目的 RAG 模块在哪个文件？",
            "expected_tools": ["rag_query", "search_files"],
            "must_contain": ["rag.py"],
            "max_steps": 5,
            "tags": ["rag", "local"],
            "human_score": 4.5,       # 人工标注的期望质量
            "human_rubrics": [...],    # 人工标注的评分标准
        },
        ...
    ]
"""

from __future__ import annotations
import json
import os
import random
from typing import Any, Optional


DEFAULT_DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")


class GoldenDataset:
    """Golden Dataset 管理器

    用法：
        dataset = GoldenDataset()
        dataset.load()
        cases = dataset.filter(category="rag")
        dataset.add_case(new_case)
    """

    def __init__(self, data_dir: Optional[str] = None):
        self.data_dir = data_dir or DEFAULT_DATA_DIR
        self.cases: list[dict] = []

    def load(self, filename: str = "golden.json") -> list[dict]:
        """加载数据集"""
        path = os.path.join(self.data_dir, filename)
        if not os.path.exists(path):
            print(f"[GoldenDataset] 数据集不存在: {path}")
            self.cases = []
            return []
        with open(path, encoding="utf-8") as f:
            self.cases = json.load(f)
        print(f"[GoldenDataset] 已加载 {len(self.cases)} 条用例")
        return self.cases

    def save(self, filename: str = "golden.json") -> str:
        """保存数据集"""
        os.makedirs(self.data_dir, exist_ok=True)
        path = os.path.join(self.data_dir, filename)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.cases, f, ensure_ascii=False, indent=2)
        return path

    def filter(
        self,
        category: Optional[str] = None,
        tag: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> list[dict]:
        """按条件筛选用例"""
        result = self.cases
        if category:
            result = [c for c in result if c.get("category") == category]
        if tag:
            result = [c for c in result if tag in c.get("tags", [])]
        if limit:
            result = result[:limit]
        return result

    def add_case(self, case: dict) -> None:
        """新增用例（自动去重）"""
        # 同 id 覆盖
        for i, c in enumerate(self.cases):
            if c.get("id") == case.get("id"):
                self.cases[i] = case
                return
        self.cases.append(case)

    def add_regression_case(
        self,
        query: str,
        category: str,
        failure_reason: str,
    ) -> dict:
        """从失败中新增回归用例"""
        case_id = f"reg_{len(self.cases) + 1:03d}"
        case = {
            "id": case_id,
            "category": category,
            "query": query,
            "expected_tools": [],
            "must_contain": [],
            "max_steps": 10,
            "tags": ["regression", category],
            "regression_from": failure_reason,
            "human_score": None,  # 待人工标注
        }
        self.cases.append(case)
        return case

    def random_subset(self, n: int) -> list[dict]:
        """随机抽取 n 条用例（快速测试用）"""
        if n >= len(self.cases):
            return list(self.cases)
        return random.sample(self.cases, n)

    @property
    def categories(self) -> list[str]:
        """返回所有分类"""
        cats = set(c.get("category", "unknown") for c in self.cases)
        return sorted(cats)

    @property
    def stats(self) -> dict[str, Any]:
        """数据集统计"""
        return {
            "total": len(self.cases),
            "categories": self.categories,
            "by_category": {
                cat: sum(1 for c in self.cases if c.get("category") == cat)
                for cat in self.categories
            },
            "tagged_regression": sum(
                1 for c in self.cases if "regression" in c.get("tags", [])
            ),
            "human_annotated": sum(
                1 for c in self.cases if c.get("human_score") is not None
            ),
        }
