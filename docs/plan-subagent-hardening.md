# react-agent Subagent 能力加固方案

> 状态：**方案待评审，未写任何实现代码**
> 依据：[`subagent-comparison.md`](subagent-comparison.md) 的五家调研结论（DSH / Codex / OpenCode / ZCode / MiniMax Code）
> 范围：`src/react_agent/orchestrator.py`、`planner.py`、`react_loop.py`、`tools/`，以及对应测试与文档

---

## 0. 先说结论：改什么、不改什么

**要改**的四个真实缺陷（均已核对到具体行）：

| # | 缺陷 | 位置 | 后果 |
|---|---|---|---|
| D1 | 工具面靠中文关键词猜，猜不到就**兜底给大工具集**，且 `filter_tools` 对未知项**静默忽略** | `orchestrator.py:33-55`、`48` | 给错工具集且无任何信号；漏词 = 静默降级 |
| D2 | 调度把"无依赖"直接等同于"可并行"，**不看写冲突** | `planner.py:212-241` | 两个都写同一文件的同层任务被并行执行 |
| D3 | 无深度、无并发上限；模块级 `MEMORY` 单例被所有 Worker 共享 | `orchestrator.py:204`、`react_loop.py:141` | 递归委派失控；Worker 间记忆互相污染 |
| D4 | 无 fork 概念，Worker 一律全新会话 | `react_loop.py:470-473` | 需要承接前期结论的子任务只能靠人肉复述 |

**明确不做**的：不引入 git worktree / 容器级的 per-worker 隔离。

理由来自调研的横向结论：**五家没有一家默认给每个 subagent 独立工作区**。隔离属于"会话/环境"层，不属于"委派"层；Codex 的 `--worktree` 也只是**会话级**且仍是实验特性。用 worktree 去解决这个问题，收益（防写冲突）远小于成本（分支管理、合并冲突、清理孤儿、与现有 `paths.py`/`REACT_AGENT_DATA_DIR` 的交互）。**先做"声明 + 串行化"，把成本压到 D2 一个改动里**，把 worktree 留作 Phase 5 的有条件选项。

**项目约定**（方案已适配）：开关用 `REACT_AGENT_*` 大写环境变量（与现存 40+ 个一致）；测试放 `tests/`，已有 `test_orchestrator_isolation.py` 可扩展；`eval/dataset.json` 里 `orchestrator_simple` 用 `must_contain_any: ["[Orchestrator]", "层级", "子任务", "#1", "#2"]` 断言输出 —— **所有改动必须保留这些字符串**，否则评测回归会红。

---

## 1. Phase 1（最高优先）：工具面改为显式声明 + 对未知项报错

### 1.1 目标

把"关键词猜工具"换成"显式声明 + 校验"，并让**收窄失败变成可见事件**而不是静默降级。

### 1.2 设计

新增 `src/react_agent/tools/scope.py`（新文件）：

```
ToolScope
  - names: set[str]                  # 显式允许的工具名（精确匹配，不支持通配）
  - from_profiles(tags) -> ToolScope # 保留 profile 概念，但 profile 内容改为显式清单
  - validate(registry_names) -> list[str]   # 返回未知项，不抛异常（便于调用方决定策略）
  - resolve(all_defs, registry_names) -> list[dict]
  - describe() -> str                # 供 trace/日志：暴露了 N/M，未知 K 项
```

三条硬规则（对齐 DSH 的"fail loud"与"可见性而非权限"）：

1. **未知工具名必须可见**：`resolve()` 返回时携带 `unknown` 列表；`strict` 模式下**抛 `UnknownToolScopeError`**，非 strict 模式下打印 `[Scope] 未知工具被忽略: {...}` 并降级到交集，**绝不静默**。
2. **空 scope 不等于全量**：当前 `classify_tool_needs` 返回 `tags or {"web","calc"}` 这种兜底要删掉。空声明解析为空工具集，由调用方显式决定是否回退到全量（回退必须打印原因）。
3. **只收窄不扩权**：`resolve()` 只能从传入的 `all_defs` 里做子集，不能新增；与 DSH `toolFilter` 的"只可收窄"语义一致。

