"""public_benchmark — 公开 Agent 基准小子集（GSM8K×10 + HotpotQA×10）

用途：外部口径证据，不是全量榜。数据冻结在 ``public_benchmark_subset.json``。

评分：
  - gsm8k: 从最终回答抽取数值，与 gold 比较
  - hotpotqa: 规范化后做大小写不敏感包含匹配

模式：
  - offline: 不调 LLM，仅校验数据集 + 用内置 fixture 文本跑匹配器（CI）
  - agent: 经 react_loop 子进程（需 API Key）
"""

from __future__ import annotations

import json
import os
import re
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Optional

from react_agent.eval.execution_scorer import (
    AgentRunner,
    wilson_ci,
    _final_answer_text,
)

_EVAL_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_PUBLIC_BENCHMARK = os.path.join(_EVAL_DIR, "public_benchmark_subset.json")


def load_public_benchmark(path: Optional[str] = None) -> dict[str, Any]:
    filepath = path or DEFAULT_PUBLIC_BENCHMARK
    with open(filepath, encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict) or not isinstance(data.get("cases"), list):
        raise ValueError(f"public benchmark must be object with cases[]: {filepath}")
    return data


def normalize_text(s: str) -> str:
    s = (s or "").strip().lower()
    s = re.sub(r"\s+", " ", s)
    s = s.replace("'", "'").replace("'", "'")
    return s


def extract_gsm8k_number(text: str) -> Optional[str]:
    """Extract predicted GSM8K answer (prefer #### marker, else last number)."""
    if not text:
        return None
    m = re.search(r"####\s*([-+]?\d[\d,]*(?:\.\d+)?)", text)
    if m:
        return m.group(1).replace(",", "")
    m = re.search(
        r"FINAL\s+ANSWER\s*[:：]\s*.*?([-+]?\d[\d,]*(?:\.\d+)?)\s*$",
        text,
        re.I | re.M | re.S,
    )
    if m:
        return m.group(1).replace(",", "")
    nums = re.findall(r"[-+]?\d[\d,]*(?:\.\d+)?", text)
    if not nums:
        return None
    return nums[-1].replace(",", "")


def numbers_equal(a: str, b: str) -> bool:
    try:
        return abs(float(a) - float(b)) < 1e-6
    except ValueError:
        return str(a).strip() == str(b).strip()


def match_gold(pred_text: str, gold: str, benchmark: str) -> tuple[bool, str]:
    gold = (gold or "").strip()
    if not gold:
        return False, "empty gold"
    if benchmark == "gsm8k":
        pred = extract_gsm8k_number(pred_text)
        if pred is None:
            return False, "no numeric prediction"
        ok = numbers_equal(pred, gold.replace(",", ""))
        return ok, f"pred={pred} gold={gold}"
    p = normalize_text(pred_text)
    g = normalize_text(gold)
    if not g:
        return False, "empty gold"
    if g in p or p in g:
        return True, "contains"
    if len(g) <= 40 and all(tok in p for tok in g.split() if len(tok) > 2):
        return True, "token_cover"
    return False, f"gold {gold!r} not found in prediction"


def _prompt_for(case: dict) -> str:
    q = (case.get("question") or "").strip()
    bench = case.get("benchmark") or ""
    if bench == "gsm8k":
        return (
            "Solve this grade-school math word problem. "
            "You may use calculator or execute_python. "
            "End with FINAL ANSWER containing only the numeric result.\n\n"
            f"{q}"
        )
    return (
        "Answer this multi-hop factual question. "
        "Use web_search and/or fetch_page when needed. "
        "Give a short FINAL ANSWER with the fact only.\n\n"
        f"{q}"
    )


def _build_offline_fixtures(cases: list[dict]) -> dict[str, str]:
    """Synthetic predictions that must match gold (CI without LLM)."""
    out: dict[str, str] = {}
    for c in cases:
        cid = str(c["id"])
        gold = str(c.get("gold_answer") or "")
        if c.get("benchmark") == "gsm8k":
            out[cid] = f"Reasoning...\nFINAL ANSWER: {gold}"
        else:
            out[cid] = f"Based on sources, the answer is {gold}.\nFINAL ANSWER: {gold}"
    return out


