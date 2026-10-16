# Harness 构建与统一契约 Spec

**状态：** Proposed  
**范围：** `react-agent` Core、运行时 Harness、评测 Harness 及其跨仓接口  
**目标：** 在不把所有模块物理搬到一个目录的前提下，将 Runtime Harness、Evaluation Harness 和 Shared Contracts 统一成可迁移、可验证的架构。

## 1. 背景与问题

项目已经具备 ReAct 循环、Workflow、工具注册表、MCP、权限闸门、Sandbox、轨迹记录、回放、评测 Runner、评分器和失败回归门禁。但这些能力分布在 `harness/`、`eval/`、`workflow/`、`tools/`、`safety/` 和服务入口中，存在以下问题：

- 正式 Format B 轨迹和 Workflow 的 “Format B-ish” 输出并存，协议边界不够严格。
- LLM 重试、工具超时、幂等和业务级 replay 没有统一策略接口。
- 结构化输出主要依赖各调用路径自行解析，缺少统一契约和失败分类。
- 评测 Runner、ReAct Agent、Workflow 以及它们对应的 HTTP Adapter/Runner 的采集方式不完全一致。
- “可回放”目前主要是轨迹展示，尚未定义带隔离环境和确定性工具结果的 replay 语义。

本 Spec 将这些问题拆为可独立验收的任务。它不把离线 fixture、mock 或本地容器结果提升为生产 SLA、安全认证或真实用户效果。

### 实施追踪

