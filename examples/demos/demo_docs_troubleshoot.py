"""Offline demo: docs/API troubleshoot capability backend (no API Key)."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

os.environ["REACT_AGENT_APP"] = "docs_troubleshoot"
os.environ.setdefault("REACT_AGENT_RAG_MODE", "keyword")

from react_agent.apps.docs_troubleshoot.eval_golden import run_golden_eval
from react_agent.apps.docs_troubleshoot.index import reset_index
from react_agent.apps.docs_troubleshoot.policy import enforce_answer_policy, should_refuse_query
from react_agent.apps.docs_troubleshoot.tools import lookup_api, search_docs, verify_citations_tool


def main():
    reset_index()
    queries = [
        "缺少 Authorization 返回什么？",
        "DeepSeek 400 怎么排查？",
        "我们公司股价明天多少？",
    ]
    print("=== Docs/API Troubleshoot Demo (offline) ===\n")
    for q in queries:
        print(f"Q: {q}")
        hits = json.loads(search_docs(q, top_k=2))
        if not hits.get("results"):
            hits = json.loads(lookup_api(q, top_k=2))
        sources = [r["source"] for r in hits.get("results") or []]
        if sources:
            draft = (
                f"根据检索结果：{(hits['results'][0].get('content') or '')[:160]} "
                f"来源: {sources[0]}"
            )
        else:
            draft = "没有相关文档。"
        # Out-of-domain heuristic
        must_refuse = should_refuse_query(q)
        out = enforce_answer_policy(
            draft, allowed_sources=sources or None, must_refuse=must_refuse
        )
        check = json.loads(verify_citations_tool(out["answer"]))
        print(f"  refused={out['refused']} policy={out['policy']}")
        print(f"  answer={out['answer'][:180]}")
        print(f"  verify={check.get('ok')} reason={check.get('reason')}\n")

    report = run_golden_eval()
    print(
        f"Golden eval: {report['passed']}/{report['total']} "
        f"(pass_rate={report['pass_rate']})"
    )
    raise SystemExit(0 if report["passed"] == report["total"] else 1)


if __name__ == "__main__":
    main()