def score_offline_case(case: dict, prediction: str) -> dict[str, Any]:
    bench = str(case.get("benchmark") or "")
    ok, reason = match_gold(prediction, str(case.get("gold_answer") or ""), bench)
    return {
        "id": case.get("id"),
        "name": case.get("name") or case.get("id"),
        "benchmark": bench,
        "tags": list(case.get("tags") or []),
        "difficulty": case.get("difficulty") or "unspecified",
        "mode": "offline",
        "passed": ok,
        "skipped": False,
        "reason": reason,
        "gold_answer": case.get("gold_answer"),
        "prediction_preview": prediction[:300],
        "tools_called": [],
        "tool_success": None,
        "has_final_answer": bool(prediction.strip()),
    }


def score_agent_case(
    case: dict,
    *,
    agent_runner: Optional[AgentRunner] = None,
) -> dict[str, Any]:
    """Run agent and score by gold answer (tools optional / reported only)."""
    import time

    from react_agent.eval.execution_scorer import _collect_tools

    cid = str(case.get("id") or "unknown")
    question = _prompt_for(case)
    if agent_runner is None:
        from react_agent.eval.runner import run_single_case

        agent_runner = run_single_case

    timeout = int(case.get("timeout") or 90)
    max_steps = case.get("max_steps")
    t0 = time.time()
    stdout, trajectory, exit_code, duration = agent_runner(
        question,
        timeout=timeout,
        max_steps=max_steps,
    )
    if not duration:
        duration = round(time.time() - t0, 3)

    text = _final_answer_text(stdout or "", trajectory)
    tools = _collect_tools(stdout or "", trajectory)
    has_answer = bool(
        (trajectory and str(trajectory.get("final_answer") or "").strip())
        or re.search(r"FINAL ANSWER:\s*\S", stdout or "", re.I)
    )
    ok, reason = match_gold(
        text, str(case.get("gold_answer") or ""), str(case.get("benchmark") or "")
    )
    timed_out = exit_code == -1
    passed = bool(ok and has_answer and not timed_out)

    return {
        "id": cid,
        "name": case.get("name") or cid,
        "benchmark": case.get("benchmark"),
        "tags": list(case.get("tags") or []),
        "difficulty": case.get("difficulty") or "unspecified",
        "mode": "agent",
        "passed": passed,
        "skipped": False,
        "duration_seconds": duration,
        "exit_code": exit_code,
        "tools_called": sorted(tools),
        "tool_success": bool(tools),
        "has_final_answer": has_answer,
        "gold_answer": case.get("gold_answer"),
        "gold_match": {"passed": ok, "reason": reason},
        "stdout_preview": (stdout or "")[:400],
        "final_answer_preview": str((trajectory or {}).get("final_answer") or "")[:300],
        "reason": (
            "timeout"
            if timed_out
            else (f"gold ok: {reason}" if passed else f"gold mismatch: {reason}")
        ),
    }


