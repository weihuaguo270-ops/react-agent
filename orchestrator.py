
"""
Orchestrator — 独立的多 Agent 协作模块
=======================================
Orchestrator-Worker 模式：
1. plan()       — 拆解任务（LLM）
2. run_worker() — 执行单个子任务
3. synthesize() — 汇总结果
4. execute()    — 一站式调用
"""

import json
import urllib.request
from urllib.error import URLError
import sys
import os

# 确保能找到同目录的模块
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


class Orchestrator:
    def __init__(self, call_llm_func, react_loop_func):
        self.tasks = []
        self.results = []
        self.call_llm = call_llm_func
        self.react_loop = react_loop_func

    def plan(self, user_query):
        """Step 1: LLM 拆解任务"""
        prompt = (
            "将以下请求拆成独立子任务。要求：\n"
            "- 每个子任务一句话，只做一件事\n"
            "- 每行一个子任务，不要编号，不要标题\n"
            "- 不要解释，直接输出任务\n\n"
            "例子：\n"
            "请求: 现在纽约几点？同时看看mcp_client.py大小\n"
            "输出:\n"
            "查询纽约的当前时间\n"
            f"查看mcp_client.py的文件大小\n\n"
            f"请求: {user_query}\n"
            "输出:"
        )
        msg = self.call_llm([
            {"role": "system", "content": "你是一个任务分解助手。"},
            {"role": "user", "content": prompt},
        ])
        self.tasks = [t.strip() for t in (msg.get("content", "") or "").split("\n") if t.strip()]
        print(f"\n[Orchestrator] 拆分为 {len(self.tasks)} 个子任务:")
        for i, t in enumerate(self.tasks, 1):
            print(f"  {i}. {t}")
        return self.tasks

    def run_worker(self, task):
        """Step 2: 执行一个子任务"""
        print(f"\n{'='*50}")
        print(f"[Worker] {task}")
        print(f"{'='*50}")
        return self.react_loop(task)

    def synthesize(self):
        """Step 3: 汇总结果"""
        if len(self.results) == 1:
            final = self.results[0]
        elif not self.results:
            final = "没有可汇总的结果"
        else:
            parts = []
            for i, r in enumerate(self.results, 1):
                parts.append(f"-- 结果{i} --\n{r}")
            final = "\n\n".join(parts)

        print(f"\n{'='*50}")
        print("[汇总结果]")
        print(final)
        return final

    def execute(self, user_query):
        """一站式执行"""
        self.plan(user_query)
        self.results = []
        for task in self.tasks:
            result = self.run_worker(task)
            self.results.append(f"[任务] {task}\n{result}")
        return self.synthesize()


if __name__ == "__main__":
    print("Orchestrator 模块 — 在 react_loop.py 中使用:")
    print("  from orchestrator import Orchestrator")
    print("  o = Orchestrator(call_llm, react_loop)")
    print("  o.execute('现在纽约几点？同时看看文件大小')")
