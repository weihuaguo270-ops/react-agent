"""跑公开 Agent benchmark 子集（GSM8K×10 + HotpotQA×10）。

用法：
  # CI / 无 Key：校验匹配器（默认）
  python examples/run_public_benchmark.py

  # 真实 Agent（需 DEEPSEEK_API_KEY）
  python examples/run_public_benchmark.py --modes agent --publish

  # 只跑某一基准
  python examples/run_public_benchmark.py --benchmarks gsm8k --modes offline
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

try:
    from react_agent.llm import _load_dotenv

    _load_dotenv()
except Exception:
    pass

from react_agent.eval.public_benchmark import (  # noqa: E402
    report_to_markdown,
    run_public_benchmark,
)


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


def main() -> int:
    parser = argparse.ArgumentParser(description="Public Agent benchmark subset")
    parser.add_argument("--dataset", default=None)
    parser.add_argument(
        "--modes",
        default="offline",
        help="comma: offline,agent (default offline)",
    )
    parser.add_argument(
        "--benchmarks",
        default=None,
        help="comma: gsm8k,hotpotqa (default both)",
    )
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--publish", action="store_true")
    parser.add_argument("--stem", default=None)
    args = parser.parse_args()

    modes = [m.strip() for m in args.modes.split(",") if m.strip()]
    benchmarks = None
    if args.benchmarks:
        benchmarks = [b.strip() for b in args.benchmarks.split(",") if b.strip()]

    if "agent" in modes:
        os.environ.setdefault("REACT_AGENT_SKIP_RAG", "1")
        os.environ.setdefault("REACT_AGENT_SANDBOX_PREWARM", "0")
        os.environ.setdefault("REACT_AGENT_DISABLE_MCP", "1")
        os.environ.setdefault("LLM_PROVIDER", "deepseek")
        if not (os.environ.get("DEEPSEEK_API_KEY") or os.environ.get("OPENAI_API_KEY")):
            print("ERROR: agent 模式需要 DEEPSEEK_API_KEY 或 OPENAI_API_KEY", file=sys.stderr)
            return 2

    report = run_public_benchmark(
        args.dataset,
        modes=modes,
        benchmarks=benchmarks,
        limit=args.limit,
    )
    s = report["summary"]
    print("=" * 55)
    print(f"  Public benchmark modes={modes} benches={benchmarks or 'all'}")
    print(f"  {s['passed']}/{s['total']}  pass_rate={s['pass_rate']}%")
    print(f"  by_benchmark: {report.get('by_benchmark')}")
    print("=" * 55)
    for r in report["results"]:
        icon = "OK" if r["passed"] else ("SKIP" if r.get("skipped") else "FAIL")
        print(f"  [{icon}] {r['id']} ({r.get('benchmark')}/{r.get('mode')}): {r.get('reason')}")

    if args.publish:
        stem = args.stem or (
            "public_benchmark_snapshot_" + datetime.now().strftime("%Y%m%d")
        )
        docs = ROOT / "docs"
        snap_dir = docs / "snapshots"
        docs.mkdir(exist_ok=True)
        snap_dir.mkdir(exist_ok=True)
        json_path = snap_dir / f"{stem}.json"
        md_path = docs / f"{stem}.md"
        cmd = f"python examples/run_public_benchmark.py --modes {','.join(modes)}"
        if benchmarks:
            cmd += f" --benchmarks {','.join(benchmarks)}"
        cmd += " --publish"
        report["meta"] = {"git": _git_sha(), "reproduce_cmd": cmd}
        json_path.write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        md = report_to_markdown(report, title=f"公开 Agent benchmark 子集（{stem}）")
        notes = (
            f"\n\n---\n\n- git: `{_git_sha()}`\n"
            f"- archived_json: `docs/snapshots/{json_path.name}`\n"
            f"- reproduce: `{cmd}`\n"
        )
        md_path.write_text(md.rstrip() + notes, encoding="utf-8")
        print(f"Published: {md_path}")
        print(f"Archived:  {json_path}")

    return 0 if s["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