def run_public_benchmark(
    path: Optional[str] = None,
    *,
    modes: Optional[list[str]] = None,
    benchmarks: Optional[list[str]] = None,
    only_ids: Optional[set[str]] = None,
    agent_runner: Optional[AgentRunner] = None,
    limit: Optional[int] = None,
) -> dict[str, Any]:
    """Run public subset. modes: offline (default) and/or agent."""
    wanted = set(modes or ["offline"])
    bundle = load_public_benchmark(path)
    cases = list(bundle.get("cases") or [])
    if benchmarks:
        bset = set(benchmarks)
        cases = [c for c in cases if c.get("benchmark") in bset]
    if only_ids:
        cases = [c for c in cases if str(c.get("id")) in only_ids]
    if limit is not None:
        cases = cases[: int(limit)]

    results: list[dict] = []
    fixtures = _build_offline_fixtures(cases)

    for case in cases:
        if "offline" in wanted:
            results.append(score_offline_case(case, fixtures[str(case["id"])]))
        if "agent" in wanted:
            results.append(score_agent_case(case, agent_runner=agent_runner))

    total = len(results)
    passed = sum(1 for r in results if r.get("passed"))
    rate = round(100.0 * passed / total, 1) if total else 0.0

    by_bench: dict[str, dict] = defaultdict(lambda: {"passed": 0, "total": 0})
    by_mode: dict[str, dict] = defaultdict(lambda: {"passed": 0, "total": 0})
    for r in results:
        b = str(r.get("benchmark") or "unknown")
        m = str(r.get("mode") or "unknown")
        by_bench[b]["total"] += 1
        by_mode[m]["total"] += 1
        if r.get("passed"):
            by_bench[b]["passed"] += 1
            by_mode[m]["passed"] += 1

    def _rate_map(d: dict) -> dict:
        return {
            k: {
                **v,
                "pass_rate": round(100.0 * v["passed"] / v["total"], 1) if v["total"] else 0.0,
            }
            for k, v in sorted(d.items())
        }

    n_agent = sum(1 for r in results if r.get("mode") == "agent" and not r.get("skipped"))
    tool_n = sum(1 for r in results if r.get("mode") == "agent" and r.get("tools_called"))

    return {
        "report_id": f"public_bench_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "dataset": os.path.basename(path or DEFAULT_PUBLIC_BENCHMARK),
        "bundle_name": bundle.get("name"),
        "bundle_version": bundle.get("version"),
        "modes": sorted(wanted),
        "summary": {
            "total": total,
            "passed": passed,
            "failed": total - passed,
            "pass_rate": rate,
            "pass_rate_wilson_95": wilson_ci(passed, total),
            "agent_n": n_agent,
            "agent_with_tools_n": tool_n,
            "honesty": (
                "公开子集 n=20（GSM8K×10 + HotpotQA×10）；offline 只验证匹配器；"
                "agent 数字绑定模型/日期，勿当全量榜"
            ),
        },
        "by_benchmark": _rate_map(by_bench),
        "by_mode": _rate_map(by_mode),
        "license_notes": bundle.get("license_notes"),
        "results": results,
    }


def report_to_markdown(report: dict, *, title: Optional[str] = None) -> str:
    s = report.get("summary") or {}
    title = title or f"公开 Agent benchmark 子集（{report.get('report_id', '')}）"
    wilson = s.get("pass_rate_wilson_95") or {}
    lines = [
        f"# {title}",
        "",
        f"- **report_id:** `{report.get('report_id', '')}`",
        f"- **bundle:** `{report.get('bundle_name', '')}` v`{report.get('bundle_version', '')}`",
        f"- **dataset:** `{report.get('dataset', '')}`",
        f"- **modes:** {', '.join(f'`{m}`' for m in (report.get('modes') or []))}",
        f"- **通过率:** **{s.get('passed', 0)}/{s.get('total', 0)}（{s.get('pass_rate', 0)}%）**",
        f"- **Wilson 95% CI:** [{wilson.get('low', '—')}, {wilson.get('high', '—')}]%",
        f"- **说明:** {s.get('honesty', '')}",
        "",
        "## 按 benchmark",
        "",
        "| benchmark | passed | total | rate |",
        "|-----------|--------|-------|------|",
    ]
    for name, info in (report.get("by_benchmark") or {}).items():
        lines.append(
            f"| `{name}` | {info.get('passed', 0)} | {info.get('total', 0)} "
            f"| {info.get('pass_rate', 0)}% |"
        )
    lines.extend([
        "",
        "## 按 mode",
        "",
        "| mode | passed | total | rate |",
        "|------|--------|-------|------|",
    ])
    for name, info in (report.get("by_mode") or {}).items():
        lines.append(
            f"| `{name}` | {info.get('passed', 0)} | {info.get('total', 0)} "
            f"| {info.get('pass_rate', 0)}% |"
        )
    lines.extend(["", "## 明细", ""])
    for r in report.get("results") or []:
        icon = "PASS" if r.get("passed") else ("SKIP" if r.get("skipped") else "FAIL")
        lines.append(
            f"- [{icon}] `{r.get('id')}` ({r.get('benchmark')}/{r.get('mode')}): "
            f"{r.get('reason', '')}"
        )
    if report.get("license_notes"):
        lines.extend(["", "## License", "", str(report["license_notes"])])
    lines.append("")
    return "\n".join(lines)