| Spec 项 | 状态 | 当前结果 / 剩余工作 |
|---|---|---|
| Phase 0 基线冻结 | Complete / frozen-clean-head-baseline | 已生成 [`HARNESS_BASELINE_20261014.md`](../evaluation/HARNESS_BASELINE_20261014.md)；HEAD clean archive 的 fixture 和聚焦测试已独立重跑，工作区候选结果单独留存 |
| Phase 1：Shared Contracts | Complete / compatibility-period | 已加入 `ToolCall`、`ArtifactRef`、`TaskEpisode`、`EvaluationEpisode`、`StopReason`、`harness-contracts/v1`、JSON Schema 和 contracts 级 `parse_trajectory()`；契约测试、依赖方向测试、README/迁移说明和 `harness-compatibility/v1` 矩阵已存在。旧 `harness.schema` 按兼容周期保留，禁止新代码新增直接依赖 |
| Shared trajectory serializer | Complete / compatibility-period | Workflow、ReAct Recorder、服务端 HTTP Adapter 和 HTTP Evaluation Runner 已调用共享 serializer；contracts 提供 `parse_trajectory()`、`normalize_trajectory()`、`validate_trajectory()` 单一迁移入口，旧 `harness.schema` 仅保留兼容实现和导出，最终删除延后到兼容周期结束 |
| RuntimeEpisode contract | Implemented in R3/R6 | `RuntimeEpisode` 已统一运行身份、停止原因、执行状态、基础运行指标和 Format B trajectory；本地 observability artifact、EvaluationEpisode 关联、脱敏、retention/exporter 和重建一致性校验已接入 |
| Workflow Format B Adapter | Mostly complete | `WorkflowResult.to_trajectory()` 通过共享 serializer 输出正式字段并保留旧 `schema` 标记；工具失败、权限拒绝和工作流拒绝已映射统一 `StopReason`，超时/取消等其他终止分支仍需补齐 |
| HTTP Adapter/Runner Format B | Mostly complete | HTTP 是 ReAct/Workflow 的传输和评测适配边界，不是第三种执行方式；HTTP 响应携带来源执行方式的正式 `trajectory`，HTTP Runner 保留服务端轨迹、`execution_mode` 和 `runtime_episode_id`；成功、超时、取消、权限拒绝、解析错误和工具错误分支均保留 RuntimeEpisode 关联 |
| 工具边界接入 ToolCall | Mostly complete | `execute_registered_tool()`、ReAct、Workflow、Evaluation 和真实/Mock MCP `call_tool()` 均已规范化参数；`ToolError` 共享错误信封、输出上限、超时和 ToolSpec 执行约束已有跨路径契约测试 |
| RetryPolicy / IdempotencyPolicy | Implemented / deployment opt-in | 非流式 LLM、MCP 请求和本地工具边界已接入策略；离线使用 `JsonIdempotencyStore`，生产配置使用 PostgreSQL 权威幂等记录和 Redis 完成结果缓存。共享 store 以 pending claim、lease 接管、唯一 key、payload hash 冲突拒绝和完成后缓存保证跨实例 replay；Redis 丢失回退 PostgreSQL，严格 exactly-once 外部副作用仍需业务工具自身幂等 |
| StructuredOutputContract | Complete / compatibility-period | `runtime.structured_output.StructuredOutputContract` 提供 provider 无关的 JSON/envelope 解析、JSON Schema/validator 校验、bounded repair、`parsed/invalid/missing/refused` 稳定状态和 `truncated` 失败分类；ReAct、Workflow、HTTP Adapter 可选接入同一契约，解析证据写入 Format B metadata，解析失败统一映射 `StopReason.PARSE_ERROR`。原始响应默认不保留，显式保留必须提供脱敏器 |
| Deterministic Replay | Complete / evidence collected | `runtime.replay.ReplayManifest` 固化轨迹、工具结果、模型响应、Fixture、协议版本和组件/总哈希；`DeterministicReplay` 提供 `record/replay/inspect`，replay 逐步消费记录的工具结果，默认拒绝网络与副作用，并通过 `ReplayLimits` 限制步骤、工具调用和输出大小；`replay-scoring-input/v1` 为 ReAct、Workflow、HTTP Runner 提供相同评分输入，Fixture 缺失、结果缺失或哈希不一致时 fail closed。`scripts/eval/smoke/run_docker_replay_evidence.py` 已在 `react-agent-sandbox:r5-replay` 中完成两次回放，步骤序列、停止原因和评分输入 SHA256 一致；容器隔离证据保存在本地 `.evidence_tmp/docker-replay-evidence-r5.json`。 |
| Phase 3：Evaluation 收敛 | Complete | Core `EvaluationEpisode`、`FixtureManifest` 和对应 JSON Schema 已加入；`FixtureBundle`、EvalRunner、execution offline/agent suite、SoftwareTaskRunner、public-RAG、reliability 注入/live/HTTP probe、Expense business/candidate、GitHub business/portfolio、acceptance inventory/materializer、Harness closed-loop、StepWatcher 和 failure flywheel 入口均生成 Episode、Format B trajectory artifact SHA256、fixture/batch 证据。待执行占位产物保持 evidence-only 且 `passed=null`；GitHub 数据标记为带哈希 live snapshot，不视为冻结题集；legacy loader 返回值保持兼容 |
| Phase 4：Baseline / repair / reverify | Partial | 失败门禁、repair/reverify、baseline compare 和 acceptance 汇总均输出共享 Episode、FixtureManifest、Format B artifact、fixture hash、artifact SHA256 与 phase-specific batch。历史采集、fixture materialization、真实复验分别标记 `historical_evidence`、`fixture_evidence`、`executed`；真实复验发生后 `reverified=true`，即使未通过也保留 review，只有实际验收条件通过才 decision=pass。Deterministic Replay 已支持 manifest 校验、记录工具结果逐步回放、资源预算、runner-neutral scoring input 和 Docker 隔离证据；跨仓 golden suite 的 Windows fixture/ACL 环境问题仍单独记录 |

## 2. 现状基线

| 能力 | 当前实现 | 基线结论 |
|---|---|---|
| 工具与 MCP | `src/react_agent/tools/`、`mcp_client.py`、`mcp_config.py` | 已有注册表和 MCP 协议；参数/超时/重试策略未统一 |
| 编排 | `react_loop.py`、`workflow/engine.py` | ReAct 和确定性 Workflow 均存在；尚无统一执行接口 |
| 模型接入 | `llm.py`、`prompts/`、SSE 流式路径 | provider、Function Calling、流式输出已存在；结构化输出契约不统一 |
| 记忆与上下文 | `memory.py`、`context.py`、RAG | 已有持久记忆和上下文裁剪；租户、并发和治理边界仍需外层补齐 |
| 权限与沙箱 | `safety/`、`harness/tool_boundary.py`、`harness/sandbox.py` | 已有权限闸门和 process/container 后端；process 不是完整安全边界 |
| 轨迹 | `harness/recorder.py`、`schema.py`、`replay.py` | Format B 记录、校验、脱敏和展示回放已存在 |
| 评测 | `eval/`、`scripts/eval/`、`fixtures/` | 题集、Fixture、Runner、评分、报告和失败回归已存在 |
| 跨仓闭环 | `harness_closed_loop.py`、StepWatcher、trace-debugger、eval-engine | 已有适配和门禁；`sibling_compatibility_report()` 记录版本、Contract 和依赖状态，缺失/不兼容依赖 fail closed |

