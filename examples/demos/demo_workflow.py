"""Demo Core Workflow: docs_troubleshoot (no LLM / no LangGraph)."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

os.environ["REACT_AGENT_APP"] = "docs_troubleshoot"
os.environ.setdefault("REACT_AGENT_RAG_MODE", "keyword")

from react_agent.apps.docs_troubleshoot.index import reset_index
from react_agent.tools import enable_app_tools, enable_workflow_tools
from react_agent.workflow import list_workflows, run_workflow


def main():
    enable_app_tools()
    enable_workflow_tools()
    reset_index()
    print("=== Registered workflows ===")
    print(json.dumps(list_workflows(), ensure_ascii=False, indent=2))

    queries = [
        "缺少 Authorization 返回什么？",
        "DeepSeek HTTP 400 怎么排查？",
        "股价明天多少？",
    ]
    print("\n=== Run docs_troubleshoot workflow ===")
    for q in queries:
        result = run_workflow("docs_troubleshoot", {"query": q})
        print(f"\nQ: {q}")
        print(f"  ok={result.ok} refused={result.refused} steps={len(result.steps)}")
        print(f"  answer={result.answer[:160]}")
        print(f"  step_ids={[s.step_id for s in result.steps]}")
    print("\nCLI: python -m react_agent.workflow run docs_troubleshoot --query \"...\"")


if __name__ == "__main__":
    main()
