"""Execution HTTP smoke — POST /v1/chat app=default against a running server.

Requires REACT_AGENT_SERVER_OFFLINE_REACT=1 (CI) or REACT_AGENT_SERVER_LLM=1 (live).

  python examples/eval/run_execution_http_smoke.py --url http://127.0.0.1:8765
"""
from __future__ import annotations

import argparse
import sys

from react_agent.eval.http_execution import run_execution_http_smoke


def main() -> int:
    p = argparse.ArgumentParser(description="Execution suite via HTTP app=default")
    p.add_argument("--url", default="http://127.0.0.1:8765", help="Server base URL")
    p.add_argument(
        "--ids",
        default="agent_calc_17x19,agent_calc_100_minus_37,agent_get_time",
        help="Comma-separated execution task ids",
    )
    args = p.parse_args()
    ids = {x.strip() for x in args.ids.split(",") if x.strip()}
    report = run_execution_http_smoke(args.url, only_ids=ids)
    s = report["summary"]
    print("=" * 55)
    print(f"  Execution HTTP smoke  app=default  {s['passed']}/{s['total']}")
    print("=" * 55)
    for r in report["results"]:
        icon = "OK" if r.get("passed") else "FAIL"
        print(f"  [{icon}] {r['id']}: {r.get('reason', '')}")
    return 0 if s.get("failed", 0) == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