## 3. 目标架构

概念上统一为 Harness 产品域；代码上分为三个边界：

```text
                     +----------------------+
                     | Shared Contracts     |
                     | ToolCall / Episode   |
                     | Trajectory / Artifact|
                     +----------+-----------+
                                ^
                 +--------------+--------------+
                 |                             |
       +---------+---------+         +---------+---------+
       | Runtime Harness   |         | Evaluation Harness|
       | tool/sandbox      |         | dataset/runner    |
       | orchestration     |         | scorer/regression |
       | model/context     |         | report/artifacts  |
       +-------------------+         +-------------------+
```

依赖规则：

1. Runtime Harness 依赖 Shared Contracts。
2. Evaluation Harness 依赖 Shared Contracts，并通过 Runtime Adapter 驱动运行时。
3. Runtime Harness 不依赖 Evaluation Harness。
4. ReAct Agent 和 Workflow 两种执行方式，以及它们对应的 HTTP Adapter/Runner，都必须通过统一的版本化 Contract 和 serializer 产出正式 Format B 轨迹。
5. 跨仓 `trace-debugger` 和 `llm-eval-engine` 只能通过版本化 Contract 接入，不能反向成为 Core Runtime 依赖。

建议目标目录：

```text
src/react_agent/harness/
  contracts/       # 共享数据结构、schema、版本和错误类型
  runtime/         # 工具边界、sandbox、recorder、replay、watcher adapter
  evaluation/      # dataset、fixture、runner、scorer、regression、report
  adapters/        # ReAct、Workflow、HTTP Adapter/Runner、trace-debugger、eval-engine
```

现有 `harness/*.py` 和 `eval/*.py` 不要求一次性搬迁。迁移期间保留兼容导出，新的代码只能依赖目标边界。

## 4. Shared Contracts

### 4.1 `ToolCall`

统一描述一次工具调用：

- `name: str`
- `arguments: str`，必须是 JSON 字符串；输入端可接受 object，归一化后只保留字符串形式
- `call_id: str | None`
- `attempt: int`
- `timeout_seconds: float | None`
- `idempotency_key: str | None`
- `source: runtime | evaluation | replay`

非法 JSON、未知工具、超出参数大小或不满足权限策略必须产生结构化错误，不得静默执行。

### 4.2 `TaskEpisode` / `EvaluationEpisode`

`TaskEpisode` 表示用户目标及完成边界，至少包括：

- `episode_id`
- `query`
- `acceptance_criteria[]`
- `split`: `dev | golden | held_out | production`
- `fixture_ref`
- `model_ref`、`tool_protocol_version`、`created_at`

`EvaluationEpisode` 在此基础上增加 runner、评分、artifact 和环境元数据。`held_out` 数据必须保持不可变，修改模型、服务或协议时新建 batch。

### 4.3 `RuntimeEpisode`

`RuntimeEpisode` 是运行时 Harness 的执行容器，表示一次实际 Agent 执行。它不等同于 Format B trajectory，也不等同于评测层的 `EvaluationEpisode`。建议至少包括：

- `runtime_episode_id`：一次运行的稳定 ID；可关联 `trace_id`、`session_id`、`run_id`
- `execution_mode`：`react | workflow`
- `transport`：`in_process | http | sse | subprocess`，HTTP/SSE 只描述承载方式
- `status`：`running | completed | failed | timeout | cancelled | refused`
- `stop_reason`：`completed | max_steps | timeout | cancelled | policy_denied | tool_error | parse_error`
- `trajectory`：由共享 serializer 生成的 Format B 记录
- `metrics`：耗时、token、重试次数、工具调用次数、拒绝/取消次数、估算成本
- `environment`：模型、工具协议、权限/sandbox、代码版本等运行信息

关系固定为：

```text
ReAct Agent / Workflow
        │  执行方式
        ▼
RuntimeEpisode
        ├── Format B trajectory
        ├── runtime status / StopReason / metrics
        └── HTTP or subprocess adapter metadata
        │
        ▼
EvaluationEpisode
        └── fixture / batch / score / evaluation artifacts
```

