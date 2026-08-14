"""Git-tracked docs held-out evaluation (real repo docs/ via ls-files)."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from react_agent.apps.docs_troubleshoot.eval_golden import score_workflow_case
from react_agent.apps.docs_troubleshoot.index import reset_index

_APP = Path(__file__).resolve().parent
_REPO = _APP.resolve().parents[3]
_CASES = _APP / "git_docs_cases.json"


def repo_root() -> Path:
    """返回 Git 文档评测使用的仓库根目录。"""
    return _REPO


def load_git_docs_cases() -> list[dict[str, Any]]:
    """加载基于真实仓库文档的冻结评测集。"""
    return json.loads(_CASES.read_text(encoding="utf-8"))


def _configure_git_ingest() -> None:
    os.environ["REACT_AGENT_DOCS_GIT_ROOT"] = str(_REPO)
    os.environ["REACT_AGENT_DOCS_GIT_PREFIX"] = "docs"
    os.environ.setdefault("REACT_AGENT_APP", "docs_troubleshoot")
    os.environ.setdefault("REACT_AGENT_RAG_MODE", "keyword")
    os.environ.pop("REACT_AGENT_DOCS_INGEST_DIRS", None)


def run_git_docs_eval(*, include_held_out: bool = True) -> dict[str, Any]:
    """运行 Git 文档集，并可排除 held-out 切片。"""
    _configure_git_ingest()

    from react_agent.tools import enable_app_tools
    from react_agent.workflow import run_workflow

    enable_app_tools()
    reset_index()

    cases = load_git_docs_cases()
    if not include_held_out:
        cases = [c for c in cases if c.get("tag") != "git_held_out"]

    rows: list[dict[str, Any]] = []
    for case in cases:
        result = run_workflow("docs_troubleshoot", {"query": case["question"]})
        row = score_workflow_case(
            case,
            answer=result.answer,
            refused=bool(result.refused),
            ok_run=bool(result.ok),
        )
        row["diagnosis"] = result.diagnosis
        rows.append(row)

    passed = sum(1 for r in rows if r["passed"])
    total = len(rows)
    by_tag: dict[str, dict[str, int]] = {}
    git_cites = 0
    for case, row in zip(cases, rows):
        tag = str(case.get("tag") or "git_blind")
        bucket = by_tag.setdefault(tag, {"passed": 0, "total": 0})
        bucket["total"] += 1
        if row["passed"]:
            bucket["passed"] += 1
        if row.get("passed") and any(
            p.split("/")[-1] in (row.get("answer") or "")
            for p in (case.get("prefer_sources") or [])
        ):
            git_cites += 1

    return {
        "suite": "git_docs_held_out",
        "git_root": str(_REPO),
        "git_prefix": "docs",
        "passed": passed,
        "total": total,
        "pass_rate": round(passed / total, 3) if total else 0.0,
        "by_tag": by_tag,
        "metrics": {
            "git_source_hit_rate": round(git_cites / total, 3) if total else 0.0,
        },
        "rows": rows,
    }


if __name__ == "__main__":
    report = run_git_docs_eval()
    print(json.dumps(report, ensure_ascii=False, indent=2))
    raise SystemExit(0 if report["passed"] == report["total"] else 1)
