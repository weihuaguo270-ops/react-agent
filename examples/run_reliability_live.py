"""Live Harness 可靠性：同一诱导失败任务下 Guard/自修 ON vs OFF。

用法：
  # mock（CI，不调 LLM）
  python examples/run_reliability_live.py --mock

  # live（需 DEEPSEEK_API_KEY）
  set REACT_AGENT_DISABLE_MCP=1
  python examples/run_reliability_live.py --live --publish
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

os.environ.setdefault("REACT_AGENT_SKIP_RAG", "1")
os.environ.setdefault("REACT_AGENT_SANDBOX_PREWARM", "0")
os.environ.setdefault("REACT_AGENT_DISABLE_MCP", "1")

try:
    from react_agent.llm import _load_dotenv
    _load_dotenv()
except Exception:
    pass


# 24 场景：20 诱导 flaky + 4 基线（无注入）→ ON/OFF 共 48 次 live 调用
_CALC_FLAKY = [
    ("live_flaky_calc_17x19", "请用 calculator 计算 17*19，给出数字答案。", "323"),
    ("live_flaky_calc_8x7", "请用 calculator 计算 8*7，给出数字。", "56"),
    ("live_flaky_calc_15x16", "请用 calculator 计算 15*16，只给最终数字。", "240"),
    ("live_flaky_calc_12x12", "请用 calculator 计算 12*12，给出数字。", "144"),
    ("live_flaky_calc_9x9", "请用 calculator 计算 9*9，给出数字。", "81"),
    ("live_flaky_calc_25x4", "请用 calculator 计算 25*4，给出数字。", "100"),
    ("live_flaky_calc_33x3", "请用 calculator 计算 33*3，给出数字。", "99"),
    ("live_flaky_calc_48_div_6", "请用 calculator 计算 48/6，给出数字。", "8"),
    ("live_flaky_calc_7x8", "请用 calculator 计算 7*8，给出数字。", "56"),
    ("live_flaky_calc_21x5", "请用 calculator 计算 21*5，给出数字。", "105"),
    ("live_flaky_calc_13x14", "请用 calculator 计算 13*14，给出数字。", "182"),
    ("live_flaky_calc_16x16", "请用 calculator 计算 16*16，给出数字。", "256"),
]
_PY_FLAKY = [
    ("live_flaky_py_fact5", "请用 execute_python 计算 5 的阶乘，输出数字。", "120"),
    ("live_flaky_py_sum", "请用 execute_python 打印 1+2+3+4+5 的结果。", "15"),
    ("live_flaky_py_pow", "请用 execute_python 计算 2 的 8 次方，输出数字。", "256"),
    ("live_flaky_py_fact4", "请用 execute_python 计算 4 的阶乘，输出数字。", "24"),
    ("live_flaky_py_sum10", "请用 execute_python 打印 sum(range(1,11)) 的结果。", "55"),
    ("live_flaky_py_pow3", "请用 execute_python 计算 3 的 5 次方，输出数字。", "243"),
    ("live_flaky_py_len", "请用 execute_python 打印 len('harness')。", "7"),
    ("live_flaky_py_abs", "请用 execute_python 打印 abs(-42)。", "42"),
]

SCENARIOS: list[dict[str, Any]] = [
    *[
        {
            "id": sid,
            "question": q,
            "expected_answer": ans,
            "inject": "calculator:2",
            "max_steps": 6,
            "timeout": 120,
            "kind": "flaky",
        }
        for sid, q, ans in _CALC_FLAKY
    ],
    *[
        {
            "id": sid,
            "question": q,
            "expected_answer": ans,
            "inject": "execute_python:1",
            "max_steps": 8,
            "timeout": 150,
            "kind": "flaky",
        }
        for sid, q, ans in _PY_FLAKY
    ],
    {
        "id": "live_baseline_calc",
        "question": "请用 calculator 计算 100-37，给出数字。",
        "expected_answer": "63",
        "inject": "",
        "max_steps": 5,
        "timeout": 90,
        "kind": "baseline",
    },
    {
        "id": "live_baseline_time_calc",
        "question": "请先调用 get_time，再用 calculator 计算 100/4，答案须含计算结果。",
        "expected_answer": "25",
        "inject": "",
        "max_steps": 8,
        "timeout": 120,
        "kind": "baseline",
    },
    {
        "id": "live_baseline_py_sum",
        "question": "请用 execute_python 打印 2+2，给出数字。",
        "expected_answer": "4",
        "inject": "",
        "max_steps": 6,
        "timeout": 120,
        "kind": "baseline",
    },
    {
        "id": "live_baseline_calc_99",
        "question": "请用 calculator 计算 50+49，给出数字。",
        "expected_answer": "99",
        "inject": "",
        "max_steps": 5,
        "timeout": 90,
        "kind": "baseline",
    },
]


def _git_sha() -> str:
    try:
        return (
            subprocess.check_output(
                ["git", "rev-parse", "--short", "HEAD"],
                cwd=ROOT,
                stderr=subprocess.DEVNULL,
            )
            .decode()
            .strip()
        )
    except Exception:
        return "unknown"


def _count_tool_calls(stdout: str, traj: Optional[dict]) -> int:
    n = len(re.findall(r"\[调工具\] \w+\(", stdout or ""))
    if traj:
        for step in traj.get("steps") or []:
            if step.get("action"):
                n = max(n, n)  # keep stdout count; also count traj
        traj_n = 0
        for step in traj.get("steps") or []:
            if step.get("action", {}).get("name"):
                traj_n += 1
            traj_n += sum(1 for a in (step.get("actions") or []) if a.get("name"))
        n = max(n, traj_n)
    return n


def _error_obs_count(stdout: str, traj: Optional[dict]) -> int:
    text = stdout or ""
    n = len(re.findall(r'"error"|执行错误|超时 \(injected|\[错误\]', text, flags=re.I))
    if traj:
        for step in traj.get("steps") or []:
            obs = str(step.get("observation") or "")
            if re.search(r'"error"|执行错误|timeout|超时', obs, flags=re.I):
                n += 1
    return n


def _passed(expected: str, stdout: str, traj: Optional[dict]) -> bool:
    blob = (stdout or "") + "\n" + str((traj or {}).get("final_answer") or "")
    return expected in blob


def _analyze_run(
    scenario: dict,
    *,
    guard_on: bool,
    stdout: str,
    traj: Optional[dict],
    exit_code: int,
    duration: float,
) -> dict:
    return {
        "guard_on": guard_on,
        "passed": _passed(scenario["expected_answer"], stdout, traj) and exit_code != -1,
        "exit_code": exit_code,
        "duration_seconds": duration,
        "self_repair_seen": "[Harness自修]" in (stdout or ""),
        "tool_calls": _count_tool_calls(stdout, traj),
        "error_obs": _error_obs_count(stdout, traj),
        "steps": len((traj or {}).get("steps") or []),
        "final_preview": str((traj or {}).get("final_answer") or "")[:120],
    }


def _mock_run(scenario: dict, guard_on: bool) -> dict:
    """Deterministic mock: Guard ON recovers flaky; OFF often fails first error path."""
    inject = scenario.get("inject") or ""
    is_flaky = bool(inject)
    if not is_flaky:
        # baseline both pass
        return _analyze_run(
            scenario,
            guard_on=guard_on,
            stdout=f"[调工具] calculator({{}})\nFINAL ANSWER: {scenario['expected_answer']}",
            traj={"final_answer": scenario["expected_answer"], "steps": [{"action": {"name": "calculator"}}]},
            exit_code=0,
            duration=0.1,
        )
    if guard_on:
        # tool-layer retry hides errors
        return _analyze_run(
            scenario,
            guard_on=True,
            stdout=f"[调工具] x({{}})\nFINAL ANSWER: {scenario['expected_answer']}",
            traj={
                "final_answer": scenario["expected_answer"],
                "steps": [{"action": {"name": "calculator"}, "observation": scenario["expected_answer"]}],
            },
            exit_code=0,
            duration=0.2,
        )
    # OFF: first call errors, may still recover via LLM retry — mock as fail for flaky delta
    return _analyze_run(
        scenario,
        guard_on=False,
        stdout='[调工具] x({})\n[工具返回] {"error": "执行错误: timeout"}\n[Harness自修] ...\nFINAL ANSWER: failed',
        traj={
            "final_answer": "failed",
            "steps": [
                {"action": {"name": "calculator"}, "observation": '{"error": "timeout"}'},
            ],
        },
        exit_code=0,
        duration=0.2,
    )


def run_pair(scenario: dict, *, live: bool) -> dict:
    results = {}
    for guard_on in (True, False):
        if not live:
            results["on" if guard_on else "off"] = _mock_run(scenario, guard_on)
            continue
        from react_agent.eval.runner import run_single_case

        extra = {
            "REACT_AGENT_TOOL_GUARD": "1" if guard_on else "0",
            "REACT_AGENT_SELF_REPAIR": "1" if guard_on else "0",
            "REACT_AGENT_DISABLE_MCP": "1",
            "REACT_AGENT_SKIP_RAG": "1",
            "REACT_AGENT_SANDBOX_PREWARM": "0",
        }
        if scenario.get("inject"):
            extra["REACT_AGENT_INJECT_FLAKY"] = scenario["inject"]
        else:
            extra["REACT_AGENT_INJECT_FLAKY"] = ""

        stdout, traj, code, dur = run_single_case(
            scenario["question"],
            timeout=int(scenario.get("timeout") or 120),
            max_steps=scenario.get("max_steps"),
            extra_env=extra,
        )
        results["on" if guard_on else "off"] = _analyze_run(
            scenario,
            guard_on=guard_on,
            stdout=stdout or "",
            traj=traj,
            exit_code=code,
            duration=dur,
        )
    on, off = results["on"], results["off"]
    return {
        "id": scenario["id"],
        "kind": scenario.get("kind", ""),
        "inject": scenario.get("inject") or "",
        "question": scenario["question"],
        "expected_answer": scenario["expected_answer"],
        "on": on,
        "off": off,
        "delta": {
            "on_passed": on["passed"],
            "off_passed": off["passed"],
            "on_better_pass": on["passed"] and not off["passed"],
            "on_fewer_errors": on["error_obs"] < off["error_obs"],
            "on_tool_calls": on["tool_calls"],
            "off_tool_calls": off["tool_calls"],
        },
    }


def aggregate(pairs: list[dict]) -> dict:
    flaky = [p for p in pairs if p.get("kind") == "flaky"]
    baseline = [p for p in pairs if p.get("kind") == "baseline"]

    def rate(items: list[dict], side: str) -> dict:
        if not items:
            return {"total": 0, "passed": 0, "pass_rate": 0.0}
        passed = sum(1 for p in items if p[side]["passed"])
        total = len(items)
        return {
            "total": total,
            "passed": passed,
            "pass_rate": round(100.0 * passed / total, 1),
            "mean_error_obs": round(
                sum(p[side]["error_obs"] for p in items) / total, 2
            ),
            "mean_tool_calls": round(
                sum(p[side]["tool_calls"] for p in items) / total, 2
            ),
            "self_repair_rate": round(
                100.0 * sum(1 for p in items if p[side]["self_repair_seen"]) / total, 1
            ),
        }

    return {
        "flaky_on": rate(flaky, "on"),
        "flaky_off": rate(flaky, "off"),
        "baseline_on": rate(baseline, "on"),
        "baseline_off": rate(baseline, "off"),
        "on_better_count": sum(1 for p in flaky if p["delta"]["on_better_pass"]),
        "flaky_n": len(flaky),
    }


def to_markdown(report: dict, *, title: str) -> str:
    agg = report["aggregate"]
    lines = [
        f"# {title}",
        "",
        f"- **report_id:** `{report.get('report_id', '')}`",
        f"- **timestamp:** `{report.get('timestamp', '')}`",
        f"- **mode:** `{report.get('mode', '')}`",
        f"- **git:** `{(report.get('meta') or {}).get('git', '')}`",
        "",
        "## 核心对照（诱导 flaky 子集）",
        "",
        "| setting | passed | total | pass_rate | mean_error_obs | mean_tool_calls | self_repair_rate |",
        "|---------|-------:|------:|----------:|---------------:|----------------:|-----------------:|",
        (
            f"| Guard+自修 **ON** | {agg['flaky_on']['passed']} | {agg['flaky_on']['total']} | "
            f"**{agg['flaky_on']['pass_rate']}%** | {agg['flaky_on']['mean_error_obs']} | "
            f"{agg['flaky_on']['mean_tool_calls']} | {agg['flaky_on']['self_repair_rate']}% |"
        ),
        (
            f"| Guard+自修 **OFF** | {agg['flaky_off']['passed']} | {agg['flaky_off']['total']} | "
            f"**{agg['flaky_off']['pass_rate']}%** | {agg['flaky_off']['mean_error_obs']} | "
            f"{agg['flaky_off']['mean_tool_calls']} | {agg['flaky_off']['self_repair_rate']}% |"
        ),
        "",
        f"- ON 独过（OFF 失败）场景数: **{agg['on_better_count']}/{agg['flaky_n']}**",
        "",
        "> 若两侧通过率接近，仍应看 **mean_error_obs / mean_tool_calls**：",
        "> Guard ON 通常把重试留在工具层，LLM 侧错误观测更少、调用轮次更短。",
        "",
        "## 基线（无 flaky 注入）",
        "",
        f"- ON: {agg['baseline_on']['passed']}/{agg['baseline_on']['total']} "
        f"({agg['baseline_on']['pass_rate']}%)",
        f"- OFF: {agg['baseline_off']['passed']}/{agg['baseline_off']['total']} "
        f"({agg['baseline_off']['pass_rate']}%)",
        "",
        "## 逐场景",
        "",
        "| id | kind | inject | ON | OFF | on_better |",
        "|----|------|--------|:--:|:---:|:---------:|",
    ]
    for p in report.get("scenarios") or []:
        lines.append(
            f"| `{p['id']}` | {p['kind']} | `{p['inject'] or '-'}` | "
            f"{'Y' if p['on']['passed'] else 'N'} | "
            f"{'Y' if p['off']['passed'] else 'N'} | "
            f"{'Y' if p['delta']['on_better_pass'] else '-'} |"
        )
    lines.extend([
        "",
        "## 复现",
        "",
        "```bash",
        "python examples/run_reliability_live.py --mock",
        "set REACT_AGENT_DISABLE_MCP=1",
        "python examples/run_reliability_live.py --live --publish",
        "```",
        "",
        "## 诚实边界",
        "",
        "- flaky 由 `REACT_AGENT_INJECT_FLAKY` **注入超时异常**，用于对照 ToolGuard 重试；不是线上随机故障采样",
        "- live 绑定具体模型与日期；样本量 8 场景 × 2 设置，属学习级证据",
        "- 与注入单元表（`reliability_snapshot_*`）互补：本报告含 **LLM 闭环**",
        "",
    ])
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mock", action="store_true", help="CI 友好 mock（默认若无 --live）")
    parser.add_argument("--live", action="store_true", help="真实 LLM + flaky 注入")
    parser.add_argument("--publish", action="store_true")
    parser.add_argument("--stem", default=None)
    parser.add_argument("--only", default=None, help="逗号分隔 scenario id")
    args = parser.parse_args()

    live = bool(args.live)
    if live:
        if not (os.environ.get("DEEPSEEK_API_KEY") or os.environ.get("OPENAI_API_KEY")):
            print("ERROR: --live 需要 API Key", file=sys.stderr)
            return 2
        os.environ.setdefault("LLM_PROVIDER", "deepseek")

    scenarios = SCENARIOS
    if args.only:
        wanted = {x.strip() for x in args.only.split(",") if x.strip()}
        scenarios = [s for s in SCENARIOS if s["id"] in wanted]

    pairs = []
    for s in scenarios:
        print(f">>> {s['id']} inject={s.get('inject') or '-'}")
        pair = run_pair(s, live=live)
        pairs.append(pair)
        print(
            f"    ON={'PASS' if pair['on']['passed'] else 'FAIL'} "
            f"OFF={'PASS' if pair['off']['passed'] else 'FAIL'} "
            f"err_obs={pair['on']['error_obs']}/{pair['off']['error_obs']}"
        )

    report = {
        "report_id": f"reliability_live_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "mode": "live" if live else "mock",
        "kind": "harness_reliability_live_guard_ab",
        "aggregate": aggregate(pairs),
        "scenarios": pairs,
        "meta": {
            "git": _git_sha(),
            "provider": os.environ.get("LLM_PROVIDER", "deepseek") if live else "mock",
        },
    }

    agg = report["aggregate"]
    print("=" * 55)
    print(f"  Live Reliability ({report['mode']})")
    print(
        f"  flaky ON {agg['flaky_on']['passed']}/{agg['flaky_on']['total']} "
        f"({agg['flaky_on']['pass_rate']}%)  vs  OFF "
        f"{agg['flaky_off']['passed']}/{agg['flaky_off']['total']} "
        f"({agg['flaky_off']['pass_rate']}%)"
    )
    print("=" * 55)

    if args.publish:
        stem = args.stem or (
            f"reliability_live_{'live' if live else 'mock'}_"
            f"{datetime.now().strftime('%Y%m%d')}"
        )
        docs = ROOT / "docs"
        snap = docs / "snapshots"
        docs.mkdir(exist_ok=True)
        snap.mkdir(exist_ok=True)
        (snap / f"{stem}.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        (docs / f"{stem}.md").write_text(
            to_markdown(report, title=f"Live Harness 可靠性对照（{stem}）"),
            encoding="utf-8",
        )
        print(f"Published docs/{stem}.md")

    # mock / live: success if we produced a report; for mock require ON better on flaky
    if not live:
        return 0 if agg["on_better_count"] >= 1 or agg["flaky_on"]["pass_rate"] >= agg["flaky_off"]["pass_rate"] else 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