HTTP Adapter/Runner 负责把 HTTP 请求映射到 ReAct 或 Workflow，并携带 `execution_mode` 和 `runtime_episode_id`；它不是与 ReAct、Workflow 并列的 Agent 执行方式。

### 4.4 `Trajectory`

正式轨迹继续使用 `schemas/harness_trajectory.schema.json` 的 Format B：

- 顶层必须有 `session_id`、`query`、`steps`、`final_answer`
- `step` 必须从 1 开始且严格可解释
- 工具参数统一写入 `action.arguments`
- 支持 `task_episode_id`、`acceptance_criteria`、input/output/step artifacts
- 记录 `schema_version`、模型、耗时、估算 token 和来源
- 轨迹保存前完成脱敏；禁止嵌入 base64 或原始秘密

ReAct Recorder、Workflow 的 `to_trajectory()`，以及对应的 HTTP Adapter/Runner，必须通过同一个 serializer 生成该结构，禁止继续输出仅“Format B-ish”的私有字段。Trajectory 是 RuntimeEpisode 的步骤记录，不承担完整的运行状态、指标和环境容器职责。

### 4.5 `ArtifactRef` 与 `StructuredOutput`

Artifact 只保存 `id`、`media_type`、`uri`、`mime_type`、`sha256` 和受控 metadata，不把二进制内容嵌入轨迹。

结构化模型输出必须声明：

- `contract_name`、`contract_version`
- JSON Schema 或等价 validator
- parse 状态：`parsed | invalid | missing | refused`
- 原始响应是否可保留及脱敏规则

## 5. Runtime Harness 任务

### R1：工具协议和边界统一

交付物：

- `contracts/tool_call.py` 或等价模块
- Tool Registry、MCP、Workflow 工具调用统一转换为 `ToolCall`
- 参数校验、输出上限、超时和错误类型统一
- 现有 `execute_registered_tool()` 保留兼容入口

验收：同一个工具从 ReAct、Workflow、MCP mock、真实 MCP Server 和 Evaluation Runner 调用时，得到相同的规范化参数和错误结构；错误 envelope 的字段和分类保持一致，仅 `source` 标识调用路径。

### R2：统一 `RetryPolicy` 和 `IdempotencyPolicy`

交付物：

- 可配置 `RetryPolicy`：可重试错误、最大次数、退避、抖动、总预算
- 可配置 `IdempotencyPolicy`：key 来源、payload/hash 绑定、重复请求行为
- LLM 非流式请求、MCP 请求和可重试工具使用策略接口
- 流式响应已经产生增量后默认不得自动重试
- 业务工具可以声明 `none | safe | required` 幂等等级
- 生产部署：PostgreSQL 保存权威 key/payload/status/result，Redis 只缓存已完成结果并设置 TTL；缓存失效或不可用时回退 PostgreSQL

验收：注入超时场景能证明重试次数和退避符合策略；相同 key + 相同 payload 可 replay；相同 key + 不同 payload 必须拒绝；两个并发实例只能有一个 pending claim 执行；claim 过期后可由新实例接管；重复副作用不会再次执行。严格 exactly-once 外部副作用不由 Harness 单独宣称。

### R3：编排 Adapter

交付物：

- `ReactLoopAdapter`
- `WorkflowAdapter`
- `HttpRunnerAdapter`：将 HTTP 请求映射到 `ReactLoopAdapter` 或 `WorkflowAdapter`，不新增执行模式
- `RuntimeEpisode`：统一封装执行身份、执行状态、`StopReason`、Format B trajectory、运行指标和环境
- 统一停止原因：`completed | max_steps | timeout | cancelled | policy_denied | tool_error | parse_error`

验收：ReAct Agent、Workflow 两种执行方式各生成一个 `RuntimeEpisode`；它们及其 HTTP Adapter/Runner 都生成通过正式 Schema 的轨迹，`runtime_episode_id`、执行状态和停止原因可追溯；HTTP 结果必须标明被适配的执行方式，而不能被统计为第三种 Agent 类型。

### R4：`StructuredOutputContract`

交付物：

- provider 无关的结构化输出解析器
- schema 校验、重试/修复策略和失败分类
- 与工具调用解析分离
- 解析失败不得被当成业务成功

