"""Collect the R1 shared error-envelope matrix, including a real MCP child server."""
from __future__ import annotations

import hashlib
import json
import sys
import textwrap
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / "artifacts" / "harness" / "p2-r1-cross-path.json"
SERVER = textwrap.dedent(
    r'''
    import json, sys
    def reply(req, result=None, error=None):
        out = {"jsonrpc":"2.0", "id":req["id"]}
        out["error" if error is not None else "result"] = error if error is not None else (result or {})
        print(json.dumps(out), flush=True)
    for line in sys.stdin:
        req = json.loads(line)
        if "id" not in req: continue
        method = req.get("method")
        if method == "initialize":
            reply(req, {"serverInfo":{"name":"r1-real-mcp-fixture","version":"1"}})
        elif method == "tools/list":
            reply(req, {"tools":[{"name":"shared_missing","inputSchema":{"type":"object"}}]})
        elif method == "tools/call":
            reply(req, error={"code":-32601,"message":"method not found"})
    '''
)


def capture(source: str, operation) -> dict:
    from react_agent.harness.contracts import ToolCallError, tool_error_from_exception

    try:
        operation()
    except ToolCallError as exc:
        return exc.error.to_dict()
    except Exception as exc:
        return tool_error_from_exception(exc, source=source, tool_name="shared_missing")
    raise AssertionError(f"expected {source} to return a tool error")


def main() -> int:
    from react_agent.harness.tool_boundary import execute_registered_tool
    from react_agent.mcp_client import MCPClient, MockMCPClient
    from react_agent.workflow.engine import Step, StepKind, WorkflowDef, WorkflowRunner

    cases: dict[str, dict] = {}
    cases["react"] = capture(
        "react", lambda: execute_registered_tool("shared_missing", {}, {}, source="react")
    )
    workflow = WorkflowRunner(
        WorkflowDef(
            name="r1-envelope",
            description="R1 matrix",
            steps=[Step(id="call", kind=StepKind.TOOL, tool="shared_missing")],
        ),
        {},
    ).run()
    cases["workflow"] = json.loads(workflow.steps[0].error)

    import react_agent.eval.execution_scorer as execution_scorer
    previous_registry = execution_scorer.TOOL_REGISTRY
    execution_scorer.TOOL_REGISTRY = {}
    try:
        cases["evaluation"] = json.loads(
            execution_scorer.execute_tool_step("shared_missing", {})
        )
    finally:
        execution_scorer.TOOL_REGISTRY = previous_registry

    mock = MockMCPClient()
    mock.connect()
    mock.discover_tools()
    try:
        cases["mcp_mock"] = capture("mcp", lambda: mock.call_tool("shared_missing", {}))
    finally:
        mock.close()

    real = MCPClient(sys.executable, ["-u", "-c", SERVER])
    real.connect()
    real.discover_tools()
    try:
        cases["mcp_real_server"] = capture("mcp", lambda: real.call_tool("shared_missing", {}))
    finally:
        real.close()

    semantic = ("error_code", "stop_reason", "retryable", "attempt", "tool_name")
    baseline = {key: cases["react"][key] for key in semantic}
    checks = {
        "all_paths_have_shared_fields": all(set(semantic) <= payload.keys() for payload in cases.values()),
        "semantic_fields_match": all(
            {key: payload[key] for key in semantic} == baseline for payload in cases.values()
        ),
        "sources_identify_path": {payload["source"] for payload in cases.values()} == {
            "react", "workflow", "evaluation", "mcp"
        },
        "real_mcp_server_included": "mcp_real_server" in cases,
    }
    report = {
        "schema_version": "harness-p2-r1-cross-path/v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "tool": "shared_missing",
        "arguments": {},
        "cases": cases,
        "checks": checks,
        "passed": all(checks.values()),
        "evidence_boundary": (
            "The real MCP case is a disposable local stdio server implementing the MCP protocol; "
            "it is not evidence from a third-party production MCP deployment."
        ),
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    canonical = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    report["artifact_sha256"] = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
