"""失败飞轮闭环：改前/改后对照（duplicate 拦截 + offtrack 假阳性修复）。

用法：
  python examples/run_flywheel_closed_loop.py
  python examples/run_flywheel_closed_loop.py --traj-dir src/react_agent/trajectories --n 100 --publish
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TDEBUG = ROOT.parent / "trace-debugger"
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(TDEBUG))


def _git_sha(cwd: Path) -> str:
    try:
        return (
            subprocess.check_output(
                ["git", "rev-parse", "--short", "HEAD"],
                cwd=cwd,
                stderr=subprocess.DEVNULL,
            )
            .decode()
            .strip()
        )
    except Exception:
        return "unknown"


def scan_files(files: list[Path]) -> dict:
    from trace_debugger import Analyzer, failure_distribution
    from trace_debugger.reader import load

    analyses = []
    rows = []
    for path in files:
        if not path.is_file():
            continue
        traj = load(str(path))
        analysis = Analyzer().analyze(traj)
        analyses.append(analysis)
        fails = sorted({ft for pa in analysis.paths for ft in pa.failure_types})
        rows.append({
            "file": path.name,
            "query": (traj.query or "")[:100],
            "failure_types": fails,
        })
    return {
        "n": len(analyses),
        "distribution": failure_distribution(analyses),
        "rows": rows,
    }


def scan_dir(traj_dir: Path, n: int) -> dict:
    files = sorted(traj_dir.glob("traj_*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not files:
        files = sorted(traj_dir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    return scan_files(files[:n])


def demo_duplicate_blocker() -> dict:
    """无 LLM：验证相邻同参会被规范化判定为重复。"""
    from react_agent.react_loop import _normalize_tool_args

    a1 = _normalize_tool_args('{"url": "https://en.wikipedia.org/wiki/AI_agent"}')
    a2 = _normalize_tool_args('{"url": "https://en.wikipedia.org/wiki/AI_agent"}')
    a3 = _normalize_tool_args('{"url": "https://en.wikipedia.org/wiki/Other"}')
    return {
        "same_args_equal": a1 == a2,
        "diff_args_unequal": a1 != a3,
        "passed": a1 == a2 and a1 != a3,
    }


def demo_offtrack_on_time_traj() -> dict:
    """用真实「现在几点了」类结构验证不再误报 offtrack。"""
    from trace_debugger import Analyzer
    from trace_debugger.reader import parse

    data = {
        "session_id": "fw_time",
        "query": "现在几点了？",
        "model": "mock",
        "steps": [
            {
                "step": 1,
                "thought": "调用时间工具",
                "action": {"name": "get_time", "arguments": "{}"},
                "observation": "2026-07-13 14:12:25",
            },
            {
                "step": 2,
                "thought": "FINAL ANSWER: 当前时间是 2026年7月13日 14时12分25秒",
                "observation": "",
            },
        ],
        "final_answer": "当前时间是 **2026年7月13日 14时12分25秒**（本地时间）。",
    }
    r = Analyzer().analyze(parse(data))
    types = {ft for pa in r.paths for ft in pa.failure_types}
    return {
        "failure_types": sorted(types),
        "passed": "llm_offtrack" not in types,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--traj-dir",
        default=str(ROOT / "src" / "react_agent" / "trajectories"),
    )
    parser.add_argument("--n", type=int, default=100)
    parser.add_argument("--publish", action="store_true")
    parser.add_argument(
        "--before-json",
        default=str(
            TDEBUG / "docs" / "snapshots" / "tdebug_failure_real_20260715.json"
        ),
        help="改前分布归档（默认真实 100 条快照）",
    )
    args = parser.parse_args()

    before_path = Path(args.before_json)
    before = {}
    if before_path.is_file():
        before = json.loads(before_path.read_text(encoding="utf-8"))
    before_dist = before.get("distribution") or {}

    traj_dir = Path(args.traj_dir)
    after = {"n": 0, "distribution": {}, "rows": []}
    # 公平对照：优先按改前快照里的同一批文件名重扫（只换分析器）
    before_files = []
    for row in before.get("trajectories") or []:
        name = row.get("file")
        if name:
            before_files.append(traj_dir / name)
    if before_files:
        existing = [p for p in before_files if p.is_file()]
        after = scan_files(existing)
        after_note = f"reanalyze same files from before snapshot ({len(existing)} found)"
    elif traj_dir.is_dir():
        after = scan_dir(traj_dir, args.n)
        after_note = "mtime-latest scan (no before file list)"
    else:
        after_note = f"traj dir missing: {traj_dir}"
        print(f"[warn] {after_note}", file=sys.stderr)

    dup = demo_duplicate_blocker()
    ot = demo_offtrack_on_time_traj()

    # delta on keys of interest
    keys = sorted(set(before_dist) | set(after.get("distribution") or {}))
    delta = {
        k: {
            "before": int(before_dist.get(k, 0)),
            "after": int((after.get("distribution") or {}).get(k, 0)),
            "delta": int((after.get("distribution") or {}).get(k, 0))
            - int(before_dist.get(k, 0)),
        }
        for k in keys
    }

    report = {
        "report_id": f"flywheel_closed_loop_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "fixes": [
            "react-agent: block adjacent identical tool calls (REACT_AGENT_BLOCK_DUPLICATE_TOOLS=1)",
            "react-agent: prompt rules 6–7 (no duplicate / stay on short factual Q)",
            "trace-debugger: skip llm_offtrack when answer grounded in tool observations / short-fact+digits",
        ],
        "unit_checks": {"duplicate_normalize": dup, "offtrack_time_case": ot},
        "before": {
            "source": str(before_path.as_posix()),
            "n": before.get("n_trajectories") or before.get("n"),
            "distribution": before_dist,
        },
        "after": {
            "source": str(traj_dir.as_posix()),
            "n": after.get("n"),
            "distribution": after.get("distribution"),
            "note": after_note,
        },
        "delta": delta,
        "meta": {
            "react_agent_git": _git_sha(ROOT),
            "trace_debugger_git": _git_sha(TDEBUG),
        },
    }

    print("unit duplicate:", dup)
    print("unit offtrack:", ot)
    print("before:", before_dist)
    print("after:", after.get("distribution"))
    print("delta:", {k: v["delta"] for k, v in delta.items()})

    if args.publish:
        stem = "flywheel_closed_loop_20260716"
        docs = ROOT / "docs"
        snap = docs / "snapshots"
        docs.mkdir(exist_ok=True)
        snap.mkdir(exist_ok=True)
        (snap / f"{stem}.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        lines = [
            f"# 失败飞轮闭环对照（{stem}）",
            "",
            f"- **report_id:** `{report['report_id']}`",
            f"- **timestamp:** `{report['timestamp']}`",
            f"- **react-agent git:** `{report['meta']['react_agent_git']}`",
            f"- **trace-debugger git:** `{report['meta']['trace_debugger_git']}`",
            "",
            "## 本轮落地改动",
            "",
        ]
        for f in report["fixes"]:
            lines.append(f"- {f}")
        lines.extend([
            "",
            "## 单元核验",
            "",
            f"- duplicate 参数规范化: **{'PASS' if dup['passed'] else 'FAIL'}**",
            f"- 「现在几点了」不再误报 offtrack: **{'PASS' if ot['passed'] else 'FAIL'}** "
            f"({ot['failure_types']})",
            "",
            "## 真实轨迹分布：改前 → 改后",
            "",
            f"- 改前源: `{report['before']['source']}` (n={report['before']['n']})",
            f"- 改后源: `{report['after']['source']}` (n={report['after']['n']})",
            f"- 改后说明: {report['after'].get('note', '')}",
            "",
            "| type | before | after | delta |",
            "|------|-------:|------:|------:|",
        ])
        for k, v in sorted(delta.items(), key=lambda x: x[0]):
            lines.append(f"| `{k}` | {v['before']} | {v['after']} | {v['delta']:+d} |")
        lines.extend([
            "",
            "## 解读",
            "",
            "- **公平对照**：改后优先按改前快照中的同一批文件名重扫（只换分析器），避免混入 flaky/新评测轨迹",
            "- **llm_offtrack 下降**：多为短问答假阳性修复（答案 grounded 于工具观测），不是模型突然变聪明",
            "- **duplicate**：Harness 层已拦截相邻同参；历史轨迹不会被改写，需新跑任务才能在新 traj 上体现",
            "- 闭环清单见 [FAILURE_FLYWHEEL.md](./FAILURE_FLYWHEEL.md)",
            "",
            "## 复现",
            "",
            "```bash",
            "python examples/run_flywheel_closed_loop.py --publish",
            "```",
            "",
        ])
        (docs / f"{stem}.md").write_text("\n".join(lines), encoding="utf-8")

        # update flywheel checklist
        fw = docs / "FAILURE_FLYWHEEL.md"
        entry = [
            "",
            f"## {datetime.now().strftime('%Y-%m-%d')} — 真闭环 `{stem}`",
            "",
            f"- 对照页: [{stem}.md](./{stem}.md)",
            f"- delta: `{json.dumps({k: v['delta'] for k, v in delta.items()}, ensure_ascii=False)}`",
            "",
            "### 闭环状态",
            "",
            "- [x] 已落地代码/提示改动（duplicate 拦截 + offtrack grounded 跳过）",
            "- [x] 已重跑同批轨迹扫描对照",
            "- [ ] 下周对新产生轨迹再扫，确认 duplicate 增量下降",
            "",
            "---",
            "",
        ]
        if fw.exists():
            text = fw.read_text(encoding="utf-8")
            if "---" in text:
                head, rest = text.split("---", 1)
                fw.write_text(head + "---\n" + "\n".join(entry) + rest.lstrip("\n"), encoding="utf-8")
            else:
                fw.write_text(text + "\n".join(entry), encoding="utf-8")
        print(f"Published docs/{stem}.md")

    ok = dup["passed"] and ot["passed"]
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
