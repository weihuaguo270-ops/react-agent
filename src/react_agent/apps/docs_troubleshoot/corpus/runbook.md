# 内部排障 Runbook

## LLM 调用失败 HTTP 400

常见原因：

1. **模型名退役**：`deepseek-chat` / `deepseek-reasoner` 已于 2026-07-24 退役，应使用 `deepseek-v4-flash`。
2. **空 tools 数组**：请求里 `tools: []` 可能导致部分供应商 400；禁用工具时应省略 `tools` 字段。
3. **thinking 多轮丢 reasoning_content**：启用 thinking 时，assistant 消息须回传 `reasoning_content`。

排查顺序：检查 `LLM_MODEL` → 检查请求体是否含空 tools → 查看错误响应体中的 `message`。

## 权限闸门拦截工具

若观测到 `blocked by permission gate`：

- DENY 工具默认不可执行（如 `delete_directory`）
- CONFIRM 工具在严格模式（`REACT_AGENT_STRICT_CONFIRM=1`）下无 HITL 会拦截
- 关闭闸门仅用于调试：`REACT_AGENT_PERMISSION_GATE=0`（生产向部署禁止默认关闭）

## RAG 无命中

- 确认语料已 ingest；空库会提示文档库为空
- CI / 离线优先 `REACT_AGENT_RAG_MODE=keyword`
- 语义检索需 `pip install -e ".[rag]"`；失败应回退关键词

## MCP 连接失败

- 真服务器依赖本机 `uvx` / `npx`
- 评测与服务模式建议 `REACT_AGENT_DISABLE_MCP=1` 或 `REACT_AGENT_MCP_MOCK=1`
- Mock 仅用于协议冒烟，不代替生产 MCP 进程治理

## 轨迹与复盘

- 默认导出 Format B（`schemas/harness_trajectory.schema.json`）
- 失败分类交给 trace-debugger；过程奖励交给 llm-eval-engine
- 相邻完全相同工具调用默认拦截（`REACT_AGENT_BLOCK_DUPLICATE_TOOLS`）