### 1.3 改动点

- `orchestrator.py`：`classify_tool_needs()` / `filter_tools()` / `TOOL_PROFILES` 改为调用 `scope.py`；保留旧函数名作为**薄封装并标记 deprecated**，避免一次性打断现有调用方。
- `orchestrator.py:run_worker()`：把"暴露 N/M 个工具"升级为带未知项的输出；把 scope 决策写进 trajectory（复用 `_capture_worker_outputs` 的落盘路径）。
- 兼容开关：`REACT_AGENT_SCOPE_STRICT=1` 开启抛错（CI/评测用），默认 `0` 只告警 —— 一个发布周期后再翻转默认值。

### 1.4 验收

- 故意声明一个不存在的工具名：strict 下抛错；非 strict 下输出含 `[Scope] 未知工具`，且**不会**因此拿到全量工具。
- 中文关键词与声明不一致时（例如任务描述里没有"计算"但声明了 `calculator`），结果由**声明**决定，不由关键词决定。
- `test_orchestrator_isolation.py` 的 `test_parallel_workers_receive_isolated_tool_definitions` 必须继续通过（它断言的是隔离性，不是分类算法）。

---

## 2. Phase 2（核心）：写集声明 + 写冲突分层的串行化

这是本方案真正的价值点，也是 D2 的唯一修复路径。

### 2.1 目标

同层任务若**写集相交**，强制拆到不同层串行执行；不相交则照旧并行。

### 2.2 设计

**关键约束（必须诚实面对）**：写集**无法从任务描述文本可靠推断**。调研显示 Codex 用 `sandbox_mode`、OpenCode 用声明式 `permissions` —— 都是**声明**而非推断。所以：

`Task` 增加字段（`planner.py:30`）：

```
Task(id, description, depends_on, writes: list[str] | None = None)
  - writes 语义：该任务**可能写入**的路径前缀。None = 未声明（未知写集）
```

**写集来源有两条，按优先级**：

1. **Planner 显式输出**（主路径）：`_PLAN_PROMPT` 增加可选行 `| writes: pathA, pathB`，并在 prompt 里要求"不确定就写 `writes: unknown`"。LLM 输出新格式时解析进 `Task.writes`；**解析不到就保持 None**，不做猜测。这一步同时是"哪些能力会被覆盖"的诚实边界：解析能力取决于模型遵循度，所以必须有第 2 条。
2. **调用方显式传入**（测试与代码路径）：`Orchestrator.execute(...)` 接受显式 `writes` 映射覆盖，供 eval / 测试 / 上层应用指定，不依赖 LLM。

**调度算法**（新增 `Planner.schedule_with_write_conflicts(tasks, levels)`，保留原 `schedule()` 不动）：

```
对每个 level：
  groups = []
  for t in level:
      for g in groups:
          if not _write_sets_may_conflict(t.writes, g.writes):
              g.append(t); break
      else:
          # 与所有现存组都冲突 → 延迟到下一轮
          deferred.append(t)
  实际执行顺序 = [g1_parallel, g2_parallel, ...] + deferred 合并进下一层递归
```

`_write_sets_may_conflict` 规则（保守优先）：

| a | b | 判定 |
|---|---|---|
| 都声明且前缀不相交 | — | **不冲突**（可并行） |
| 任一为 None / `unknown` | — | **视为冲突**（保守串行） |
| 一方是另一方的前缀（目录 vs 文件） | — | **冲突** |
| 路径大小写/分隔符差异 | — | 归一化后再比（Windows 下大小写不敏感） |

