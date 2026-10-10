# Changelog

## Unreleased

### Changed

- Replaced the misleading `examples/` umbrella with honest top-level layout:
  `demos/` (product demos), `scripts/eval/<category>/` (CI/local eval entrypoints
  split into execution, reliability, docs, rag, failure, acceptance, smoke, publish,
  integration), and merged former `examples/fixtures/` into root `fixtures/` alongside
  existing corpora. Workflows, docs, and tests now point at the new paths.

### Removed

- Dropped the optional LangGraph twin under `experiments/langgraph/` (extra `[langgraph]`, harness contract test, and docs that framed it as a framework comparison). Task decomposition and sequencing stay on Planner + Orchestrator + `react_loop` / self-built workflow.

- Dropped the frozen GSM8K×10 + HotpotQA×10 **public Agent benchmark** suite
  (`public_benchmark.py` / `public_benchmark_subset.json` / `run_public_benchmark.py` /
  CI Pillar ③ offline step and related snapshots). Offline CI only exercised the gold-derived
  matcher and did not measure agent ability. Shared HotpotQA-style text matching for the
  remaining public RAG suite lives in `eval/answer_match.py`.

### Added

- `/v1/chat/stream` now behaves the same on both HTTP surfaces. The FastAPI entry point used
  to run the chat handler to completion and then emit a single terminal `completed` event, so
  the event table `DEPLOY.md` documents for this endpoint (`runtime`, `step`, `tool_call` /
  `tool_result`, `answer_delta`, `answer`, `trajectory`, `result` / `error`, `cancelled`,
  `heartbeat`, `done`) only ever held for the stdlib surface, and its frames carried no `id:`.
  It now runs the handler on a worker thread that installs the request-local event sink, hands
  events to the ASGI stream through `loop.call_soon_threadsafe`, emits `heartbeat` when idle
  (`streaming.HEARTBEAT_SECONDS`, default 10s), turns an `LLMCancelled` into `cancelled` +
  `done {status: 499}`, and sets the request cancel signal when the generator is reclaimed so a
  disconnected client actually stops the agent instead of burning LLM calls. The terminal event
  is now the documented `done` (the undocumented `completed` is gone), and the `GET
  /v1/chat/stream` query-parameter form exists on both surfaces. Frame construction and
  query-parameter parsing moved into `server/streaming.py` (`sse_frame`, `query_body`) so the
  two surfaces cannot drift again; `tests/test_stream_surface_parity.py` drives the real stdlib
  endpoint and the FastAPI ASGI app through one parser and one event-vocabulary assertion.

