"""python -m react_agent.workflow — list / run Core workflows."""
from __future__ import annotations

import argparse
import json
import os


def main(argv=None):
    p = argparse.ArgumentParser(description="Core Workflow CLI")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("list", help="list workflows")

    run_p = sub.add_parser("run", help="run a workflow")
    run_p.add_argument("name")
    run_p.add_argument("--query", default="")
    run_p.add_argument("--json", dest="payload", default="")

    args = p.parse_args(argv)
    if args.cmd == "list":
        from react_agent.workflow import list_workflows

        print(json.dumps(list_workflows(), ensure_ascii=False, indent=2))
        return 0

    os.environ.setdefault("REACT_AGENT_APP", "docs_troubleshoot")
    os.environ.setdefault("REACT_AGENT_RAG_MODE", "keyword")
    from react_agent.workflow import run_workflow
    from react_agent.tools import enable_app_tools
    from react_agent.apps.docs_troubleshoot.index import reset_index

    enable_app_tools()
    if args.name == "docs_troubleshoot":
        reset_index()

    initial = {}
    if args.payload:
        initial = json.loads(args.payload)
    if args.query:
        initial["query"] = args.query
    result = run_workflow(args.name, initial)
    print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
    return 0 if result.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
