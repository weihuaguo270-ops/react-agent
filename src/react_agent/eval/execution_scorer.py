"""execution_scorer — Execution-based 离线任务集打分

不经过 LLM：按数据集中预置的工具调用脚本直接执行 TOOL_REGISTRY，
产出可复现的任务成功率（pass_rate）。

用法：
    from react_agent.eval.execution_scorer import run_execution_suite
    report = run_execution_suite()
"""

from __future__ import annotations

import json
import os
import re
import time
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Optional

from react_agent.tools import TOOL_REGISTRY

_EVAL_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_EXECUTION_DATASET = os.path.join(_EVAL_DIR, "execution_dataset.json")


def load_execution_dataset(path: Optional[str] = None) -> list[dict]:
    filepath = path or DEFAULT_EXECUTION_DATASET
    with open(filepath, encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, list):
        raise ValueError(f"execution dataset must be a list: {filepath}")
    return data


def _check_expectation(result: str, step: dict) -> tuple[bool, str]:
    """对照 expect_* 字段判定单步是否通过。"""
    if "expect_equals" in step:
        exp = str(step["expect_equals"])
        if result.strip() == exp:
            return True, "equals"
        return False, f"expected equals {exp!r}, got {result.strip()!r}"

    if "expect_contains" in step:
        needle = str(step["expect_contains"])
        if needle in result:
            return True, "contains"
        return False, f"missing {needle!r} in {result[:200]!r}"

    if "expect_regex" in step:
        pat = str(step["expect_regex"])
        if re.search(pat, result.strip()):
            return True, "regex"
        return False, f"regex {pat!r} not matched: {result.strip()!r}"

    # 无显式期望：工具未返回 JSON error 即算过
    low = result.lower()
    if '"error"' in low or result.startswith("[错误]") or "错误：" in result:
        return False, f"tool error-like output: {result[:200]!r}"
    return True, "no_explicit_expect"


def execute_tool_step(tool: str, arguments: dict) -> str:
    if tool not in TOOL_REGISTRY:
        return json.dumps({"error": f"未知工具: {tool}"})
    try:
        return str(TOOL_REGISTRY[tool](**(arguments or {})))
    except Exception as e:
        return json.dumps({"error": f"执行错误: {e}"})


def score_task(task: dict) -> dict[str, Any]:
    """评测单条 execution 任务。"""
    task_id = str(task.get("id") or "unknown")
    mode = task.get("mode", "offline_tools")
    if mode != "offline_tools":
        return {
            "id": task_id,
            "passed": False,
            "skipped": True,
            "reason": f"unsupported mode: {mode}",
            "steps": [],
        }

    step_results = []
    all_ok = True
    t0 = time.time()
    for i, step in enumerate(task.get("steps") or []):
        tool = step.get("tool", "")
        args = step.get("arguments") or {}
        raw = execute_tool_step(tool, args)
        ok, reason = _check_expectation(raw, step)
        step_results.append({
            "index": i + 1,
            "tool": tool,
            "arguments": args,
            "result": raw[:500],
            "passed": ok,
            "reason": reason,
        })
        if not ok:
            all_ok = False
    duration = round(time.time() - t0, 3)
    return {
        "id": task_id,
        "name": task.get("name", ""),
        "tags": list(task.get("tags") or []),
        "passed": all_ok and bool(step_results),
        "skipped": False,
        "duration_seconds": duration,
        "steps": step_results,
        "reason": "all steps ok" if all_ok and step_results else "step failure",
    }


def run_execution_suite(
    path: Optional[str] = None,
    *,
    only_ids: Optional[set[str]] = None,
) -> dict[str, Any]:
    """跑完整 execution 集，返回可归档 JSON 报告。"""
    tasks = load_execution_dataset(path)
    if only_ids:
        tasks = [t for t in tasks if str(t.get("id")) in only_ids]

    results = []
    for task in tasks:
        results.append(score_task(task))

    scored = [r for r in results if not r.get("skipped")]
    passed = sum(1 for r in scored if r["passed"])
    total = len(scored)
    rate = round(100.0 * passed / total, 1) if total else 0.0

    by_tag: dict[str, dict[str, int]] = defaultdict(lambda: {"total": 0, "passed": 0})
    for r in scored:
        for tag in r.get("tags") or ["untagged"]:
            by_tag[tag]["total"] += 1
            if r["passed"]:
                by_tag[tag]["passed"] += 1

    report = {
        "report_id": f"execution_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "dataset": os.path.basename(path or DEFAULT_EXECUTION_DATASET),
        "mode": "offline_tools",
        "summary": {
            "total": total,
            "passed": passed,
            "failed": total - passed,
            "pass_rate": rate,
            "skipped": sum(1 for r in results if r.get("skipped")),
        },
        "by_tag": {
            k: {
                **v,
                "pass_rate": round(100.0 * v["passed"] / v["total"], 1) if v["total"] else 0.0,
            }
            for k, v in sorted(by_tag.items())
        },
        "results": results,
    }
    return report


def report_to_markdown(report: dict, *, title: Optional[str] = None) -> str:
    s = report.get("summary") or {}
    title = title or f"Execution 公开快照（{report.get('report_id', 'exec')}）"
    lines = [
        f"# {title}",
        "",
        f"- **report_id:** `{report.get('report_id', '')}`",
        f"- **timestamp:** `{report.get('timestamp', '')}`",
        f"- **dataset:** `{report.get('dataset', '')}`",
        f"- **mode:** `{report.get('mode', 'offline_tools')}`（不经 LLM，直接执行工具）",
        f"- **通过率:** **{s.get('passed', 0)}/{s.get('total', 0)}（{s.get('pass_rate', 0)}%）**",
        "",
        "## 按 tag",
        "",
        "| tag | passed | total | rate |",
        "|-----|--------|-------|------|",
    ]
    for tag, info in (report.get("by_tag") or {}).items():
        lines.append(
            f"| `{tag}` | {info.get('passed', 0)} | {info.get('total', 0)} "
            f"| {info.get('pass_rate', 0)}% |"
        )
    lines.extend(["", "## 用例明细", ""])
    for r in report.get("results") or []:
        icon = "PASS" if r.get("passed") else ("SKIP" if r.get("skipped") else "FAIL")
        lines.append(
            f"- **{icon}** `{r.get('id')}` — {r.get('name', '')} "
            f"({r.get('duration_seconds', 0)}s) — {r.get('reason', '')}"
        )
    lines.extend([
        "",
        "## 诚实边界",
        "",
        "- 本套为 **工具执行验收**，不是端到端 Agent（LLM 规划）成功率",
        "- 数字绑定具体 `report_id`；改工具语义后需重跑",
        "",
    ])
    return "\n".join(lines)
