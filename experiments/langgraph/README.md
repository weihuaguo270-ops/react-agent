# LangGraph 版本 — 框架实现

`experiments/langgraph/` 将 Agent 核心能力用 **LangChain + LangGraph** 重新实现。

## 设计思路

```
核心运行时（src/）            LangGraph 版（experiments/langgraph/）
─────────────────────       ─────────────────────────────────────
ReAct Loop                   StateGraph（call_model ⇄ tools）
LLM API 调用                 ChatOpenAI（复用 llm_config.json）
工具注册                     @tool 装饰器
字符串 prompt 构建           角色模板 + SystemMessage
执行沙箱                     harness/sandbox.py
轨迹录制                     harness/recorder.py
```

两者**不共享代码**——LangGraph 版从零实现，只在配置层（`llm_config.json`）和轨迹文件格式上保持一致，便于两种架构的对比。

## 模块映射

| 核心模块 | LangGraph 文件 | 说明 |
|---------|---------------|------|
| Agent 运行时 | `graph/agent.py` | StateGraph 定义，call_model ⇄ tools 循环 |
| 上下文管理 | `graph/context.py` | 角色注入、CoT 策略 |
| 工具注册 | `graph/tools.py` | 内建工具集的 @tool 封装 |
| MCP 工具 | `graph/mcp.py` | MCP Client 集成 |
| RAG | `graph/rag.py` | 检索增强生成 |
| 记忆 | `graph/memory.py` | 对话记忆管理 |
| 多 Agent 编排 | `graph/orchestrator.py` | 任务分解 + Worker 并行 |
| 轨迹录制 | `graph/harness/recorder.py` | 完整执行录制 |
| 回放 | `graph/harness/replay.py` | 逐步骤回放 |
| 沙箱 | `graph/harness/sandbox.py` | 隔离执行 |
| Prompt 管理 | `graph/prompts.py` | 模板化 system prompt |

## 使用

```python
from experiments.langgraph.graph.main import create_agent

agent = create_agent()
result = agent.invoke({"input": "分析这份数据"})
print(result["output"])
```

## 配置

复用顶层 `llm_config.json` 和 `.env`，无需额外配置。
