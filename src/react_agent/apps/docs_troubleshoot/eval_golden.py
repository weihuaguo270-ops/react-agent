"""Offline golden-set evaluation — Workflow primary path, no score leakage.

Rules (strict):
- Run `docs_troubleshoot` Workflow on the raw question only (no must_* hint injection).
- Score **final answer text only** (never retrieval blob).
- Do not force refuse / do not stuff expected keywords into drafts.
- Optionally require preferred sources and forbid wrong tokens.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from react_agent.apps.docs_troubleshoot.index import reset_index
from react_agent.apps.docs_troubleshoot.policy import (
    answer_has_citation_marker,
    extract_claimed_sources,
)

_GOLDEN = Path(__file__).resolve().parent / "golden.json"


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
        # Prefer: at least one preferred source must be cited
        ok_src = bool(claimed & prefer) or any(p in text_l for p in prefer)

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


def run_golden_eval(*, path: str = "workflow") -> dict[str, Any]:
    """
    Run golden set.

    path:
      - workflow (default): Core Workflow — primary production-like path
      - (reserved) other paths may be added later
    """
    if path != "workflow":
        raise ValueError(f"unsupported eval path: {path}")

    os.environ.setdefault("REACT_AGENT_APP", "docs_troubleshoot")
    os.environ.setdefault("REACT_AGENT_RAG_MODE", "keyword")

    from react_agent.tools import enable_app_tools
    from react_agent.workflow import run_workflow

    enable_app_tools()
    reset_index()

    cases = load_golden()
    rows: list[dict[str, Any]] = []
    for case in cases:
        # Strict: raw question only — no must_* leakage into retrieval
        result = run_workflow("docs_troubleshoot", {"query": case["question"]})
        rows.append(
            score_workflow_case(
                case,
                answer=result.answer,
                refused=bool(result.refused),
                ok_run=bool(result.ok),
            )
        )

    passed = sum(1 for r in rows if r["passed"])
    total = len(rows)
    by_tag: dict[str, dict[str, int]] = {}
    for case, row in zip(cases, rows):
        tag = str(case.get("tag") or "core")
        bucket = by_tag.setdefault(tag, {"passed": 0, "total": 0})
        bucket["total"] += 1
        if row["passed"]:
            bucket["passed"] += 1

    return {
        "path": path,
        "passed": passed,
        "total": total,
        "pass_rate": round(passed / total, 3) if total else 0.0,
        "by_tag": by_tag,
        "rows": rows,
        "leakage_guards": {
            "no_must_in_query": True,
            "score_answer_only": True,
            "no_forced_refuse": True,
            "no_keyword_stuffing": True,
        },
    }


# Back-compat alias used by older imports/tests
def score_case(case: dict[str, Any]) -> dict[str, Any]:
    """Run a single case via Workflow (strict)."""
    os.environ.setdefault("REACT_AGENT_APP", "docs_troubleshoot")
    os.environ.setdefault("REACT_AGENT_RAG_MODE", "keyword")
    from react_agent.tools import enable_app_tools
    from react_agent.workflow import run_workflow

    enable_app_tools()
    reset_index()
    result = run_workflow("docs_troubleshoot", {"query": case["question"]})
    return score_workflow_case(
        case,
        answer=result.answer,
        refused=bool(result.refused),
        ok_run=bool(result.ok),
    )


if __name__ == "__main__":
    report = run_golden_eval()
    print(json.dumps(report, ensure_ascii=False, indent=2))
    raise SystemExit(0 if report["passed"] == report["total"] else 1)