**默认策略**：`REACT_AGENT_WRITE_CONFLICT_SERIALIZE`，默认 `1`（安全侧）。`parallel=True` 但检测到冲突时，打印 `[Orchestrator] 写冲突：强制串行 #{x} ↔ #{y}` 并降级为串行 —— **降级必须可见**。

### 2.3 为什么不做 per-worker 工作区

即使给每个 Worker 一个独立 cwd，也要回答"结果怎么合并"。`opencode-worktree` 的做法是**合并用文件锁串行化、冲突即中止并列文件** —— 本质仍是"减少并发写"，只是把问题推到 git 层。先做声明 + 分层不需要碰文件系统、不需要新依赖、不需要清理孤儿 worktree，且在 `eval/dataset.json` 的确定性用例上不会引入 flakiness。

### 2.4 验收

- 两个 `writes` 相交的同层任务：实际执行**不并发**（用 `Barrier(timeout=…)` 断言会超时/或用调用序列断言串行）。
- 两个 `writes` 不相交的同层任务：**仍然并发**（复用现有 `Barrier(2)` 写法，证明没有把并行能力一起关掉）。
- 任一 `writes` 未声明：保守串行，且日志有明确原因。
- 无依赖但写集不相交的任务，最终答案仍包含 `[Orchestrator]`/`层级`/`#1`/`#2` 等字符串（保证 eval 不回归）。

---

## 3. Phase 3：深度与并发上限 + 记忆隔离

### 3.1 深度上限

对齐 Codex（`max_depth` 默认 1、`max_threads` 默认 6）与 DSH（`delegationDepth` + `maxDepth`）：

- 新增 `REACT_AGENT_SUBAGENT_MAX_DEPTH`，默认 `1`（允许直接子级，禁止更深嵌套 —— 与 Codex 默认一致）。
- 用 `ContextVar` 记当前委派深度（项目已有这套 idiom：`_last_trajectory_steps`、`react_loop.py:46`）。
- 入口点：`multi_agent_chain()`（`react_loop.py:765`）。递归调用时深度 +1，超限**明确拒绝并返回可读错误**，不是静默截断。
- 新增 `REACT_AGENT_SUBAGENT_MAX_CONCURRENCY`，默认 `4`；当前 `ThreadPoolExecutor(max_workers=len(level))`（`orchestrator.py:204`）改为 `min(len(level), cap)`。

### 3.2 记忆隔离

现状：`MEMORY = Memory()` 是模块级单例（`react_loop.py:141`），所有 Worker 共享，且 `auto_extract_memory()` 会**从并行 Worker 里回写**（`react_loop.py:754`）—— 这是并行场景下真实的交叉污染。

方案：
- 给 Worker 调用加显式参数 `memory_scope`（`spawn` 默认 = 只读父级快照、不写回；`fork` = 可读写）。
- Worker 侧**默认禁止自动记忆回写**（`auto_extract_memory` 仅在主会话路径调用），开关 `REACT_AGENT_WORKER_MEMORY_WRITE=0` 为默认。
- 对齐 ZCode 的结论："项目记忆只在主对话生效，子智能体不读也不写" —— 这是五家中唯一把该边界写死的，值得照做。

### 3.3 验收

- 深度超限时返回明确错误，且**不产生**新会话副作用。
- 并发上限生效：给定 8 个同层任务 + cap=4，峰值并发 ≤ 4。
- 并行 Worker 结束后，`MEMORY.facts` 无新增（写回被禁用）。

---

## 4. Phase 4：引入 `spawn` / `fork` 两种上下文策略

对齐 DSH 的 `inheritsParentContext`（fork=true / spawn=false）语义，并把这条信息**如实告知模型**（DSH 特意强调这一点，避免措辞暗示继承了工具或权限）。