- The FastAPI surface (the container's default `react-agent-api` entry point) now implements
  the async approval chain `DEPLOY.md` already documented for it: `GET /v1/approvals`,
  `POST /v1/approvals/{approval_id}`, an `awaiting_approval` + `approval_id` response when a
  CONFIRM-level tool is gated, and an `approval_required` SSE event on `/v1/chat/stream`.
  The request-scoped context (`set_request_id`, `set_approval_credential`) and the approval
  capture now run inside the same threadpool call as the chat handler: the pending signal is a
  ContextVar, so capturing it across the `run_in_threadpool` boundary always returned `None`
  and the default entry point could never surface an `approval_id`.
  `tests/test_fastapi_async_approvals.py` drives the whole loop over HTTP (including the
  consumed-once and session-grant paths) and fails if the capture moves back outside that
  boundary.

### Fixed

- The FastAPI surface — the container's default `react-agent-api` entry point — now shares
  `server/auth.py` for authentication and Host-header validation instead of reading its own
  `REACT_AGENT_API_KEY`. Following `DEPLOY.md` and setting `REACT_AGENT_AUTH_TOKEN` therefore
  left the default entry point unauthenticated, and it performed no Host validation at all, so
  the documented DNS-rebinding defence and the `REACT_AGENT_REQUIRE_HOST_ALLOWLIST=1`
  fail-closed startup check only ever applied to the stdlib surface. `REACT_AGENT_API_KEY` is
  kept as a legacy alias (`REACT_AGENT_AUTH_TOKEN` wins), `X-Api-Key` and constant-time
  comparison now work on both surfaces, `main()` runs the same startup validation and exposure
  warning, and every non-probe path requires credentials as `DEPLOY.md` already stated.
  `tests/test_server_surface_parity.py` runs one contract matrix against both entry points so
  the two cannot drift apart again.
- Failure-regression suite (`pipeline`, `gate`, `contracts`, `software-task`, `closed-loop`
  decision) now runs against trace-debugger's v0.6.0 failure-gate export —
  `build_failures_export`, `build_scan_snapshot(task_type=...)` and `approval_denied`
  detection — which is on the sidecar's default branch that CI installs.
- `tests/test_collect_repair_evidence.py` no longer seeds from `artifacts/software-tasks`,
  which only exists after a real Docker SoftwareTaskRunner run. The same layout is committed
  as compact fixtures under `fixtures/software_tasks/repair_evidence/`, so the test
  passes on a clean checkout instead of failing in CI.
- `GitHubDeliveryWorkflow` runs candidate tests with `PYTHONDONTWRITEBYTECODE=1`. CPython keys
  `.pyc` validity on (source mtime in whole seconds, size), so a candidate that rewrites a file
  to the same size within the same second could be tested against the *previous* candidate's
  bytecode — the repair-loop delivery test flaked between two runs of the same commit
  (`repair_failed` vs `shadow_passed`).
- `scripts/eval/failure/run_failure_flywheel.py`, `run_step_watcher_evidence.py` and
  `run_flywheel_closed_loop.py` resolve the trace-debugger **source** checkout from the
  importable package (`pip install -e /tmp/trace-debugger` in CI) with
  `REACT_AGENT_TDEBUG_ROOT` and sibling-directory fallbacks, instead of assuming
  `../trace-debugger`. The flywheel CI step failed with `轨迹目录不存在` and the StepWatcher
  evidence step silently published `golden_suite_pass_rate: null`.

## 0.9.0 (2026-08-14)

### Added

- Controlled GitHub delivery workflow with isolated clones, real test execution, shadow mode,
  plan-bound approval, idempotency, audit records, candidate commits, and explicit Draft PR writes
- Public GitHub portfolio dataset with repository-isolated dev/golden/held-out splits and source evidence
- HTTP reliability runner and portable local evidence paths
- EvaluationEpisode export for release gates and trajectory failure analysis

### Changed

- Production maturity and application-direction documents now distinguish `local_real` evidence from
  unverified external GitHub writes
- Sandbox and runtime artifact paths fail closed or resolve through portable data directories

### Verified

- Offline release regression: 193 passed, 3 skipped, 9 live tests deselected
- GitHub delivery and dataset regression: 11 passed
- Delivery Episode accepted by llm-eval-engine and trace-debugger
- Live LLM exploratory run: 201 passed, 3 skipped, 1 nondeterministic consistency failure

### Documentation

- Aligned the docs troubleshooting default path with the current offline Agent runner
- Updated the production maturity matrix for tool-sequence and business-state evaluation
- Replaced the retired transformer repository link with `llm-inference-pipeline`
## 0.8.0 (2026-08-12)

### Added

- Portable user-data directories for Memory, RAG, trajectories, reports, and app indexes
- Deterministic expense evaluation with dev/golden/held-out splits and Episode v1 export
- Historical evidence paths normalized to `${WORKSPACE_ROOT}`
- Explicit LangGraph environment isolation through the JSON protocol boundary
- Linux and Windows portability checks

### Verified

- Full local regression: 177 passed, 3 skipped
- Portable path and sandbox regression: 27 passed

## 0.7.0 (2026-08-12)

### Added

- Container sandbox backend for untrusted tool execution with rootless runtime support
- Fail-closed `container + required` production mode and readiness reporting
- Per-call tool allowlist, stdin protocol, structured runner envelope, and input/output limits
- Hardened sandbox image: non-root user, read-only root, dropped capabilities, no-new-privileges,
  default-deny network, tmpfs, CPU, memory, PID, and file descriptor limits
- Unified required-mode tool boundary for ReAct, workflow, docs troubleshooting, and execution eval
- Security regression suite and deployment threat-model documentation

### Changed

- Unknown tools are treated as untrusted; process mode is explicitly documented as crash/timeout
  isolation rather than a security boundary
- Strict container mode blocks direct host MCP access until an isolated broker is configured
- Permission confirmation fails closed when production required mode has no HITL callback
- Fault and production evaluation report tool-boundary and sandbox failures separately

### Verified

- Local security regression: 15 passed
- Full local regression: 180 passed, 3 skipped
- Docker sandbox path validated for identity, seccomp, filesystem, secrets, network, resource

## 0.6.0 (2026-08-11)

### Added

- Harness 轨迹支持 input_artifacts、output_artifacts 和步骤级 artifacts
- Trajectory 新增输入、输出和步骤 Artifact 记录接口
- Format B Schema 增加图片、视频、音频和文档引用字段
- Artifact 契约测试覆盖合法引用和 data/base64 内嵌内容拒绝

### Changed

- Recorder 仅保存 Artifact 白名单元数据，避免媒体二进制进入轨迹
- README 补充 Artifact 记录范围和评测职责边界

## 0.5.2 (2026-08-04)

### Fixed
- **docker-smoke**：`run_deploy_smoke.py` 在未 `pip install` 的宿主机上可导入（`sys.path` + `PYTHONPATH=src`）

## 0.5.1 (2026-08-03)

### Added — Pillar ① HTTP smoke

- **`run_execution_http_smoke.py`**：execution 子集经 `POST /v1/chat app=default`
- **`REACT_AGENT_SERVER_OFFLINE_REACT=1`**：离线 ReAct smoke（deploy / docker-smoke，无 API Key）
- **`offline_react.py`** + `http_execution.py`；docker-smoke 启用 offline_react

### Fixed

- **git docs eval 5/5**：git01（对外名称）、git03（Core 架构）检索/合成修复
- `lookup_api` 跳过架构/评测类 meta 问题；`draft` 补充 CORE_ARCHITECTURE 检索

### Changed

- `APPLICATION_DIRECTION.md`：v0.5 已完成项同步，更新各 pillar 待办

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

## 0.4.0 (2026-08-03)

### Added — Agent 默认路径与交付

- **`agent_runner`**：离线 Agent 循环（观测驱动选工具 → 强制 `verify_citations` → Harness 轨迹）；默认引擎
- **产品 UI**：`GET /`、`/ui` — 证据链、拒答状态、结构化 diagnosis、Agent 工具步；`GET /v1/info`
- **Docker 交付**：`Dockerfile`、`docker-compose.yml`、`docs/DEPLOY.md`；`/ready` 就绪探针
- **部署自检**：`scripts/eval/smoke/run_deploy_smoke.py`；CI `docker-smoke` job
- **HTTP**：`/v1/chat` 支持 `log_excerpt`、`trace_context`；返回 `agent_steps`、`engine`

### Changed

- 黄金集 eval 默认路径：`agent`（原 `workflow` 仍可用）
- 架构/成熟度文档：评判基准改为 **主流 ReAct + 工具 + HTTP**

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
