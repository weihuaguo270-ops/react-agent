"""Offline golden-set evaluation — Workflow primary path, no score leakage.

Rules (strict):
- Run eval path on the raw question only (no must_* hint injection).
- Score **final answer text only** (never retrieval blob).
- Do not force refuse / do not stuff expected keywords into drafts.
- Optionally require preferred sources and forbid wrong tokens.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from react_agent.apps.docs_troubleshoot.index import reset_index
from react_agent.apps.docs_troubleshoot.policy import (
    answer_has_citation_marker,
    extract_claimed_sources,
)

_GOLDEN = Path(__file__).resolve().parent / "golden.json"
_APP_ROOT = Path(__file__).resolve().parent


def load_golden() -> list[dict[str, Any]]:
    return json.loads(_GOLDEN.read_text(encoding="utf-8"))


def _norm_sources(items: list[str] | None) -> set[str]:
    return {s.split("/")[-1].lower() for s in (items or []) if s}


def score_workflow_case(case: dict[str, Any], *, answer: str, refused: bool, ok_run: bool) -> dict[str, Any]:
    """Score one case from a Workflow (or any) final answer — answer text only."""
    expect = case.get("expect", "answer")
    must_any = case.get("must_any") or []
    must_all = case.get("must_all") or []
    forbid_any = case.get("forbid_any") or []
    must_cite = bool(case.get("must_cite"))
    prefer = _norm_sources(case.get("prefer_sources"))
    text = answer or ""
    text_l = text.lower()

    details: dict[str, Any] = {
        "id": case["id"],
        "tag": case.get("tag") or "core",
        "expect": expect,
        "answer": text[:280],
        "refused": refused,
        "ok_run": ok_run,
    }

    if not ok_run:
        details["passed"] = False
        details["fail_reason"] = "workflow_not_ok"
        return details

    if expect == "refuse":
        ok_kw = any(k in text for k in must_any) if must_any else True
        passed = bool(refused and ok_kw)
        details.update(
            {
                "passed": passed,
                "ok_kw": ok_kw,
                "fail_reason": "" if passed else "expected_refuse",
            }
        )
        return details

    # expect == answer
    if refused:
        details["passed"] = False
        details["fail_reason"] = "unexpected_refuse"
        return details

    ok_any = any(k.lower() in text_l for k in must_any) if must_any else True
    ok_all = all(k.lower() in text_l for k in must_all) if must_all else True
    ok_forbid = not any(k.lower() in text_l for k in forbid_any) if forbid_any else True
    ok_cite = (not must_cite) or answer_has_citation_marker(text)

    claimed = {c.lower() for c in extract_claimed_sources(text)}
    ok_src = True
    if prefer:
        ok_src = bool(claimed & prefer)
        if not ok_src and must_cite and claimed:
            ok_src = False
        elif not ok_src and must_cite and not claimed:
            ok_src = any(p in text_l for p in prefer)

    passed = bool(ok_any and ok_all and ok_forbid and ok_cite and ok_src)
    fail = []
    if not ok_any:
        fail.append("must_any")
    if not ok_all:
        fail.append("must_all")
    if not ok_forbid:
        fail.append("forbid_any")
    if not ok_cite:
        fail.append("citation")
    if not ok_src:
        fail.append("prefer_sources")

    details.update(
        {
            "passed": passed,
            "ok_any": ok_any,
            "ok_all": ok_all,
            "ok_forbid": ok_forbid,
            "ok_cite": ok_cite,
            "ok_src": ok_src,
            "claimed_sources": sorted(claimed),
            "fail_reason": ",".join(fail),
        }
    )
    return details


def _run_one_case(case: dict[str, Any], *, path: str) -> dict[str, Any]:
    if path == "workflow":
        from react_agent.workflow import run_workflow

        result = run_workflow("docs_troubleshoot", {"query": case["question"]})
        return score_workflow_case(
            case,
            answer=result.answer,
            refused=bool(result.refused),
            ok_run=bool(result.ok),
        )
    if path in ("agent", "chat_offline"):
        from react_agent.apps.docs_troubleshoot.offline_answer import answer_offline

        out = answer_offline(case["question"])
        return score_workflow_case(
            case,
            answer=str(out.get("answer") or ""),
            refused=bool(out.get("refused")),
            ok_run=bool(out.get("ok")),
        )
    raise ValueError(f"unsupported eval path: {path}")


def run_golden_eval(*, path: str = "agent") -> dict[str, Any]:
    """
    Run golden set.

    path:
      - agent (default): offline Agent loop (tool selection + verify_citations + trajectory)
      - workflow: legacy fixed-step Workflow DAG
      - chat_offline: alias of agent (/v1/chat offline path)
    """
    if path == "chat_offline":
        path = "agent"
    if path not in ("agent", "workflow"):
        raise ValueError(f"unsupported eval path: {path}")

    os.environ.setdefault("REACT_AGENT_APP", "docs_troubleshoot")
    os.environ.setdefault("REACT_AGENT_RAG_MODE", "keyword")

    from react_agent.tools import enable_app_tools

    enable_app_tools()
    reset_index()

    cases = load_golden()
    rows: list[dict[str, Any]] = []
    for case in cases:
        rows.append(_run_one_case(case, path=path))

    passed = sum(1 for r in rows if r["passed"])
    total = len(rows)
    by_tag: dict[str, dict[str, int]] = {}
    for case, row in zip(cases, rows):
        tag = str(case.get("tag") or "core")
        bucket = by_tag.setdefault(tag, {"passed": 0, "total": 0})
        bucket["total"] += 1
        if row["passed"]:
            bucket["passed"] += 1

    held = by_tag.get("held_out", {"passed": 0, "total": 0})

    return {
        "path": path,
        "passed": passed,
        "total": total,
        "pass_rate": round(passed / total, 3) if total else 0.0,
        "by_tag": by_tag,
        "non_held_out": {
            "passed": sum(
                1 for c, r in zip(cases, rows) if c.get("tag") != "held_out" and r["passed"]
            ),
            "total": sum(1 for c in cases if c.get("tag") != "held_out"),
        },
        "rows": rows,
        "leakage_guards": {
            "no_must_in_query": True,
            "score_answer_only": True,
            "no_forced_refuse": True,
            "no_keyword_stuffing": True,
        },
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


def eval_gate_ok(report: dict[str, Any], *, gate: str = "all") -> bool:
    if gate == "all":
        return report["passed"] == report["total"]
    if gate == "non_held_out":
        nh = report.get("non_held_out") or {}
        return nh.get("passed") == nh.get("total")
    raise ValueError(f"unknown gate: {gate}")


def publish_golden_snapshot(report: dict[str, Any], *, stem: str | None = None) -> tuple[Path, Path]:
    """Write JSON archive + markdown summary under docs/."""
    repo = _APP_ROOT.parents[4]
    docs = repo / "docs"
    snap_dir = docs / "snapshots"
    reports_dir = docs / "reports"
    snap_dir.mkdir(parents=True, exist_ok=True)
    reports_dir.mkdir(parents=True, exist_ok=True)

    day = datetime.now(timezone.utc).strftime("%Y%m%d")
    stem = stem or f"docs_troubleshoot_golden_{day}"
    archived = snap_dir / f"{stem}.json"
    archived.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    by_tag = report.get("by_tag") or {}
    lines = [
        f"# 文档/API 排障黄金集快照（{stem}）",
        "",
        f"- **路径:** `{report.get('path')}`",
        f"- **结果:** {report['passed']}/{report['total']}（pass_rate={report.get('pass_rate')}）",
        f"- **生成:** {report.get('generated_at')}",
        f"- **归档 JSON:** [`snapshots/{archived.name}`](../snapshots/{archived.name})",
        "",
        "## 分 tag",
        "",
        "| tag | passed | total |",
        "|-----|--------|-------|",
    ]
    for tag in ("core", "hard", "refuse", "held_out"):
        b = by_tag.get(tag)
        if b:
            lines.append(f"| {tag} | {b['passed']} | {b['total']} |")
    lines += [
        "",
        "## 复现",
        "",
        "```bash",
        "python examples/eval/run_docs_troubleshoot_eval.py",
        "```",
        "",
    ]
    md_path = reports_dir / f"{stem}.md"
    md_path.write_text("\n".join(lines), encoding="utf-8")
    stub = docs / f"{stem}.md"
    stub.write_text(
        f"Moved → [`reports/{stem}.md`](reports/{stem}.md)\n",
        encoding="utf-8",
    )
    return archived, md_path


# Back-compat alias used by older imports/tests
def score_case(case: dict[str, Any]) -> dict[str, Any]:
    """Run a single case via Workflow (strict)."""
    os.environ.setdefault("REACT_AGENT_APP", "docs_troubleshoot")
    os.environ.setdefault("REACT_AGENT_RAG_MODE", "keyword")
    reset_index()
    return _run_one_case(case, path="agent")


if __name__ == "__main__":
    report = run_golden_eval()
    print(json.dumps(report, ensure_ascii=False, indent=2))
    raise SystemExit(0 if report["passed"] == report["total"] else 1)
