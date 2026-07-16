"""失败归因飞轮：扫描 → 归档周报 → 追加闭环条目。

用法：
  # 演示样例（CI）
  python examples/run_failure_flywheel.py --fixture

  # 真实本地轨迹
  python examples/run_failure_flywheel.py --dir src/react_agent/trajectories --n 50 --publish
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TDEBUG_ROOT = ROOT.parent / "trace-debugger"


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


def _run_tdebug_publish(traj_dir: Path, n: int, stem: str, out_dir: Path) -> dict:
    script = TDEBUG_ROOT / "examples" / "publish_failure_snapshot.py"
    if not script.is_file():
        raise FileNotFoundError(f"missing {script}; clone/install trace-debugger sibling")
    cmd = [
        sys.executable,
        str(script),
        "--dir",
        str(traj_dir),
        "--n",
        str(n),
        "--stem",
        stem,
        "--out-dir",
        str(out_dir),
    ]
    subprocess.check_call(cmd, cwd=str(TDEBUG_ROOT))
    snap = out_dir / "snapshots" / f"{stem}.json"
    return json.loads(snap.read_text(encoding="utf-8"))


def _suggest_actions(dist: dict) -> list[str]:
    actions = []
    if dist.get("tool_error", 0) > 0:
        actions.append(
            "tool_error → 开/核验 ToolGuard 重试；对高频失败工具加超时与自修提示"
        )
    if dist.get("duplicate", 0) > 0:
        actions.append(
            "duplicate → 加强自修文案「勿重复相同失败调用」；限制同参重试次数"
        )
    if dist.get("llm_offtrack", 0) > 0:
        actions.append(
            "llm_offtrack → 收紧 system prompt / 增加 must_contain 验收；扩 execution hard 题"
        )
    if dist.get("no_answer", 0) > 0:
        actions.append(
            "no_answer → 检查 max_steps / FINAL ANSWER 引导；评测侧标记超时"
        )
    if dist.get("context_overflow", 0) > 0:
        actions.append(
            "context_overflow → 启用上下文压缩策略；降低 traj 写入冗余"
        )
    if not actions:
        actions.append("本周分布较干净 → 维持扫描节奏，扩难任务观察回归")
    return actions


def append_flywheel(
    flywheel_path: Path,
    *,
    stem: str,
    report: dict,
    source: str,
) -> None:
    dist = report.get("distribution") or {}
    actions = _suggest_actions(dist)
    date = datetime.now().strftime("%Y-%m-%d")
    block = [
        f"## {date} — `{stem}`",
        "",
        f"- **source:** `{source}`",
        f"- **n:** {report.get('n_trajectories', 0)}",
        f"- **git (react-agent):** `{_git_sha()}`",
        f"- **distribution:** `{json.dumps(dist, ensure_ascii=False)}`",
        "",
        "### 观察 → 假设动作 → 下次度量",
        "",
    ]
    for i, a in enumerate(actions, 1):
        block.append(f"{i}. {a}")
    block.extend([
        "",
        "### 闭环状态",
        "",
        "- [ ] 已落地代码/提示改动",
        "- [ ] 已重跑 execution 或 reliability 相关子集",
        "- [ ] 下周扫描对比本分布是否下降",
        "",
        "---",
        "",
    ])

    if not flywheel_path.exists():
        header = [
            "# 失败归因飞轮（Failure → Fix → Retest）",
            "",
            "本页由 `examples/run_failure_flywheel.py` 追加。每次扫描后记录假设动作，",
            "并在下一周期勾选是否完成改动与复测。",
            "",
            "---",
            "",
        ]
        flywheel_path.write_text("\n".join(header + block), encoding="utf-8")
    else:
        prev = flywheel_path.read_text(encoding="utf-8")
        # prepend new entry after title block
        parts = prev.split("---", 1)
        if len(parts) == 2:
            new = parts[0] + "---\n\n" + "\n".join(block) + parts[1].lstrip("\n")
        else:
            new = prev + "\n" + "\n".join(block)
        flywheel_path.write_text(new, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixture", action="store_true", help="用 tdebug failure_bundle")
    parser.add_argument("--dir", default=None, help="轨迹目录")
    parser.add_argument("--n", type=int, default=50)
    parser.add_argument("--publish", action="store_true", help="写入 react-agent/docs 飞轮")
    parser.add_argument("--stem", default=None)
    args = parser.parse_args()

    if args.fixture:
        traj_dir = TDEBUG_ROOT / "examples" / "failure_bundle"
        out_dir = TDEBUG_ROOT / "docs"
    else:
        traj_dir = Path(args.dir) if args.dir else (
            ROOT / "src" / "react_agent" / "trajectories"
        )
        out_dir = TDEBUG_ROOT / "docs"

    if not traj_dir.is_dir():
        print(f"轨迹目录不存在: {traj_dir}", file=sys.stderr)
        return 1

    stem = args.stem or f"tdebug_failure_flywheel_{datetime.now().strftime('%Y%m%d')}"
    report = _run_tdebug_publish(traj_dir, args.n, stem, out_dir)
    print("distribution:", report.get("distribution"))

    if args.publish or args.fixture:
        docs = ROOT / "docs"
        docs.mkdir(exist_ok=True)
        # mirror summary json
        snap = docs / "snapshots"
        snap.mkdir(exist_ok=True)
        (snap / f"{stem}.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        append_flywheel(
            docs / "FAILURE_FLYWHEEL.md",
            stem=stem,
            report=report,
            source=str(traj_dir.as_posix()),
        )
        print(f"Updated docs/FAILURE_FLYWHEEL.md and docs/snapshots/{stem}.json")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
