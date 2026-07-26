# Changelog

## Unreleased

（下一批变更写在这里。）

## 0.2.0 (2026-07-26)

### Added
- **权限闸门**：deny → ask → allow（`safety/permissions.py` + `permission_gate.py`），在沙箱前强制评估；与进程沙箱分层说明
- **Context LLM 接线**：`CONTEXT.manage(..., llm_call=)`；离线 `demo_context.py` + `tests/test_context_manage.py`
- **RAG 关键词离线路径**：`REACT_AGENT_RAG_MODE=keyword`；`fixtures/rag_corpus` + `demo_rag.py`
- **业务多步 Demo**：报销政策检索与裁决 `demo_expense_workflow.py`
- **MCP mock**：`MockMCPClient` / `REACT_AGENT_MCP_MOCK=1`；`demo_mcp_mock.py`
- **工作流文档**：`docs/AGENT_WORKFLOW.md`
- **LangGraph 对照**：Core + twin 叙事；`experiments/langgraph/demo_checkpoint_hitl.py`；Format B 契约测试
- **P2 跨仓版本化**：`SCHEMA_VERSION` / `EVAL_API_VERSION`；缺省轨迹兼容 major `1`
- **Core 懒加载**：`react_loop` 不再顶层导入 MCP / Orchestrator / RAG
- **tdebug↔eval 契约**：`tests/test_tdebug_eval_contract.py`（integration CI）
- **公开 Agent benchmark 子集**：GSM8K×10 + HotpotQA×10；`run_public_benchmark.py` + offline CI
- Execution-based 离线任务集与 **Agent 端到端 execution**（公开 36/36）
- Harness 可靠性注入 / Live 可靠性 ON/OFF；失败飞轮与真闭环（`llm_offtrack` 6→1）
- **收尾强制 FINAL ANSWER**；Windows 控制台安全输出；日烟 `daily-smoke` 方差日志

### Changed
- DeepSeek 默认模型：`deepseek-chat` → **`deepseek-v4-flash`**（旧名自动映射；`LLM_THINKING=disabled`）
- Core 收窄：默认工具表去掉 RAG/ToT/Dashboard；实验能力见 `docs/EXPERIMENTAL.md`
- 空 `tools:[]` 不再写入请求体；HTTP 错误带响应体；400 不重试

### Infrastructure
- CI：coverage / mypy / pip-audit；`windows-latest`；Real LLM smoke 使用 v4 模型环境变量

## 0.1.0 (2026-07-13)

### Added
- Capability 评测：`capability_scorer` + `capability_dataset.json`（准确率/工具/推理/一致性/幻觉）
- `python -m react_agent` / `python -m react_agent.eval` 入口
- 真实 LLM 集成测试（无 Key 时 skip）与 Agent→Eval 对接示例

### Changed
- README 降调为学习实现；沙箱防递归；`.env` 优先加载 API Key
- 项目从 handwritten-react-agent 更名为 react-agent（历史）

### Infrastructure
- GitHub Actions CI（lint + test + eval-engine 集成校验）
