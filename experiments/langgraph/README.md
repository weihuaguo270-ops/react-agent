# LangGraph 版本 — 框架对照路径

`experiments/langgraph/` 用 **LangChain + LangGraph** 实现与 Core 平行的编排路径。  
用来理解图模型 / checkpoint / HITL；**不是**「第二套手写拷贝」，也**不是**默认唯一正确写法。

## 设计思路

```
Core（src/react_agent/）              LangGraph（experiments/langgraph/）
─────────────────────────            ─────────────────────────────────
过程式 ReAct 循环                      StateGraph（call_model ⇄ tools）
直接 LLM API                           ChatOpenAI（复用 llm_config.json）
TOOL_REGISTRY                          @tool + bind_tools
Harness 过程式插桩                     节点前后插桩（Format B, source=graph）
ToolGuard / safety                     retry_call + HITL / gate demo
                                       MemorySaver + thread_id
```

两条路径**不共享实现代码**，对齐的是 `llm_config.json` 与 **Harness Format B**，便于对比「机制在哪一层」。

## 无 Key 框架 Demo（优先）

```bash
pip install -e ".[langgraph]"
python experiments/langgraph/demo_checkpoint_hitl.py
```

展示：条件边、HITL gate、同 `thread_id` 检查点续跑。

## 完整 Agent（需 API Key）

```bash
pip install -e ".[langgraph]"
python experiments/langgraph/graph/main.py "用计算器算 1+1"
```

或在代码中：

```python
from agent import run  # 在 graph/ 目录下，或自行调整 sys.path

print(run("用计算器算 1+1", thread_id="demo"))
```

`run(..., hitl=...)` 可将 `safety.HumanInTheLoop` 传入 tools 节点。

## 模块映射

| 能力 | LangGraph 文件 | 说明 |
|------|----------------|------|
| Agent 运行时 | `graph/agent.py` | StateGraph + MemorySaver |
| 框架 Demo | `demo_checkpoint_hitl.py` | 无 Key：图边 / checkpoint / HITL |
| 工具 / HITL | `graph/tools.py` · `graph/safety.py` | `@tool` + 权限审批 |
| 轨迹 | `graph/harness/recorder.py` | Format B，`schema_version=1` |
| 其他 | context / memory / mcp / rag / orchestrator | 可选旁路 |

## 契约测试

```bash
pytest tests/test_langgraph_harness_contract.py -q
```

## 配置

复用顶层 `llm_config.json` 和 `.env`。完整 Agent 需要可用的 LLM API Key。
