# Core 架构

结构地图：[`STRUCTURE.md`](STRUCTURE.md)。主场景说明：[`EVIDENCE_DOCS_TROUBLESHOOT.md`](EVIDENCE_DOCS_TROUBLESHOOT.md)。

运行时走 **自建 Core**，服务 **三类主流 Agent 应用**（编码执行 · 客服自动化 · RAG/研究）。应用地图：[`APPLICATION_DIRECTION.md`](APPLICATION_DIRECTION.md)。`docs_troubleshoot` 为 **② 客服/自动化** 下的垂直 demo。

## 与主流 Agent 的对齐（实践共性）

生产里常见的 Agent 服务形态大致如下；本项目 **整体骨架对齐**，差异在循环内的治理细节（见下一节）。

| 层 | 主流做法 | 本项目 |
|----|----------|--------|
| 交互 | HTTP Chat API、JSON/SSE | `/v1/chat`、`/v1/chat/stream`、`/v1/info`、Docker |
| 推理 | LLM + function calling（ReAct 形） | `react_loop`（Live）；`agent_runner`（离线同构） |
| 知识 | RAG / 文档检索 | `search_docs`、`lookup_api` |
| 工具 | 领域工具 + 通用工具 | docs 工具集 + ToolGuard |
| 安全 | 拒答、权限、危险操作拦截 | policy + permission gate + `fix_steps` 分级 |
| 可观测 | 日志、request_id、SSE 进度、轨迹 | Format B 轨迹 + StepWatcher（可选） + `/v1/chat/stream` |
| 质量 | 回归集 / smoke | 四套 eval + CI（**验收手段**，非产品卖点） |
| 交付 | 单服务、health/ready | `/health`、`/ready`、compose |

**刻意不作为 KPI 的能力**：复杂图编排、Checkpoint 中断恢复、多租户平台——多数 Runbook/Copilot 类 Agent 也不会先做这些。

## 细节优化（相对主流的加分项）

在 ReAct 循环与主场景契约上，做了运行时级处理（不只靠 prompt）：

| 细节 | 主流常见 | 本项目 |
|------|----------|--------|
| 工具失败 | 直接返回 error | **Harness 自修提示** + ToolGuard 分级重试/熔断 |
| 重复调用 | 靠 prompt | **Runtime 拦截** 相邻同参 duplicate |
| 步数耗尽 | 常无答案 | **reserve_final_step** + 强制 FINAL ANSWER |
| 文档问答 | RAG 后直接生成 | **强制 `verify_citations` 工具步** |
| 修复建议 | 模型自由输出 | **fix_steps**：deny → ask → allow |
| 迭代 | 改 prompt | **轨迹 → StepWatcher → failure flywheel → 改 loop** |
| 工具可见性 | 全局注册表共享 | **应用作用域隔离**（见下节），app 工具不外溢 |
| 自探健康 | 回环 HTTP 请求自己 | **进程内取值**，与探针鉴权 / Host 策略解耦 |
| 答案投递 | 一次性返回 | **`answer_delta` 流式增量** + `answer` 权威全文 |
| 客户端断开 | 仅停止推送 | **真正取消执行**（步间 + 工具前检查），不再空烧 LLM |

## 分层

```
Apps (docs_troubleshoot)     ← Agent 循环（默认）+ legacy Workflow + diagnosis
  → agent_runner（观测 → 工具 → verify_citations → policy）
  → Workflow v5（固定 DAG，REACT_AGENT_DOCS_ENGINE=workflow）
  → react_loop（LLM ReAct；Live）
  → Tools + Permission gate + ToolGuard
  → Harness Format B / Eval（验收，非卖点）
  → Server HTTP + 产品 UI
```

## Agent 循环（默认实现）

**离线 Agent 路径**（`agent_runner.py`）：

1. 根据 state / 观测 **选择下一工具**（非固定顺序 DAG）
2. 调用 `search_docs` / `lookup_api` / 现场证据 parse / `fetch_trace` 等
3. 合成 draft 后 **必须** 调用 `verify_citations` 工具步
4. `enforce_answer_policy` + `build_diagnosis`
5. 全程 `start_trajectory` → Format B 步记录 → `finish_trajectory`

Live：`REACT_AGENT_SERVER_LLM=1` 时 `/v1/chat` 走 `react_loop`，同一套 docs 工具与 prompt；`/v1/chat/stream` 在相同 handler 外增加 Runtime 进度事件。

## Workflow（legacy DAG）

v5 固定路径：**现场证据 → 检索 → synthesize → policy → diagnosis**（`REACT_AGENT_DOCS_ENGINE=workflow`）。用于对照与回归，不是默认叙事中心。

```bash
python -m react_agent.workflow run docs_troubleshoot --query "401 怎么返回？"
python examples/eval/run_docs_troubleshoot_eval.py          # 默认 agent 路径
```

## 实验对照（可选）

