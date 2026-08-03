# Changelog

## Unreleased

### Added
- **Pillar ① HTTP smoke**：`run_execution_http_smoke.py` — execution 子集经 `POST /v1/chat app=default`
- **`REACT_AGENT_SERVER_OFFLINE_REACT=1`**：离线 ReAct smoke（deploy / docker-smoke，无 API Key）

## 0.5.0 (2026-08-03)

### Added — 多应用 HTTP 与三类主流应用定位

- **`/v1/chat` 多应用路由**：`app=default|docs_troubleshoot|expense`（`chat_router` + handlers）
- **`expense` 应用**：离线政策检索 + 规则裁决 demo（`apps/expense/offline_answer.py`）
- **`GET /v1/info`**：返回 `applications` 列表与 `pillars`（coding_execution / support_automation / rag_research）
- **文档**：`docs/APPLICATION_DIRECTION.md` — 编码/执行 · 客服/自动化 · RAG/研究 三类映射

### Changed

- 产品定位：repo = Agent 运行时 + 三类主流应用；`docs_troubleshoot` 降为 ② 客服/自动化 垂直 demo
- 默认环境变量：`REACT_AGENT_DEFAULT_APP`（替代 `REACT_AGENT_APP` 作为 HTTP 默认）
- CI：按 pillar 标注 execution / docs troubleshoot / public benchmark 步骤
- 部署自检：expense app + `/v1/info` applications 断言

### Tests

- `tests/test_expense_app.py` — 规则裁决 + HTTP 路由
- `tests/test_server_http.py` — 多应用 info 断言


### Added — Agent 默认路径与交付

- **`agent_runner`**：离线 Agent 循环（观测驱动选工具 → 强制 `verify_citations` → Harness 轨迹）；默认引擎，`REACT_AGENT_DOCS_ENGINE=workflow` 可回退 legacy DAG
- **产品 UI**：`GET /`、`/ui` — 证据链、拒答状态、结构化 diagnosis、Agent 工具步；`GET /v1/info`
- **Docker 交付**：`Dockerfile`、`docker-compose.yml`、`docs/DEPLOY.md`；`/ready` 就绪探针（docs 索引 `chunks > 0`）
- **部署自检**：`examples/eval/run_deploy_smoke.py`；CI `docker-smoke` job
- **HTTP**：`/v1/chat` 支持 `log_excerpt`、`trace_context`；返回 `agent_steps`、`engine`、`trajectory_id`

### Changed

- 黄金集 eval 默认路径：`agent`（原 `workflow` 仍可用）
- `offline_answer` / `POST /v1/chat` 离线默认走 Agent 循环
- 架构/成熟度文档：评判基准改为 **主流 ReAct + 工具 + HTTP**（不以 LangGraph 为 KPI）
- README：默认叙事从 Workflow DAG 调整为 Agent 循环 + Live `react_loop`

### Tests

- `tests/test_docs_troubleshoot_agent.py` — Agent 步序、拒答、现场证据
- `tests/test_server_http.py` — `/`、`/v1/info`、health/ready

## 0.3.0 (2026-07-27)

### Added — 证据化文档排障（docs_troubleshoot）

- **Workflow v5**：现场证据 → 检索 → 句级合成 → 引用/拒答 → 结构化诊断
- **现场证据**：HTTP 错误、请求头、日志片段、Trace JSON；`trace_id` 自动拉取（mock / MCP）
- **结构化诊断**：`cause_rules` + `cause_infer`（文档推断）、`schemas/diagnosis.schema.json`
- **fix_steps 权限闸门**：可执行修复进 `pending_fix_steps`（`apply_fix_step` CONFIRM）；破坏性步骤拦截
- **资料 ingest**：递归目录、Git `ls-files`、OpenAPI `$ref`、增量 manifest
- **起草**：`synthesize.py` 句级要点合成（替代硬拼接片段）

### Eval（CI 四门禁）

| 套件 | 规模 |
|------|------|
| golden | 34 |
| fault_sim | 12（含 log / trace 场景） |
| production_blind | 5（外部 fixtures 语料） |
| git_docs_held_out | 5（本仓库 `docs/` via Git ingest） |

- 指标：`root_cause_hit_rate`、`evidence_sufficiency_rate`、`wrong_suggestion_rate`
- 脚本：`run_fault_eval.py`、`run_production_eval.py`、`run_git_docs_eval.py`
- Trace MCP：`fixtures/docs_troubleshoot/mcp_trace_server.py` + `REACT_AGENT_TRACE_BACKEND=mcp`

### Changed

- `draft.py` / `ranking.py`：证据扩展 query、domain boost（含 git/prod 语料）
- `permissions.py`：注册 `apply_fix_step`、`fetch_trace`
- HTTP `/v1/chat`：支持 `error_response` / `trace_id`，返回 `diagnosis`

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