- `run_worker(..., context_mode: Literal["spawn","fork"] = "spawn")`。
- `fork` 的实现：注入父会话**最后一个已完成轮次**为止的内容 —— 但项目当前没有持久化的轮次级会话日志（`harness/recorder.py` 记的是 trajectory，不是可续接的会话前缀）。因此这里有一个**明确的依赖前置**：
  - **可选做法 A（低成本，先做）**：`fork` 只注入父会话**已产出的最终答案摘要 + 上游任务结果**（现有 `shared_data` 已具备），并在 prompt 里如实说明"你只看到摘要，不是完整历史"。
  - **可选做法 B（高成本，后做）**：为 SSE 会话引入可续接的回合日志，才能实现真正的"已完成轮次前缀"。
- 二者都必须遵守 DSH 的一条纪律：**fork 初始内容是一次性快照**，父级此后新增的内容不回流；且 fork **不继承工具与权限**。

### 4.1 验收

- `spawn` 与 `fork` 传给 `react_loop` 的初始 messages 不同，且测试能断言差异（现有 `fake_loop` 模式可直接复用）。
- fork 模式下 prompt 中**不存在**暗示"继承了父级工具/权限"的措辞。

---

## 5. Phase 5（有条件，默认不做）：工作区/进程外隔离

仅当出现以下信号之一才启动，且**先写 ADR**：

- 实际观测到并行写导致的数据损坏（不是理论风险）；
- 需要跑不可信代码（此时应对齐项目已有的 `SANDBOX_BACKEND=container` 路径，而不是 worktree）。

若启动，优先级为：**进程外执行器**（复用 `harness/sandbox.py` 与 `_sandbox_runner.py` 的既有能力） > git worktree（需要额外解决合并串行化与孤儿清理，成本最高）。

无论是否启动，**现在就应该**在 `docs/` 里补一句显式声明："当前 Orchestrator 的并行 Worker 共享同一工作区，无文件系统隔离；并行写需依赖 Phase 2 的写集声明。" —— 五家里 ZCode 把这条写进了用户文档，本项目也该写进 `CORE_ARCHITECTURE.md`。

---

## 6. 落地顺序与影响面

| Phase | 新增文件 | 修改文件 | 风险 | 是否影响 eval |
|---|---|---|---|---|
| 1 工具面声明化 | `tools/scope.py` | `orchestrator.py` | 低（保留旧函数名） | 需保留 `[Orchestrator]`/层级 等字符串 |
| 2 写集 + 冲突分层 | — | `planner.py`、`orchestrator.py` | 中（调度行为变化） | 同上 + 新增确定性用例 |
| 3 深度/并发/记忆 | — | `react_loop.py`、`orchestrator.py` | 中（`MEMORY` 写回行为变化） | 低 |
| 4 spawn/fork | — | `orchestrator.py`、`react_loop.py` | 中（prompt 变化） | 低 |
| 5 工作区隔离 | 视方案 | 视方案 | 高 | 高 |

**建议节奏**：Phase 1 + 3 一批（都是"加约束、不加行为分支"），Phase 2 单独一批（唯一改调度语义的），Phase 4 最后。每批都必须：

1. 扩展 `tests/test_orchestrator_isolation.py`（该文件已是并发断言的正确落点，`Barrier` + `monkeypatch` 模式现成）；
2. 跑 `test_all.py` 与 eval 的 `orchestrator_simple` 用例；
3. 更新 `docs/CORE_ARCHITECTURE.md` 的 Worker 章节（现状描述与实现同步）。

---

## 7. 已定稿决策（2026-09-25 确认）

| # | 事项 | 决策 | 对方案的约束 |
|---|---|---|---|
| 1 | Phase 2 写冲突检测默认值 | **默认开启** | `REACT_AGENT_WRITE_CONFLICT_SERIALIZE` 默认 `1`；检测到冲突必须打印降级原因；未声明写集按保守串行处理 |
| 2 | Phase 4 fork 策略 | **先做 A（摘要式 fork），再做 B（真回合前缀）** | Phase 4A 必须用 prompt 如实标注"你只看到摘要，不是完整历史"；不得暗示继承工具或权限。Phase 4B 需先补回合级会话日志，另立项 |
| 3 | Phase 5 工作区隔离 | **仅做文档声明** | 在 `docs/CORE_ARCHITECTURE.md` 显式声明"并行 Worker 共享同一工作区，无文件系统隔离"；进程外执行器另立项目，不在本方案内实施 |

