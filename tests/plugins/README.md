# 插件功能测试

测试可选的插件功能，这些功能默认不在核心运行时中启用。

## 结构

- `test_mcp_mock.py` - MCP mock 实现测试
- `test_mcp_stdio_contract.py` - MCP stdio 协议契约测试
- `test_tot.py` - Tree-of-Thought 推理测试（如果存在）
- `test_dashboard.py` - Dashboard UI 测试（如果存在）

## 可用插件

| 插件 | 测试文件 | 说明 |
|------|---------|------|
| MCP | `test_mcp_*.py` | Model Context Protocol 集成 |
| ToT | `test_tot.py` | Tree of Thought 推理 |
| Dashboard | `test_dashboard.py` | Web UI 可视化 |

**注意**: RAG 和 Orchestration 插件的测试分别在 `tests/rag/` 和 `tests/core/` 中。

## 运行测试

```bash
# 运行所有插件测试
pytest tests/plugins/ -v

# 运行特定插件测试
pytest tests/plugins/test_mcp_mock.py -v
pytest tests/plugins/test_mcp_stdio_contract.py -v
```

## 启用插件

这些功能通过 `REACT_AGENT_PLUGINS` 环境变量控制：

```bash
# 启用所有插件
set REACT_AGENT_PLUGINS=1

# 启用特定插件
set REACT_AGENT_PLUGINS=mcp,tot,dashboard

# 或使用单独的配置
set REACT_AGENT_MCP_MOCK=1
```

详见 `docs/PLUGINS.md`。

## 注意

- 插件功能默认不在核心运行时中加载（懒加载）
- 部分插件可能需要额外的依赖（如 RAG 的语义模式需要 `[rag]` 依赖）
- "插件"不等于"不稳定"，只是表示可选和按需启用

## 术语更新

本目录之前名为 `tests/experimental/`，已重命名为 `tests/plugins/` 以更准确地反映这些功能的性质。

旧环境变量 `REACT_AGENT_EXPERIMENTAL_TOOLS` 仍然有效（向后兼容），但推荐使用新变量 `REACT_AGENT_PLUGINS`。
