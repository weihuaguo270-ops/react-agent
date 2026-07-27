"""MCP mock Demo：证明工具发现 / Schema 合并 / call_tool，无需 uvx。

用法:
  set REACT_AGENT_MCP_MOCK=1
  python examples/demos/demo_mcp_mock.py

接入 CLI:
  set REACT_AGENT_MCP_MOCK=1
  python -m react_agent.react_loop --help
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from react_agent.mcp_client import MockMCPClient


def main():
    with MockMCPClient() as c:
        c.connect()
        c.discover_tools()
        defs = c.to_tool_definitions()
        print("\n=== OpenAI tool definitions (excerpt) ===")
        print(json.dumps(defs[0], ensure_ascii=False, indent=2)[:400], "...")
        print("\n=== call_tool ===")
        print(c.call_tool("get_current_time", {"timezone": "Asia/Shanghai"}))
        print(c.call_tool("echo_note", {"text": "mcp protocol ok"}))
    print("\n与 Core 合并点: react_loop 将 MCP defs 并入 TOOL_DEFINITIONS，执行时按名路由 call_tool。")


if __name__ == "__main__":
    main()
