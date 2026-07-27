"""跑公开 RAG/Agent benchmark（分层 smoke/hard/held_out + 跌落对照）。

用法：
  # 推荐对外口径：全部分层 + 自动 controls
  python examples/run_public_rag_benchmark.py

  # 只看 hard / held_out
  python examples/run_public_rag_benchmark.py --tiers hard,held_out --modes rag

  # Agent（需 Key）
  python examples/run_public_rag_benchmark.py --modes agent --tiers hard --publish
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

from react_agent.eval.public_rag_benchmark import (  # noqa: E402
    report_to_markdown,
    run_public_rag_benchmark,
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
    parser = argparse.ArgumentParser(
        description="Public RAG/Agent benchmark (stratified; not smoke-only SOTA)"
    )
    parser.add_argument("--dataset", default=None)
    parser.add_argument(
        "--modes",
        default="offline,rag",
        help="comma: offline,rag,rag_topk1,rag_no_context,rag_distractors_only,agent",
    )
    parser.add_argument(
        "--benchmarks",
        default=None,
        help="comma: hotpotqa_rag,nq_rag",
    )
    parser.add_argument(
        "--tiers",
        default=None,
        help="comma: smoke,hard,held_out (default all)",
    )
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--top-k", type=int, default=None)
    parser.add_argument("--min-recall", type=float, default=None)
    parser.add_argument(
        "--no-controls",
        action="store_true",
        help="disable automatic drop-off controls on hard/held_out",
    )
    parser.add_argument("--publish", action="store_true")
    parser.add_argument("--stem", default=None)
    args = parser.parse_args()

    modes = [m.strip() for m in args.modes.split(",") if m.strip()]
    benchmarks = (
        [b.strip() for b in args.benchmarks.split(",") if b.strip()]
        if args.benchmarks
        else None
    )
    tiers = (
        [t.strip() for t in args.tiers.split(",") if t.strip()] if args.tiers else None
    )

    if "agent" in modes:
        os.environ.setdefault("REACT_AGENT_SKIP_RAG", "1")
        os.environ.setdefault("REACT_AGENT_SANDBOX_PREWARM", "0")
        os.environ.setdefault("REACT_AGENT_DISABLE_MCP", "1")
        os.environ.setdefault("LLM_PROVIDER", "deepseek")
        if not (os.environ.get("DEEPSEEK_API_KEY") or os.environ.get("OPENAI_API_KEY")):
            print(
                "ERROR: agent 模式需要 DEEPSEEK_API_KEY 或 OPENAI_API_KEY",
                file=sys.stderr,
            )
            return 2

    report = run_public_rag_benchmark(
        args.dataset,
        modes=modes,
        benchmarks=benchmarks,
        tiers=tiers,
        limit=args.limit,
        top_k=args.top_k,
        min_recall=args.min_recall,
        include_controls=not args.no_controls,
    )
    s = report["summary"]
    print("=" * 55)
    print(f"  Public RAG modes={modes} tiers={tiers or 'all'}")
    print(f"  overall {s['passed']}/{s['total']} ({s['pass_rate']}%)  << do not cite alone")
    print(f"  by_tier: {report.get('by_tier')}")
    print(f"  dropoff: {report.get('dropoff_controls')}")
    print(f"  honesty: {(report.get('honesty') or {}).get('live_reading', '')}")
    print("=" * 55)
    for r in report["results"]:
        icon = "OK" if r["passed"] else "FAIL"
        print(
            f"  [{icon}] {r['id']} ({r.get('tier')}/{r['mode']}): "
            f"recall={r.get('retrieval_recall')} | {r.get('reason')}"
        )

    if args.publish:
        stem = args.stem or (
            f"public_rag_benchmark_snapshot_{datetime.now().strftime('%Y%m%d')}"
        )
        docs = ROOT / "docs"
        snap = docs / "snapshots"
        snap.mkdir(parents=True, exist_ok=True)
        report["git"] = _git_sha()
        report["reproduce_cmd"] = (
            "python examples/run_public_rag_benchmark.py "
            f"--modes {','.join(modes)} --publish"
        )
        json_path = snap / f"{stem}.json"
        md_path = docs / f"{stem}.md"
        json_path.write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        md_path.write_text(report_to_markdown(report, title=stem), encoding="utf-8")
        print(f"\nPublished:\n  {md_path}\n  {json_path}")

    # Gate: smoke offline+rag must pass; hard/held_out are informational (may fail)
    smoke_rows = [
        r
        for r in report["results"]
        if r.get("tier") == "smoke" and r.get("mode") in ("offline", "rag")
    ]
    smoke_ok = all(r.get("passed") for r in smoke_rows) if smoke_rows else True
    if not smoke_ok:
        print("GATE FAIL: smoke tier must pass (protocol regression)", file=sys.stderr)
        return 1
    print("GATE OK: smoke protocol pass; hard/held_out reported for honesty")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