验收：有效 JSON、字段缺失、类型错误、模型拒答和截断响应分别得到稳定分类，并在轨迹中留证。

### R5：确定性 Replay

交付物：

- replay manifest：轨迹、工具结果、模型响应、Fixture、协议版本和哈希
- `record | replay | inspect` 三种模式
- replay 默认禁止真实网络和真实副作用
- 缺失 Fixture 时 fail closed

验收：同一 manifest 在隔离环境中产生相同的步骤序列、停止原因和评分输入；禁止把“展示轨迹”标记为“执行回放”。

### R6：Runtime 可观测性

交付物：

- 每次 `RuntimeEpisode` 的 trace/session/run 关联 ID，并能被 `EvaluationEpisode` 引用
- 工具调用次数、重试次数、耗时、token、估算成本、拒绝和取消计数
- JSON artifact 和可选日志/指标 exporter
- 敏感字段脱敏规则和 retention 配置

当前实现：`RuntimeObservability` 生成 `runtime-observability/v1` JSON artifact，保留
`runtime_episode_id`、`evaluation_episode_id`、`trace_id`、`session_id`、`run_id` 关联，
对已观测指标和 `unknown` 缺失值进行稳定序列化，并支持本地重建与可选 exporter；完整
生产指标采集和外部 exporter 仍属于后续工作。

验收：不依赖外部观测系统也能从本地 artifact 重建一次 `RuntimeEpisode`；字段缺失不能伪造为 0 或成功，运行时状态和停止原因必须与 trajectory、HTTP/Runner 结果一致。

## 6. Evaluation Harness 任务

### E1：题集和 Fixture 契约

交付物：

- 统一 `TaskEpisode` 数据集 schema
- fixture manifest、依赖版本、初始化命令、清理命令和数据哈希
- `dev/golden/held_out/production` 分区规则
- dataset version 和 batch id

验收：Runner 能拒绝缺少 acceptance、fixture 或版本信息的用例；held-out 结果不得混入 dev/golden 统计。

### E2：统一 Runner

交付物：

- offline tool、Agent subprocess、HTTP、软件任务 Runner 的共同接口
- 多轮交互、超时、取消、重试和轨迹采集统一
- 每次执行先生成 `RuntimeEpisode`，再由 Evaluation Runner 封装为 `EvaluationEpisode` 和 artifact manifest

验收：同一用例可切换 offline/agent/HTTP 模式；超时、进程错误和协议错误必须分别计数。

### E3：断言和评分分层

交付物：

- 规则断言：答案、工具、顺序、禁止工具、状态和文件差异
- LLM Judge Adapter：明确 prompt、版本、输出 schema 和 judge 状态
- 人工抽检导出格式
- `task_pass_rate`、`tool_success_rate`、`final_answer_rate`、Judge 指标分栏

验收：不能用工具成功率替代任务通过率；Judge 未运行必须是 `unobserved` 或 `not_run`，不能写成 0 分。

### E4：回归、报告和失败分类

交付物：

- baseline manifest 和 compare 规则
- `pass/review/hold` 决策及原因
- failure taxonomy、repair feedback、reverify linkage
- JSON、Markdown 和 artifact index

验收：失败优先于 review；baseline 相同可 pass；新增硬失败必须 hold；repair 后必须真实重跑并标记 `reverified=true` 才能转 pass。

### E5：跨仓 Adapter

交付物：

- trace-debugger 输入 Adapter
- llm-eval-engine Process Reward Adapter
- sibling 仓库缺失时的显式 `dependency_unavailable` 状态
- 版本兼容矩阵和契约测试

验收：跨仓工具只消费 Shared Contracts；缺失依赖不得静默跳过 P0 门禁；跨仓结果保留来源、版本和运行时间。

## 7. 实施顺序

### Phase 0：冻结基线

- 盘点现有入口、导入路径、Schema、报告和 CI 命令。
- 建立当前行为快照，不修改 held-out/golden 历史数据。
- 产出：`HARNESS_BASELINE.md`、入口矩阵、兼容性清单。

### Phase 1：Shared Contracts

- 建立 contracts 模块和版本常量。
- 为现有 Format B schema 增加 serializer/parser 的单一入口。
- 产出：Contract API、JSON Schema、迁移说明、契约测试。

### Phase 2：Runtime 收敛