`experiments/langgraph/` 为 **可选** 图编排对照（`pip install -e ".[langgraph]"`），不参与主场景交付与成熟度评判。见 [`EXPERIMENTAL.md`](EXPERIMENTAL.md)。

## 设计原则

1. **整体贴近主流 ReAct 服务**；**细节**在循环治理与领域工具契约上加深  
2. 主场景默认 Agent 循环；Workflow DAG 保留作 legacy / 对照  
3. eval 验证 Agent 边界，不作为对外产品叙事中心  
4. P1 优先补齐主流交付项：Bearer 鉴权、结构化 JSON 日志、**verify_actions 接工具执行**

> ⚠️ **本目录是 RAG 语料，不只是文档**：`docs/` 会被 docs_troubleshoot 索引
> （`REACT_AGENT_DOCS_GIT_ROOT` + 前缀 `docs`），git-docs 评测（`git_docs_cases.json`）
> 按 `must_any` 关键词断言答案内容，而答案来自被检索到的**文本片段**。因此**结构性改动
> （插入/移动章节、改写被断言句子）会改变分块与命中，可能让评测失败**——即使语义没变。
>
> 该评测带有**语料基线**（`git_docs_corpus_baseline.json`，逐文件 sha256）。运行时会把
> 当前 `docs/` 与基线对比，在报告 `corpus` 字段给出状态、变更文件与**受影响用例**；
> 默认只提示（不因文档变更打断评测）。
>
> ```bash
> # 复核断言后刷新基线
> python -m react_agent.apps.docs_troubleshoot.eval_git_docs --refresh-baseline
> # 严格模式：语料漂移即失败
> python -m react_agent.apps.docs_troubleshoot.eval_git_docs --strict-corpus
> ```
>
> 实践约定：**在文档末尾追加新章节**，不要顶开前部被断言的句子；改完跑
> `pytest tests/test_docs_troubleshoot_p4.py tests/test_git_docs_corpus_drift.py`。

## 三个应用的通信方式（差异在内部，不在对外）

三者共用同一条对外通道（`/v1/chat` / `/v1/chat/stream`，HTTP JSON + SSE），差异全在应用内部：

| 应用 | 出站 LLM | 数据/语料来源 | 检索 | 工具执行 | 出站网络 |
|------|----------|---------------|------|----------|----------|
| `default` | **是**（`REACT_AGENT_SERVER_LLM=1`） | — | — | 沙箱子进程（离线 smoke 时进程内） | 仅工具自身 |
| `docs_troubleshoot` | 否 | 本地文件 + 可选本地 git | 进程内 RAG（keyword） | 进程内 | 自探进程内；外部探测受 SSRF 守卫 |
| `expense` | 否（LLM 模式直接 501） | 本地 JSON / Markdown | 进程内 RAG（keyword） | 无工具 | 无 |

两条与本表相关的实现约定：

- **工具视图按应用作用域隔离**：`tools.get_registry()` / `get_tool_definitions()` 依据
  `tools.set_request_app()` 返回该应用的工具集，`docs_troubleshoot` 的工具不会出现在
  Core/其它应用中。请求路径**不再**调用 `enable_app_tools()`（那会把 app 工具永久并入
  全局注册表）。CLI 作为顶层入口仍可显式挂载。
- **健康自探走进程内**：`probe_service_health` 判定目标指向本服务自身时（回环 + 配置端口 +
  `/health`|`/ready`）直接调用 `health` 模块取值，不经 TCP 回环，因而与探针鉴权 / Host
  校验策略解耦；指向外部地址时仍走 HTTP 并受 SSRF 守卫约束。

## 工具作用域（app 隔离）

`docs_troubleshoot` 的工具（`search_docs` / `lookup_api` / `probe_service_health` …）
**不应**对 Core 或其它应用可见。此前 `enable_app_tools()` 会把它们永久并入全局
`TOOL_REGISTRY`，使 Core 的 ReAct 循环也能看到并调用。

现在改为**请求级作用域视图**：

```python
from react_agent.tools import set_request_app, get_registry, get_tool_definitions

set_request_app("docs_troubleshoot")   # 声明本次请求属于哪个 app（"" = Core）
registry = get_registry()              # 合并视图；不改动全局对象
defs = get_tool_definitions()          # 该应用应有的工具描述
```

约定：

- **请求路径不要调用 `enable_app_tools()`**——它会永久污染全局表。需要某 app 的工具时用
  `set_request_app()` + `get_registry()`。
- `get_registry()` / `get_tool_definitions()` 以**模块装配时固化的 Core 名单**为基，
  因此即使有遗留调用方污染了全局表，Core 视图仍保持隔离。
- CLI（`agent`）是顶层入口，用户已显式选择 app，`main()` 中仍可显式挂载。
- 若某工具会读取宿主环境或发起出站请求，应显式标注权限等级（见
  `safety/permissions.py`），不要依赖“没人能调到它”。
