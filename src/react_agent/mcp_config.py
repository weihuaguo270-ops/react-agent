"""从配置加载 MCP Server 启动命令，避免硬编码本机路径。"""
from __future__ import annotations

import json
import os
from typing import Optional


# 默认命令必须可移植，不包含操作系统相关的绝对路径。
PORTABLE_DEFAULT_MCP_SERVERS: list[list[str]] = [
    ["uvx", "mcp-server-time"],
]


def load_mcp_server_configs(config_path: Optional[str] = None) -> list[dict]:
    """Load stdio and remote MCP definitions in one normalized shape.

    Backwards-compatible list/string entries remain stdio commands.  Remote
    entries use ``{"transport": "streamable_http", "url": "..."}`` and may
    reference a bearer token through ``token_env`` rather than storing secrets
    in the JSON configuration.
    """
    if os.environ.get("REACT_AGENT_DISABLE_MCP", "").strip().lower() in (
        "1", "true", "yes", "on",
    ):
        return []

    candidates = [config_path] if config_path else []
    candidates.extend(_candidate_config_paths())
    for path in candidates:
        if not path or not os.path.isfile(path):
            continue
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError) as exc:
            print(f"  [MCP] 配置不可用 ({path}): {exc}")
            continue
        servers = data.get("servers") if isinstance(data, dict) else None
        if not isinstance(servers, list) or not servers:
            continue
        configs: list[dict] = []
        for entry in servers:
            if isinstance(entry, list) and entry and all(isinstance(x, str) for x in entry):
                configs.append({"transport": "stdio", "command": entry[0], "args": entry[1:]})
            elif isinstance(entry, str) and entry.strip():
                parts = entry.split()
                configs.append({"transport": "stdio", "command": parts[0], "args": parts[1:]})
            elif isinstance(entry, dict):
                transport = str(entry.get("transport", "")).strip().lower()
                url = entry.get("url")
                if transport in {"streamable_http", "streamable-http", "http", "sse"} and isinstance(url, str) and url:
                    item = dict(entry)
                    item["transport"] = "streamable_http"
                    configs.append(item)
        if configs:
            print(f"  [MCP] 已加载配置: {path} ({len(configs)} server)")
            return configs

    return [
        {"transport": "stdio", "command": command[0], "args": command[1:]}
        for command in PORTABLE_DEFAULT_MCP_SERVERS
    ]


def _candidate_config_paths() -> list[str]:
    paths: list[str] = []
    env = os.environ.get("REACT_AGENT_MCP_CONFIG", "").strip()
    if env:
        paths.append(env)
    # 依次检查项目根目录和当前工作目录，与 llm_config.json 的查找方式一致。
    here = os.path.dirname(os.path.abspath(__file__))
    root = os.path.abspath(os.path.join(here, "..", ".."))
    paths.append(os.path.join(root, "mcp_servers.json"))
    paths.append(os.path.join(os.getcwd(), "mcp_servers.json"))
    return paths


def load_mcp_server_commands(
    config_path: Optional[str] = None,
) -> list[list[str]]:
    """返回各 MCP Server 的 argv 命令列表。

    配置解析顺序：
      1. 显式传入的 ``config_path``
      2. 环境变量 ``REACT_AGENT_MCP_CONFIG``
      3. 项目根目录或当前工作目录中的 ``mcp_servers.json``
      4. 可移植默认命令（仅 ``uvx mcp-server-time``）

    JSON 结构::
        {"servers": [["uvx", "mcp-server-time"], ["npx", "-y", "..."]]}

    设置 ``REACT_AGENT_DISABLE_MCP=1`` 可禁用全部 MCP，供确定性评测使用。
    """
    if os.environ.get("REACT_AGENT_DISABLE_MCP", "").strip().lower() in (
        "1", "true", "yes", "on",
    ):
        return []

    candidates = [config_path] if config_path else []
    candidates.extend(_candidate_config_paths())

    for path in candidates:
        if not path or not os.path.isfile(path):
            continue
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError) as e:
            print(f"  [MCP] 配置不可用 ({path}): {e}")
            continue
        servers = data.get("servers") if isinstance(data, dict) else None
        if not isinstance(servers, list) or not servers:
            print(f"  [MCP] 配置缺少 servers 列表: {path}")
            continue
        out: list[list[str]] = []
        for entry in servers:
            if isinstance(entry, list) and entry and all(isinstance(x, str) for x in entry):
                out.append(list(entry))
            elif isinstance(entry, str) and entry.strip():
                out.append(entry.split())
        if out:
            print(f"  [MCP] 已加载配置: {path} ({len(out)} server)")
            return out

    return [list(cmd) for cmd in PORTABLE_DEFAULT_MCP_SERVERS]