- 接入 ToolCall、RetryPolicy、IdempotencyPolicy、StructuredOutputContract。
- 实现 `RuntimeEpisode`，为 ReAct Agent、Workflow 和 MCP 增加 Runtime Adapter；HTTP Adapter/Runner 只负责承载并关联 ReAct/Workflow 的 RuntimeEpisode。
- 统一 `runtime_episode_id`、`trace_id`、`session_id`、`run_id` 的关联规则，以及 status、StopReason、metrics 和 environment 字段。
- 产出：运行时统一错误、停止原因、运行指标、RuntimeEpisode 和 Format B trajectory。

### Phase 3：Evaluation 收敛

- 统一 TaskEpisode、Fixture、Runner、Scorer 和 Report 接口。
- 将现有 execution、software task、reliability 和 acceptance 入口接到 Runtime Adapter，再由 Evaluation Runner 封装。
- 产出：统一 `EvaluationEpisode`、`RuntimeEpisode` 引用关系和 artifact manifest。

### Phase 4：Replay 与回归门禁

- 实现 deterministic replay manifest。
- 接入 baseline compare、failure taxonomy、repair/reverify 和跨仓 Adapter。
- 产出：可复现回放证据和 CI 门禁报告。

### Phase 5：迁移和删除重复路径

- 保留旧导入路径至少一个兼容周期，并发出 deprecation warning。
- 更新 README、架构文档、运行手册和 CI。
- 删除重复 serializer、重复错误分类和未经适配的私有轨迹输出。
- 产出：迁移完成报告和旧接口删除清单。

## 8. 统一验收成果

实现完成必须提交以下成果：

1. `docs/spec/HARNESS_BUILD_SPEC.md` 对应任务的实现映射表。
2. Shared Contracts 的源码、Schema、版本记录和契约测试。
3. Runtime/Evaluation/Adapter 的依赖方向检查结果。
4. ReAct Agent、Workflow 两种执行方式各有一个可验证的 `RuntimeEpisode` 和 Format B 轨迹，并各有对应 HTTP Adapter/Runner 的契约验证；HTTP 结果必须标明其来源执行方式。
5. 一条 offline fixture replay 和一条带工具失败的 replay 证据。
6. RetryPolicy、IdempotencyPolicy、StructuredOutputContract 的单元及集成测试。
7. baseline compare 的 pass、review、hold 三种报告。
8. repair -> reverify -> pass 和 repair -> hold 两种失败闭环证据。
9. artifact manifest，包含模型/工具协议/Fixture/环境/代码版本和 SHA256。
10. 兼容导入、迁移说明和 CI 命令更新。

## 9. 验收门槛

必须满足：

- `pytest tests/evaluation/test_harness_schema.py tests/evaluation/test_harness_reliability.py tests/evaluation/test_harness_closed_loop_decision.py` 通过。
- 新增 Contract、Adapter、Policy、Replay 测试全部通过。
- ReAct Agent、Workflow 的 `RuntimeEpisode` 和 trajectory 均通过正式 Schema/契约校验；对应 HTTP Adapter/Runner 输出也必须通过正式 Schema 校验，并保留来源执行方式、运行状态和停止原因。
- required Sandbox 不可用、权限拒绝、工具超时、结构化输出错误均 fail closed。
- held-out/golden/dev/production 统计严格分栏。
- 失败、未运行、依赖缺失和无观测证据不计为成功，也不伪造为普通失败分数。
- 现有公共导入路径和已支持 CLI 在兼容周期内继续工作。

## 10. 不纳入本 Spec

- 不在本阶段引入新的 Agent 编排框架。
- 不把所有 `llm.py`、`workflow/`、`memory.py`、`safety/` 和 `tools/` 直接搬到 `harness/`。
- 不把 process Sandbox 描述为企业级安全隔离。
- 不以离线 fixture、mock 或单次本地运行宣称生产 SLA、真实用户收益或多租户 readiness。
- 不修改历史 held-out/golden 记录来提高通过率；协议或模型变化必须新建 batch。

## 11. 完成定义

当且仅当第 8 节成果齐全、第 9 节门槛通过、旧入口完成兼容迁移、所有报告能够追溯到具体代码/数据/环境版本时，本 Spec 才能标记为 `Implemented`。只有目录重组或新增抽象而没有三条运行路径、回放证据和失败闭环证据，不得标记完成。
