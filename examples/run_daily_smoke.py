"""Daily P0 smoke — append cross-day variance rows for Execution / Reliability.

Default (CI / free): offline execution + injected reliability + mock live A/B.
Optional: --with-agent when DEEPSEEK_API_KEY is set (costs API).

Usage:
  python examples/run_daily_smoke.py
  python examples/run_daily_smoke.py --with-agent
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
sys.path.insert(0, str(ROOT / "src"))

LOG_DIR = ROOT / "docs" / "daily_smoke"
LOG_JSONL = LOG_DIR / "log.jsonl"
VARIANCE_MD = LOG_DIR / "VARIANCE.md"

os.environ.setdefault("REACT_AGENT_SKIP_RAG", "1")
os.environ.setdefault("REACT_AGENT_SANDBOX_PREWARM", "0")
os.environ.setdefault("REACT_AGENT_DISABLE_MCP", "1")


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


def _run_execution_offline() -> dict:
    from react_agent.eval.execution_scorer import run_execution_suite

    report = run_execution_suite(None, modes=["offline_tools"])
    s = report["summary"]
    return {
        "ok": int(s.get("failed", 0) or 0) == 0,
        "passed": s.get("passed"),
        "total": s.get("total"),
        "pass_rate": s.get("pass_rate"),
        "wilson": s.get("pass_rate_wilson_95"),
    }


def _run_reliability_harness() -> dict:
    # Reuse CLI for a stable contract
    proc = subprocess.run(
        [sys.executable, str(ROOT / "examples" / "run_reliability_harness.py")],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return {
        "ok": proc.returncode == 0,
        "exit_code": proc.returncode,
        "tail": (proc.stdout or "")[-400:],
    }


def _run_reliability_mock() -> dict:
    proc = subprocess.run(
        [sys.executable, str(ROOT / "examples" / "run_reliability_live.py"), "--mock"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return {
        "ok": proc.returncode == 0,
        "exit_code": proc.returncode,
        "tail": (proc.stdout or "")[-400:],
    }


def _run_execution_agent_smoke() -> dict:
    """Tiny agent subset if key present — not the full 36."""
    from react_agent.eval.execution_scorer import run_execution_suite

    report = run_execution_suite(None, modes=["agent"], difficulties=["easy"])
    s = report["summary"]
    return {
        "ok": int(s.get("failed", 0) or 0) == 0,
        "passed": s.get("passed"),
        "total": s.get("total"),
        "pass_rate": s.get("pass_rate"),
        "note": "easy-only agent smoke",
    }


def _render_variance(rows: list[dict]) -> str:
    lines = [
        "# Daily smoke variance（跨日）",
        "",
        "自动由 `examples/run_daily_smoke.py` + GitHub Actions `daily-smoke` 追加。",
        "默认 **offline / mock**（不耗 API）；带 Key 时可选 `--with-agent`。",
        "",
        "| date (UTC) | git | exec offline | exec ok | reliability harness | reliability mock | agent smoke | overall |",
        "|------------|-----|-------------:|:-------:|:-------------------:|:----------------:|:-----------:|:-------:|",
    ]
    for r in rows[-60:]:  # keep table readable
        ex = r.get("execution_offline") or {}
        ex_s = (
            f"{ex.get('passed')}/{ex.get('total')}"
            if ex.get("total") is not None
            else "-"
        )
        ag = r.get("execution_agent")
        if ag:
            ag_s = f"{ag.get('passed')}/{ag.get('total')}"
        else:
            ag_s = "skip"
        lines.append(
            "| {date} | `{git}` | {ex} | {ex_ok} | {rh} | {rm} | {ag} | {ov} |".format(
                date=r.get("date", ""),
                git=r.get("git", ""),
                ex=ex_s,
                ex_ok="PASS" if ex.get("ok") else "FAIL",
                rh="PASS" if (r.get("reliability_harness") or {}).get("ok") else "FAIL",
                rm="PASS" if (r.get("reliability_mock") or {}).get("ok") else "FAIL",
                ag=ag_s if ag else "skip",
                ov="PASS" if r.get("overall_ok") else "FAIL",
            )
        )
    lines.extend(
        [
            "",
            "## 怎么读",
            "",
            "- 看的是**跨日是否稳定**，不是再刷一次公开大快照。",
            "- `agent smoke` 默认 skip；只有 workflow / 本地显式开 `--with-agent` 才跑。",
            "- 复现：`python examples/run_daily_smoke.py`",
            "",
        ]
    )
    return "\n".join(lines)


def _load_rows() -> list[dict]:
    if not LOG_JSONL.is_file():
        return []
    rows = []
    for line in LOG_JSONL.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description="Daily P0 smoke + variance log")
    parser.add_argument(
        "--with-agent",
        action="store_true",
        help="Also run easy agent execution (needs API Key)",
    )
    args = parser.parse_args()

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc)
    row: dict = {
        "date": now.strftime("%Y-%m-%d"),
        "timestamp": now.isoformat(),
        "git": _git_sha(),
    }

    print("[daily] execution offline …")
    row["execution_offline"] = _run_execution_offline()
    print(
        f"  -> {row['execution_offline'].get('passed')}/"
        f"{row['execution_offline'].get('total')} "
        f"ok={row['execution_offline'].get('ok')}"
    )

    print("[daily] reliability harness …")
    row["reliability_harness"] = _run_reliability_harness()
    print(f"  -> ok={row['reliability_harness'].get('ok')}")

    print("[daily] reliability mock …")
    row["reliability_mock"] = _run_reliability_mock()
    print(f"  -> ok={row['reliability_mock'].get('ok')}")

    if args.with_agent:
        if not (
            os.environ.get("DEEPSEEK_API_KEY") or os.environ.get("OPENAI_API_KEY")
        ):
            print("ERROR: --with-agent needs API Key", file=sys.stderr)
            return 2
        print("[daily] execution agent (easy) …")
        row["execution_agent"] = _run_execution_agent_smoke()
        print(
            f"  -> {row['execution_agent'].get('passed')}/"
            f"{row['execution_agent'].get('total')} "
            f"ok={row['execution_agent'].get('ok')}"
        )

    checks = [
        row["execution_offline"].get("ok"),
        row["reliability_harness"].get("ok"),
        row["reliability_mock"].get("ok"),
    ]
    if "execution_agent" in row:
        checks.append(row["execution_agent"].get("ok"))
    row["overall_ok"] = all(bool(x) for x in checks)

    with LOG_JSONL.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")

    rows = _load_rows()
    VARIANCE_MD.write_text(_render_variance(rows), encoding="utf-8")
    print(f"[daily] wrote {LOG_JSONL.relative_to(ROOT)}")
    print(f"[daily] wrote {VARIANCE_MD.relative_to(ROOT)}")
    print(f"[daily] overall={'PASS' if row['overall_ok'] else 'FAIL'}")
    return 0 if row["overall_ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
