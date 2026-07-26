# API 快速入门

## 配置 API Key

在项目根目录创建 `.env`，设置：

```
LLM_PROVIDER=deepseek
DEEPSEEK_API_KEY=sk-xxxx
```

也可用 `llm_config.json`。`.env` 会覆盖系统环境中残留的旧 Key。

## 调用约定

- 工具调用使用 OpenAI Function Calling JSON Schema
- 轨迹默认导出 Format B（`schemas/harness_trajectory.schema.json`）
- 评测路径建议 `REACT_AGENT_DISABLE_MCP=1` 以保证可复现