**实施批次**：Phase 1 + 3 → Phase 2 → Phase 4A → 文档声明 →（Phase 4B 另立项）。

### 7.1 实施进度（2026-09-25 完成）

- [x] **Phase 1**：工具面声明化 — 新增 `src/react_agent/tool_scope.py`（`ToolScope` / `UnknownToolScopeError`）；`orchestrator.py` 改为声明式解析，未知工具名**告警不静默**，`classify_tool_needs` 降级为兼容层且**取消兜底**
- [x] **Phase 2**：写集声明 + 冲突分层 — 新增 `src/react_agent/write_sets.py`；`Task.writes` + Planner 解析 `| writes:`；`Planner.schedule_with_write_conflicts`；`Orchestrator` 默认按写冲突分段（**默认开启**）
- [x] **Phase 3**：深度/并发上限 — 委派深度守卫（默认 1，超限明确拒绝）+ 并发上限（默认 4）
- [x] **Phase 4A**：摘要式 fork — `Task.context_mode` + Planner 解析 `| context: fork`；Worker 提示词**如实标注**摘要非完整历史、不继承工具与权限
- [x] **文档声明**：`docs/CORE_ARCHITECTURE.md` 新增「Orchestrator / Worker 的能力边界（含无工作区隔离的声明）」
- [ ] **Phase 4B**（另立项）：真"已完成轮次前缀" fork，需先补回合级会话日志
- [ ] **Phase 5**（另立项）：进程外执行器 / worktree 隔离

### 7.2 新增配置项

| 环境变量 | 默认值 | 作用 |
|---|---|---|
| `REACT_AGENT_WRITE_CONFLICT_SERIALIZE` | `1` | 同层写冲突强制串行（**默认开启**，按决策） |
| `REACT_AGENT_SUBAGENT_MAX_DEPTH` | `1` | 委派深度上限；超限明确拒绝 |
| `REACT_AGENT_SUBAGENT_MAX_CONCURRENCY` | `4` | 同层并行 Worker 上限；`0` = 不限 |
| `REACT_AGENT_SCOPE_STRICT` | `0` | 工具面声明含未知名字时抛错而非仅告警 |
| `REACT_AGENT_WORKER_MEMORY_WRITE` | `0` | 是否允许 Worker 回写长期记忆 |

### 7.3 实施记录与已知边界

**文件**：新增 `src/react_agent/tool_scope.py`（工具面声明解析）、`src/react_agent/write_sets.py`（写集冲突判定）、`tests/test_subagent_hardening.py`；修改 `src/react_agent/orchestrator.py`、`src/react_agent/planner.py`、`src/react_agent/react_loop.py`、`docs/CORE_ARCHITECTURE.md`。

> 注：`tool_scope.py` / `write_sets.py` 刻意放在**顶层**而非 `tools/` 包内 —— `react_agent.tools.__init__` 会挂载 app/workflow/experimental 工具（连带 RAG），Orchestrator 不能在 core 路径上触发那次装配。

**验证**：
- 新增 + 既有并发测试：`tests/test_subagent_hardening.py` + `tests/test_orchestrator_isolation.py` = **36 passed**
- 相关回归组（含 workflow / permissions / docs / llm payload / eval contract / rag / duplicate / final answer / corpus drift）：通过
- 全量离线套件：失败数与基线一致（12–13 项既有失败）。已用 `git worktree` 建干净副本逐项对照确认，非本次改动引入。

**提交**：`8f27fcc`（RAG 语料装配修复，独立提交）· `c3dbd75`（本方案的实现 + 指令解析三处修复）。

