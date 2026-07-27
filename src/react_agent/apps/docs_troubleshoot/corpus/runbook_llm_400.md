# Runbook：LLM 调用失败 HTTP 400

常见原因：

1. **模型名退役**：`deepseek-chat` / `deepseek-reasoner` 已于 2026-07-24 退役，应使用 `deepseek-v4-flash`。deepseek-chat 不能继续当默认模型。
2. **空 tools 数组**：请求里 `tools: []` 可能导致部分供应商 400；禁用工具时应省略 `tools` 字段。
3. **thinking 多轮丢 reasoning_content**：启用 thinking 时，assistant 消息须回传 `reasoning_content`。

排查顺序：检查 `LLM_MODEL` → 检查请求体是否含空 tools → 查看错误响应体中的 `message`。
