"""Git-tracked docs held-out evaluation (real repo docs/ via ls-files)."""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from react_agent.apps.docs_troubleshoot.eval_golden import score_workflow_case
from react_agent.apps.docs_troubleshoot.index import reset_index

_APP = Path(__file__).resolve().parent
_REPO = _APP.resolve().parents[3]
_CASES = _APP / "git_docs_cases.json"
# 语料基线：记录断言编写时 docs/ 的逐文件 sha256
_BASELINE = _APP / "git_docs_corpus_baseline.json"


def repo_root() -> Path:
    return _REPO


def load_git_docs_cases() -> list[dict[str, Any]]:
    return json.loads(_CASES.read_text(encoding="utf-8"))


# ── 语料漂移检测 ──
# docs/ 既是文档也是本评测的 RAG 语料，且断言是 must_any 关键词匹配“被检索到的
# 文本片段”。因此结构性改写（插入/移动章节、改写被断言的句子）会让评测失败——
# 即使语义没变。这里把语料状态相对基线的漂移**显式报告**出来，并指出哪些用例
# 受影响的文件牵动，避免失败时只能靠猜。默认提示；strict 模式可直接失败。

def corpus_dir() -> Path:
    return _REPO / "docs"


def current_corpus_hashes() -> dict[str, str]:
    """当前 docs/ 语料的逐文件 sha256（与索引一致的文件集合）。"""
    from react_agent.apps.docs_troubleshoot.ingest import _iter_doc_files, sha256_file

    root = corpus_dir()
    if not root.is_dir():
        return {}
    return {fp.relative_to(root).as_posix(): sha256_file(fp) for fp in _iter_doc_files(root)}


def load_corpus_baseline() -> dict[str, str]:
    if not _BASELINE.is_file():
        return {}
    data = json.loads(_BASELINE.read_text(encoding="utf-8"))
    return dict(data.get("files") or {})


def refresh_corpus_baseline() -> dict[str, Any]:
    """把当前 docs/ 状态记录为基线（在确认断言仍然有效后调用）。"""
    files = current_corpus_hashes()
    payload = {
        "note": "git-docs 评测语料基线；docs/ 变更后请复核 git_docs_cases.json 断言后刷新",
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "files": files,
    }
    _BASELINE.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return payload


def corpus_drift() -> dict[str, Any]:
    """对比当前语料与基线，返回状态与受影响用例。"""
    current = current_corpus_hashes()
    baseline = load_corpus_baseline()
    if not baseline:
        return {
            "status": "no_baseline",
            "hint": (
                "缺少语料基线；确认断言有效后运行 "
                "python -m react_agent.apps.docs_troubleshoot.eval_git_docs --refresh-baseline 生成"
            ),
            "changed_files": [],
        }

    changed = sorted(
        name for name in set(current) | set(baseline)
        if current.get(name) != baseline.get(name)
    )
    if not changed:
        return {"status": "clean", "changed_files": []}

    # 哪些用例的 prefer_sources 指向了被改动的文件
    try:
        cases = load_git_docs_cases()
    except (OSError, json.JSONDecodeError):
        cases = []
    changed_names = {Path(n).name for n in changed}
    affected = sorted(
        str(case.get("id"))
        for case in cases
        if changed_names & {Path(str(s)).name for s in (case.get("prefer_sources") or [])}
    )
    return {
        "status": "changed",
        "changed_files": changed,
        "changed_count": len(changed),
        "affected_cases": affected,
        "hint": (
            "docs/ 语料已变化：关键词断言的命中片段可能位移。"
            "请复核 git_docs_cases.json 的 must_any / prefer_sources，"
            "确认后用 --refresh-baseline 刷新基线。"
        ),
    }


def _configure_git_ingest() -> None:
    os.environ["REACT_AGENT_DOCS_GIT_ROOT"] = str(_REPO)
    os.environ["REACT_AGENT_DOCS_GIT_PREFIX"] = "docs"
    os.environ.setdefault("REACT_AGENT_APP", "docs_troubleshoot")
    os.environ.setdefault("REACT_AGENT_RAG_MODE", "keyword")
    os.environ.pop("REACT_AGENT_DOCS_INGEST_DIRS", None)


def run_git_docs_eval(
    *, include_held_out: bool = True, strict_corpus: bool = False
) -> dict[str, Any]:
    _configure_git_ingest()

    from react_agent.tools import enable_app_tools
    from react_agent.workflow import run_workflow

    enable_app_tools()
    reset_index()

    drift = corpus_drift()
    if strict_corpus and drift["status"] == "changed":
        raise AssertionError(
            "docs/ 语料相对基线已变化，需先复核断言并刷新基线: "
            f"{drift.get('changed_files')}"
        )

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
        "corpus": drift,
        "rows": rows,
    }


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="git-docs held-out 评测")
    parser.add_argument(
        "--refresh-baseline",
        action="store_true",
        help="把当前 docs/ 状态记录为语料基线（确认断言仍有效后使用）",
    )
    parser.add_argument(
        "--strict-corpus",
        action="store_true",
        help="语料相对基线有变化时直接失败（默认只报告）",
    )
    args = parser.parse_args(argv)

    if args.refresh_baseline:
        payload = refresh_corpus_baseline()
        print(f"已刷新语料基线：{len(payload['files'])} 个文件 -> {_BASELINE}")
        return 0

    report = run_git_docs_eval(strict_corpus=args.strict_corpus)
    drift = report.get("corpus") or {}
    if drift.get("status") == "changed":
        print(
            f"[corpus] 警告：docs/ 有 {drift.get('changed_count')} 个文件相对基线变化，"
            f"受影响用例={drift.get('affected_cases')}",
            file=sys.stderr,
        )
        print(f"[corpus] {drift.get('hint')}", file=sys.stderr)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["passed"] == report["total"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