### 7.4 指令解析鲁棒性（实测驱动，2026-09-25 补充）

起因：`writes` 依赖 Planner 的 LLM 输出，需要量化"模型不遵循格式"的风险。用 14 种真实偏差场景实测当前解析器后，确认风险**低且失效方向正确**（漏写/拼错/反引号等落为 `None` → 保守串行，不存在"静默并行写同一文件"的路径），但发现三处失真并已修复：

| # | 问题 | 修复 |
|---|---|---|
| 1 | `depends_on` 用宽泛 `in` 匹配，`\| writes: depends_on_helper.py` 被误判为依赖指令，产出垃圾依赖 `['writes: _helper.py']`，任务永远无法 `ready()` | 指令名归一化（去 `_`/`-`/空格 + 小写）后前缀匹配 |
| 2 | `writes` 值不做形态校验，`src/a.tsx (新建)`、`src/b.py; src/c.py` 被当成**有效声明**——垃圾路径既不匹配真实路径、也不触发 unknown 兜底，会让两个写同一文件的任务被判为不相交而放行并行 | 值形态校验；任一值不像路径则**整条降级为未声明**并打印被拒值（引号路径仍接受） |
| 3 | 拼错的指令（如 `\| write:`）被静默丢弃 | 打印「忽略无法识别的指令」，未知即可见 |

附带修复：`Orchestrator.run_worker` 原先无条件调用 `_registry_names()` 校验工具名，而该调用会装配整个 `react_agent.tools` 包（连带 RAG）。改为先与本次可用工具定义求交（零成本），仅当声明出现可用集之外的名字时才查注册表，并区分「拼错」与「已注册但本次未暴露」。

**已定稿决策**：写冲突检测**默认开启**（同层写集相交即串行，宁可慢不可猜）。

**已知边界（必须如实说明）**：

1. **写入逻辑上的解释**：`write_sets.py` 的注释写的是「并行 Worker 没有工作区隔离」——这正是事实；调度层面的串行化**降低**了并发写风险，但**不消除**它（同一 Worker 内部、或写集声明不完整的场景仍可能冲突）。
2. **命中前先执行**：写集来自 Planner 的 LLM 输出，模型可能不遵循 `writes:` 格式；此时 `writes` 为 `None` → 保守串行。**这是设计意图**：宁可慢，不可猜。
3. **`docs/` 同时是评测语料**：`docs/` 同时是 git-docs 评测的 RAG 语料。本次新增/修改了 3 个 docs 文件，语料 sha256 基线（`git_docs_corpus_baseline.json`）**未刷新**。注意该基线在改动前**已经**与 `docs/` 漂移（18 个文件，其中多数非本次改动），因此刷新它属于独立事项，不应混进本次改动。

**顺带发现的既有缺陷（已在 `8f27fcc` 单独修复）**：

`tests/test_core_lazy_imports.py::test_react_loop_import_does_not_load_experimental_modules` 在本方案开始前于 HEAD 上就失败。已用干净 worktree 复现（`HEAD rag leak: True`，`1 failed`）。

- 导入链：`react_agent.tools.__init__` → `enable_workflow_tools()`（模块级调用）→ `react_agent.workflow.tools` → `workflow.builtins` → `apps.docs_troubleshoot.diagnosis/draft` → `apps/docs_troubleshoot/__init__.py` → `tools.py` → `apps/docs_troubleshoot/index.py:15` → `react_agent.rag`。
- 后果：**Core 默认路径会连带装配 RAG 语料**（实测启动打印 `[RAG] 已加载 591 个文档片段`），与"实验工具默认不注册"的设计意图不符；`import react_loop` 实测 **2.46s → 1.32s**（修复后）。
- 修复方式：`index`（→ `rag`）在 `tools.py` 中只在真正检索时需要，改为经 `_load_index()` 按需导入。
