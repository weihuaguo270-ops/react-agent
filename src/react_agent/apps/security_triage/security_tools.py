"""Project Skill/MCP-compatible read-only tool surface."""
from __future__ import annotations

import json
from typing import Any

from .intel import get_intel_provider
from .workflow import run_triage

TOOL_DEFINITIONS = [
    {
        "name": "security_lookup_cve",
        "description": "Read-only lookup of public CVE metadata and citation.",
        "inputSchema": {"type": "object", "required": ["cve_id"], "properties": {"cve_id": {"type": "string"}}},
        "annotations": {"readOnlyHint": True, "destructiveHint": False},
    },
    {
        "name": "security_check_kev",
        "description": "Read-only check against the selected CISA KEV evidence boundary.",
        "inputSchema": {"type": "object", "required": ["cve_id"], "properties": {"cve_id": {"type": "string"}}},
        "annotations": {"readOnlyHint": True, "destructiveHint": False},
    },
    {
        "name": "security_triage_report",
        "description": "Run the citation-bound, read-only Security Triage workflow.",
        "inputSchema": {"type": "object", "properties": {"cve_ids": {"type": "array"}, "iocs": {"type": "array"}, "assets": {"type": "array"}}},
        "annotations": {"readOnlyHint": True, "destructiveHint": False},
    },
]


def call_tool(name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
    args = dict(arguments or {})
    provider = get_intel_provider()
    if name == "security_lookup_cve":
        return provider.lookup_cve(str(args.get("cve_id") or "").upper())
    if name == "security_check_kev":
        return provider.check_kev(str(args.get("cve_id") or "").upper())
    if name == "security_triage_report":
        return run_triage(args)
    raise KeyError(f"unknown security tool: {name}")


def mcp_tools_list() -> dict[str, Any]:
    return {"tools": TOOL_DEFINITIONS, "read_only": True}


def mcp_tools_call(name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"content": [{"type": "text", "text": json.dumps(call_tool(name, arguments), ensure_ascii=False)}]}
