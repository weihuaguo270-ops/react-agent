# Subagent 实现对比：DSH / Codex / OpenCode / ZCode / MiniMax Code

> 调研日期：2026-09-25
> 方法：优先取官方文档与源码仓库真值（DSH 官方 subagent 子系统文档、Codex 官方文档镜像、OpenCode 官方 Agents 文档、ZCode 官方子智能体文档、MiniMax Agent 官方文档+官方博客）。第三方教程与社区插件在文中单独标注，不与官方行为混用。
> 说明：本文只做资料调研，不改动 `react-agent` 任何代码。

---

## 0. 一句话结论

五家都做了「主 Agent 派子 Agent」，但**没有一家默认给子 Agent 独立工作区**。
差异主要落在四处：**上下文继承策略**、**工具面收窄手段**、**结果回传协议**、**是否把工作区隔离当作独立机制**。
其中 DSH 与 Codex 把「工作区隔离」明确排除在 subagent 职责之外（交给 worktree 机制/外部工具）；Codex 已提供 `--worktree` 实验能力；ZCode 明确声明 fork 不回滚磁盘文件、共享同一工作区。

---

## 1. 总览对比表

| 维度 | DeepSeek Harness (DSH) | OpenAI Codex CLI | OpenCode | ZCode (智谱) | MiniMax Code CLI |
|---|---|---|---|---|---|
| 派发入口 | `subagent` / `subagent_fork` 工具 | 显式要求 spawn agents；`spawn_agents_on_csv` | `subagent` 工具；`@` 提及 | Agent 工具自动/显式调用 | `task` 工具 |
| 子 Agent 来源 | 6 个后端 provider | 内置 `default`/`worker`/`explorer` + 自定义 TOML | 内置 `general`/`explore` + 自定义 Markdown | 内置 `general-purpose`/`Explore` + 自定义 Markdown | `task` 的 `agent_name` |
| 对话上下文继承 | spawn=零；fork=父级**已完成轮次**前缀 | 不继承对话 | **fresh context** 子会话 | 独立上下文；默认注入 AGENTS.md | 全新上下文（brief 必须自足） |
| 配置/权限继承 | 不继承父级工具视图与权限；新建扁平作用域 | **继承当前 sandbox policy** + 父 turn 运行时 override | 子级用**自己配置的 permissions**，非父级受限副本 | 工具权限在定义文件里独立配置 | 继承会话级模型；权限按模式（Ask/Auto/Full） |
| 工具面收窄 | `toolFilter` 能力开关，只可收窄不可扩权，未知工具名会大声报错 | `sandbox_mode`、`mcp_servers` 按 agent 覆盖 | `permissions` 规则（action×resource×effect） | `tools`/`disallowedTools` + MCP 精确名单 | 自定义 Agent 的角色化工具集 |
| 结果回传 | 父级只拿子级**最终输出**；结构化输出走 `outputSchema` | 父等全部结果后返回整合响应；CSV 模式要求每 worker 调一次 `report_agent_job_result` | 子会话结果作为工具输出回到父会话 | 汇总回主对话 | `task` 返回文本/摘要 |
| 后台执行 | 后台 + 完成时运行时投递通知 | `/agent` 切换/引导，可后台 | 前台或后台子会话 | **前台并行 / 后台**（由 Agent 自己决定） | `run_in_background` 布尔 |
| 嵌套深度 | 有 `delegationDepth` 与 `maxDepth` 上限 | `agents.max_depth` 默认 **1** | `general` 不能再生子代理 | **子智能体内不能再派发子智能体** | 技术上支持，官方不建议 |
| 并发上限 | 由提供方/容量控制 | `agents.max_threads` 默认 **6** | 未在文档给出固定值 | 未在文档给出固定值 | 按队列/团队引擎 |
| 工作区隔离 | **无 per-subagent 隔离**（同一 cwd；由插件/worktree 负责） | 默认共享；`--worktree` 实验能力（0.154.0） | 默认共享；社区 `opencode-worktree` | **明确共享**：fork 不回滚磁盘 | CLI 无；Agent Team 走角色+沙箱+分支 |

---

## 2. DeepSeek Harness（DSH）

来源：官方 [Subagent 子系统文档](https://cdn.jsdelivr.net/gh/deepseek-ai/deepseek-harness@master/docs/subsystems/subagent.zh.md)、[subagent-fork-in-process](https://cdn.jsdelivr.net/gh/deepseek-ai/deepseek-harness@master/packages/subagent/subagent-fork-in-process/README.zh.md)、[subagent-spawn-in-process](https://cdn.jsdelivr.net/gh/deepseek-ai/deepseek-harness@master/packages/subagent/subagent-spawn-in-process/README.zh.md)。

**架构定位**：subagent 是一个**能力 seam（可选能力）**，与 agent loop 解耦，类型定义不放在 core。关键设计是**同一上下文可共存多个具名 provider**（`ctx.subagents` 注册表），这一点照搬了 LLM 适配器注册表的模式，而不是单执行器的 bash。

**六个 provider**：`spawn-in-process`、`fork-in-process`、`acp`、`codex`、`claude-code`、`dsh-sdk`。
- 进程内后端用「全新扁平作用域」创建子 Agent；父级工具限制与权限**绝不会被导入**。
- fork 后端只额外做一件事：把父级事件日志的**已配平已完成轮次前缀**（截至最后一个 `turn/end`）作为 `CreateAgentOptions.seed` 注入子会话。初始内容是一次性快照，父级此后产生的内容永不抵达子级。
- 外部 provider（ACP/Codex/Claude Code）会**拒绝** `agentOptions`，即不接受模型/推理强度覆盖。

**能力协商（值得借鉴的工程细节）**：`SubagentCapabilities` 声明 5 个启动时能力——`agentOptions`、`outputSchema`、`depthLimit`、`toolFilter`、`persona`。请求依赖了 provider 不具备的能力时，返回 `SubagentError('UNSUPPORTED_CAPABILITY')`，**fail loud 而非接受后静默忽略**。

**工具面收窄**是「可见性而非权限」：`toolFilter` 作为作用域内 `tools.restrict()` 应用在子 Agent 创建窗口，被过滤的工具**既从提示词里消失、也拒绝执行**（同一可见性），未知工具名会大声校验报错。`persona` 以 `deployment:persona-prefix` 作用域段遮蔽该子级的部署 persona。

**两类子 Agent 生命周期**：
- 一次性：`SubagentRun`，一个结果、无 steering、无恢复，消费方必须 `dispose` 到完全停稳。
- **可继续**：`SubagentRuntime.startContinuable()` 预留稳定子 id，一个持久 Session 至多一个驻留 Activation。`sendMessage()` 是**唯一由模型编写消息**的操作，只允许直接 parent ↔ 直接可继续 child，sibling/隔代/self-target 一律拒绝。`interrupt()` 同步鉴权后 `Agent.cancel(..., {keepInbox:true})` 并立即返回——**是暂停不是销毁**。
- 子级结算时，管理器向父级投递一条 `subagent-settled` 通知，来源 kind 与 Agent 消息**刻意区分**，避免 transcript 把运行时记账算成子 Agent 自己说的话。

**结果回传**：父级只接收子级最终输出（或非完成 stop reason 对应的出错工具结果），中间工作永不到达父级。这保证了父级上下文的干净。

**工作区隔离**：文档层面**不属于 subagent 职责**。进程内 spawn 默认继承父级 cwd；fork 除 seed 外同样。要隔离需另配 worktree 类插件（社区有 `dsh-worktree-space`、`dsh-plugin-worktrees`、`dsh-plugin-subagents`，均为第三方，非内置）。

**官方定位的两个工具集**：`dsh-tool-subagent`（按 provider 委派）与 `dsh-tool-subagent-control`（可选全局 `send_message`/`interrupt_agent`/`list_agents`）。`list_agents` 对外只暴露 `running`/`inactive`，**不表示任务是否完成**，也不保证 `send_message` 会成功——这是刻意的弱承诺。

---

## 3. OpenAI Codex CLI

来源：官方文档（经 [非官方中文镜像](https://cdn.jsdelivr.net/gh/crasuna/openai-dev-docs-cn-mirror@main/docs/mirror/codex/subagents.md) 读取，原文 developers.openai.com/codex/subagents）+ [Subagent concepts](https://cdn.jsdelivr.net/gh/crasuna/openai-dev-docs-cn-mirror@main/docs/mirror/codex/concepts/subagents.md)。

**为什么做**：官方概念页把动机写得很直白——**context pollution**（有用信息被噪音掩埋）与 **context rot**（对话被无关细节填满后性能下降）。解法是「把嘈杂工作移出主线程」，子级返回**摘要而非原始中间输出**。

**触发**：Codex **不会自动** spawn，只有用户显式要求（"spawn two agents"/"delegate this work in parallel"/"one agent per point"）。原因是一致性口径：每个子 Agent 都跑自己的模型与工具，token 消耗高于单 Agent。多 Agent V2（CLI 0.145.0 起稳定）把委派模式分成三档：禁用 / 仅显式请求 / 主动，可在**线程级与回合级**切换。

**上下文继承**：新 agent thread，不继承对话。
但有三类东西**确实继承**：
1. **sandbox policy**（"Subagents inherit your current sandbox policy"）；
2. **父 turn 的 live runtime overrides**——包括你在会话里交互式设置的 `/permissions` 或 `--yolo`，**即使 custom agent 文件写了不同默认值也会被重新应用**；
3. 被省略的可选字段（`model`、`model_reasoning_effort`、`sandbox_mode`、`mcp_servers`、`skills.config`）从父会话继承。

**工具与模型**：custom agent 用独立 TOML 文件（`~/.codex/agents/` 个人级、`.codex/agents/` 项目级），必填 `name`/`description`/`developer_instructions`，可作为 spawned session 的**配置层**覆盖普通会话配置。项目级与个人级同名冲突时**自定义覆盖内置**（例如覆盖 `explorer`）。`nickname_candidates` 只影响展示，身份仍由 `name` 决定。

**结果与调度**：Codex 自己负责编排——spawn、路由 follow-up、等待、关闭 agent thread；多个 agent 在跑时**等全部结果可用再返回整合响应**。CLI 里 `/agent` 切换与查看 thread，可直接要求引导/停止/关闭。实验性的 `spawn_agents_on_csv` 按 CSV 每行 spawn 一个 worker，要求每个 worker **恰好调用一次** `report_agent_job_result`，未报告的行在导出 CSV 里标记为 error；job 状态从 CSV 迁到 SQLite。并发 `agents.max_threads` 默认 6，`agents.max_depth` 默认 1（允许直接子级 spawn，阻止更深嵌套）。

**工作区隔离**：官方明确把并行**写**列为高风险（"agents editing code at once can create conflicts"），起点建议是读密集任务。CLI 0.154.0 新增**实验性 worktrees**（`--worktree` / `/worktree`），可为新建或 fork 的会话创建独立工作树——注意这是**会话级 worktree，不是每个 subagent 自动一份**。第三方教程把结论说得更直白：*开启 Subagents 本身不保证每个子代理都有独立 Git 工作树；要隔离两个实现方向，应先分别创建 worktree，再分配任务。*（[第三方课程](https://cdn.jsdelivr.net/gh/KimYx0207/AI-Coding-Guide-Zh@main/docs/codex/CX-08-Codex-Subagents%E5%A4%9AAgent%E5%8D%8F%E4%BD%9C%E5%AE%8C%E6%95%B4%E6%8C%87%E5%8D%97.md)，非官方）

---

## 4. OpenCode

来源：官方 [Agents 文档](https://opencode.ai/v2/docs/agents) 与 [V1 版 Agents](https://opencode.mintlify.site/agents)。

**Agent = 可复用配置档**：Markdown 文件（`~/.config/opencode/agents/<name>.md`、`.opencode/agents/<name>.md`）或 JSONC。frontmatter 字段即配置，**正文即 system prompt**。路径会变成 agent id（`.opencode/agents/team/reviewer.md` → `team/reviewer`）。

**modes**：`primary`（可作主 Agent）/ `subagent`（只能被子 `subagent` 工具在子会话启动）/ `all`。

**上下文**：文档写得很明确——"Subagents run in child sessions with **fresh context**"，前台或后台均可，可用 `@explore ...` 直接点名委派。

**权限**：父级的 `subagent` 权限控制它能启动哪些子 Agent；但这里有个**与直觉相反的关键设计**——"The child currently uses **its own configured permissions, not a restricted copy of the parent's permissions**"。也就是说权限模型不是「父级 ∩ 子级」，而是子级自持。权限规则是 `{action, resource, effect}` 的有序列表，**最后匹配者胜**，所以宽规则要放前面；`action` 覆盖 `shell`/`edit`/`subagent`/`read`/`glob`/`grep`/`webfetch`/`websearch`/`skill`。

**工具面**：通过 `permissions` 的 `edit`/`shell` deny 实现「只读 reviewer」这类角色；`steps` 限制模型步数（末步移除工具并要求总结）；`hidden` 只影响可见性、不是安全边界（文档特意点明）。

**内置**：`build`（默认）、`plan`（探索规划，正常项目文件禁止编辑）、`general`（**subagent**，宽工具但**不能再启动子代理**）、`explore`（**subagent**，只读 read/glob/grep/webfetch/websearch），另有隐藏的 `compaction`/`title`/`summary` 维护型 agent。V2 没有内置 `scout`。

**工作区隔离**：内置无 per-subagent 隔离。社区用 Go 写的 [`opencode-worktree`](https://pkg.go.dev/github.com/danhenton/opencode-worktree) 补齐：为每个 agent 会话创建 `agent/<task>` 分支的兄弟 worktree 目录，退出时自动合并回父分支，**合并用文件锁串行化**（`/tmp/<repo-name>-merge.lock`）防止多 agent 同时合并竞态，冲突则中止并列出冲突文件。第三方，非官方。

---

## 5. ZCode（智谱）

来源：官方 [子智能体文档](https://zcode.z.ai/cn/docs/subagents)（v3.14.3 时期）。

**两种内置 + 可自定义**：
- `general-purpose`：完整工具权限，适合独立实现小功能、跑验证命令。
- `Explore`：**只读**文件搜索与代码库调研，不创建/修改/移动/删除文件。
- 自定义（Beta，**仅用户级** `~/.zcode/agents/<name>.md`，暂不支持项目级）：表单或 frontmatter 定义名称/颜色/模型/思考强度/描述/可用工具/系统提示词。

**字段级细节（工程上很有信息量）**：
- `model` 写 `inherit` 或不填 → 跟随主 Agent；`thoughtLevel` **仅在同时配置了具体 model 时生效**；字段名**不是** `reasoningEffort`，**不认识的字段会被静默忽略、不报错**。
- `tools` 留空或 `*` → 继承全部工具**包括已连接 MCP**；一旦自定义勾选，**MCP 工具会全部不可用**（勾选列表只有内置工具），要保留个别 MCP 得手写全名 `mcp__<服务名>__<工具名>`，且**通配写法无效、也会被静默忽略**。
- 子级只能看到主会话**启动时**已连接的 MCP；中途新连的对子级不可见。
- `maxTurns`、`mcpServers`（声明的服务未连接时调用直接失败）、`injectAgentsMd`（默认注入 `~/.zcode/AGENTS.md` + 工作区 AGENTS.md，内置 Explore 默认不注入）。
- **生效时机**：改定义文件或改模型/思考强度需**新建会话**；例外是未指定 model 的子级会立即跟随主会话模型切换。

**明确写死的三条边界**：子智能体**内不能再派发子智能体**；内置角色不可编辑正文/删除/停用；**项目记忆只在主对话生效，子智能体不读也不写**。

**前台/后台**：前台并行启动时主任务等全部完成再继续；后台则主任务不必等待，跑完自动回到主对话。出于安全，**后台运行的 Explore 只有只读工具**。是否后台由 Agent 自己决定，无需手动切换。文档强调需要"新建会话"才生效，说明子 Agent 定义是在会话启动时快照加载的。

**工作区隔离（本项目最值得注意的一条）**：官方在「会话分叉」段落写得毫无歧义——*分叉只影响对话历史，**不会回滚磁盘上的文件**。两个会话操作的是同一个工作区。* 子智能体同理，没有 per-subagent worktree。社区有 `zcode-executor`、`zcode-loop-orchestra` 之类工具在**外部**补 worktree 隔离，属于第三方。

---

## 6. MiniMax Code CLI

来源：官方 [Agent Team 文档](https://agent.minimaxi.com/docs/code/agents/team)、[自定义 Agent](https://agent.minimaxi.com/docs/code/agents/custom-agents)、[安全与权限](https://agent.minimaxi.com/docs/cli/security)、[能力总览](https://agent.minimaxi.com/docs/cli/features)、官方博客 [MiniMax Agent Team](https://www.minimax.io/blog/minimax-agent-team-long-running-1779893953)。

**两个层次，别混淆**：
1. **CLI 的 `task` 工具**（模型工具调用层的委派）。
2. **桌面端 Agent Team**（Leader/Worker/Verifier + 确定性状态机的运行时）。

### 6.1 CLI `task` 工具

第三方技能的兼容性说明给出了**经 `cli.js` 严格校验器验证的规范 schema**（[来源](https://skillsmp.com/creators/minimax-ai/minimax-code-plugins/plugins-antianqi-codex-harness-patterns-skills-model-router)，第三方，但附版本号与校验点）：

```
task(
  description: string,                              // required
  prompt: string,                                   // required
  agent_name: "explore" | "worker" | "verifier",    // required
  run_in_background?: boolean                       // optional
)
```

关键约束：**没有 `model_config_id`、没有 `model`、没有 `reasoning_effort`**——0.2.4 的 `task` 不支持 per-call 模型路由，模型选择是**会话级**的（会话启动时决定）。该技能作者还专门记录了自己 v0.3.3 的错误说法并更正，属于可靠的一手核对。

`agent_name` 的三个角色对应清晰的职责分离：`explore`（只读调研）/ `worker`（实现与修复）/ `verifier`（验证）。这与 ZCode 的 Explore/general-purpose、Codex 的 explorer/worker 收敛到同一套角色划分。

**上下文**：官方博客明确批评「传统 Task 工具」的局限——*一次输入输出、没有多轮对话、不能实时上报问题与冲突*，适合短时低风险的本地探索（搜文件、摘要、方案 sanity check）。也就是说 `task` 的子级是**全新上下文**，brief 必须自足。

**工作区隔离**：CLI 默认数据根 `~/.minimax`（`MINIMAX_DATA_DIR` 可切），权限模式 Ask/Auto/Full access/Off；headless 用 `smart` 代替 `ask`（无人工确认界面）。文档给 CI 的建议是「只在隔离工作区使用 `--permission full` 或 `off`」——**即隔离靠外部提供，不是 subagent 自带的**。没有 per-subagent worktree。

### 6.2 Agent Team（桌面端）

这是五家里投入最重的多 Agent 工程，几个设计点值得单独记：

- **三角色对抗**：Leader 拆解目标 → Worker 执行 → **Verifier 与 Worker 构成对抗关系**（"one finishing triggers the other to start"），刻意解决「单 Agent 既是运动员又是裁判」的问题。
- **状态机而非提示词编排**：Team Engine 管理每个 Agent 的生命周期，一次生命周期 = 一个 Session，状态为 producing → verifying → done；**verifying 失败会唤醒 producing 节点继续改**。Leader 全程拿最新状态，**可以向正在运行的 producing/verifying Agent 追加提示词**——这是对 `task` 一次性调用模式的直接升级。
- **通信设计哲学**：把人对 Agent 的操作（prompt/spawn/abort/kill）抽象成接口，**操作者可以是人、另一个 Agent 或 Team Engine**（"Agents and humans have equal rights"），但明确保留边界——等权不等于无限权限，也不把人移出问责链。
- **长任务成本三分类**：handoff cost（跨 Agent 重组信息）/ sharing cost（共享信息每轮所有人付 token）/ aggregation cost（10 份材料合并成 1 篇）。应对手段是**交接文件 + 跨 Agent 共享白板文件 + Agent 间 CLI 通信**，而不是把一切都塞进 context。
- **工作区与隔离**：Coding Harness 场景下要求「代码在分支上、执行在沙箱、编辑即 diff、测试可重跑、评审留记录、失败可回放」，并把停止条件绑定到**确定性的外部系统**（测试/构建/PR）。注意这是**角色分工 + 沙箱 + 分支**层面的隔离，不是「每个 subagent 一个 worktree」。
- **官方自陈的成本态度**：引用 *Cost of Consensus* 论文——同质辩论场景下消耗可达孤立自纠的 **2.1–3.4 倍 token 且准确率不升反降**；结论是*没有结构和停止条件的「更多」只是把不确定性并行扩散*。这也是它劝退「什么都开 Team」的论据。

---

## 7. 四个关键问题的横向回答

### 7.1 上下文继承：要拆成三类，别当一件事

| 继承类别 | 谁继承 | 谁不继承 |
|---|---|---|
| **对话内容** | 仅 DSH `fork`（父级已完成轮次前缀，一次性快照）；ZCode 辅助对话（非 subagent，继承主会话历史） | DSH `spawn`、Codex、OpenCode、ZCode 子智能体、MiniMax `task` 全部**零继承** |
| **配置/权限** | Codex（sandbox policy + live runtime overrides + 省略字段）、MiniMax（会话级模型）、ZCode（AGENTS.md 注入） | DSH（明确不继承父级工具视图与权限）、OpenCode（子级用自己配置的权限） |
| **工具面** | Codex（省略即继承）、ZCode（`tools` 留空/`*` 继承全部含 MCP） | DSH（新建扁平作用域 + `toolFilter` 只收窄）、OpenCode（受子级 permissions 约束） |

工程含义：**「不继承对话」是共识，「配置继承」才是各家分歧最大、也最容易踩坑的地方**。Codex 选择继承 sandbox 与运行时 override（安全边界一致优先），DSH 与 OpenCode 选择子级自持（角色可独立定义优先）。

### 7.2 工具面收窄的四种流派

1. **能力协商 + 只收窄**（DSH）：`toolFilter` 过滤后工具从提示词消失且拒绝执行，未知名报错。防「以为收窄了其实没有」。
2. **配置层覆盖**（Codex）：`sandbox_mode`、`mcp_servers`、`skills.config` 按 agent 写，缺省继承父级。
3. **声明式权限规则**（OpenCode）：`{action, resource, effect}` 有序规则，最后匹配胜；**子级不继承父级副本**。
4. **名单 + 静默忽略**（ZCode）：最危险的一种——`tools` 自定义后 MCP 全失效、`mcp__server__*` 通配**静默无效**、未知 frontmatter 字段**静默忽略**。配置写错不会报错，只会「悄悄地不生效」。

### 7.3 结果回传：三种协议

- **终局文本 + 结构化 schema**（DSH）：父级只拿最终输出，`outputSchema` 走受约束的 object-rooted JSON Schema；可继续子级另有 `subagent-settled` 通知（来源 kind 与 Agent 消息区分）。
- **等待屏障 + 整合响应**（Codex）：多 agent 并行时等**全部**结果可用再返回整合响应；CSV 批处理要求每 worker 恰好一次 `report_agent_job_result`，未报告即标记 error——**这是把「结果回传」变成可校验契约的少数设计**。
- **工具输出回会话**（OpenCode / ZCode / MiniMax `task`）：子会话结果作为父会话里的一次工具返回。

### 7.4 工作区隔离：五家的共同短板

- **没有一家默认给每个 subagent 独立工作区。** 这不是实现偷懒，而是普遍的有意取舍：隔离属于「会话/环境」层，不属于「委派」层。
- Codex 走得最远：0.154.0 起 `--worktree` 实验能力，但仍是**会话级**、需自行组合（先建 worktree 再分活）。
- ZCode 把风险写进了文档：fork **不回滚磁盘**，两个会话操作同一工作区。
- DSH 在 seam 文档层面就不承担这件事，靠插件（`dsh-worktree-space` 等第三方）补。
- OpenCode 靠社区 `opencode-worktree`，其**合并用文件锁串行化**、冲突即中止并列文件，是这几家里把「并行写回合并」讲得最具体的方案。
- MiniMax 只在 Agent Team 层谈「分支 + 沙箱 + diff」的 Harness 纪律；CLI 层让用户自己在隔离工作区跑 `full` 权限。

**跨家共识（各家文档都独立说了同一件事）**：并行适合**读密集**任务（探索、审查、检索、日志分析），**并行写**必须配文件所有权或工作区隔离，否则就是「把混乱并行化」。

---

## 8. 与 `react-agent` 项目的对照（承接上一轮排查）

| 能力 | 五家做法 | `react-agent` 现状 |
|---|---|---|
| 子 Agent 角色 | ZCode/Codex/OpenCode/MiniMax 均有内置角色 + 可自定义 | `classify_tool_needs()` 中文关键词打标签，非 LLM 判断，无角色概念 |
| 工具收窄 | 声明式 + 校验 + 报错（DSH 最严） | `filter_tools()` 按 profile 取并集，关键词漏了就静默给错工具集 |
| 上下文继承 | 显式分 spawn/fork 两种 | 一律新建 `messages=[system,user]`，无 fork 概念 |
| 结果回传 | 终局文本 + 结构化契约 | `shared_data[task.id]` + 正则抠 `data = [...]` 注入下游 |
| 深度/并发上限 | Codex max_depth=1、max_threads=6；DSH maxDepth；ZCode 禁嵌套 | 无任何深度或并发上限 |
| 工作区隔离 | 无默认，靠 worktree 机制（Codex 实验性/社区工具） | **完全没有**；`ThreadPoolExecutor` 同层共享一个 cwd 直接写 |

可借鉴优先级（若后续要动手）：① 工具面收窄改为声明式并**对未知项报错**；② 增加 spawn/fork 两种上下文策略；③ 深度与并发显式设上限；④ 工作区隔离先做「文件所有权声明 + 交集检测强制串行」，成本远低于 worktree。

---

## 9. 来源清单

官方文档：
- DSH：[Subagent 子系统](https://cdn.jsdelivr.net/gh/deepseek-ai/deepseek-harness@master/docs/subsystems/subagent.zh.md) · [spawn 后端](https://cdn.jsdelivr.net/gh/deepseek-ai/deepseek-harness@master/packages/subagent/subagent-spawn-in-process/README.zh.md) · [fork 后端](https://cdn.jsdelivr.net/gh/deepseek-ai/deepseek-harness@master/packages/subagent/subagent-fork-in-process/README.zh.md)
- Codex：[Subagents](https://developers.openai.com/codex/subagents)（经[中文镜像](https://cdn.jsdelivr.net/gh/crasuna/openai-dev-docs-cn-mirror@main/docs/mirror/codex/subagents.md)读取）· [Subagent concepts](https://cdn.jsdelivr.net/gh/crasuna/openai-dev-docs-cn-mirror@main/docs/mirror/codex/concepts/subagents.md)
- OpenCode：[Agents (V2)](https://opencode.ai/v2/docs/agents) · [Agents (V1)](https://opencode.mintlify.site/agents)
- ZCode：[子智能体](https://zcode.z.ai/cn/docs/subagents) · [ZCode Agent](https://zcode.z.ai/cn/docs/agents)
- MiniMax：[Agent Team](https://agent.minimaxi.com/docs/code/agents/team) · [安全与权限](https://agent.minimaxi.com/docs/cli/security) · [能力总览](https://agent.minimaxi.com/docs/cli/features) · [Agent Team 博客](https://www.minimax.io/blog/minimax-agent-team-long-running-1779893953)

第三方（已在正文标注，不作为官方行为依据）：
- [Codex Subagents 完整指南（老金）](https://cdn.jsdelivr.net/gh/KimYx0207/AI-Coding-Guide-Zh@main/docs/codex/CX-08-Codex-Subagents%E5%A4%9AAgent%E5%8D%8F%E4%BD%9C%E5%AE%8C%E6%95%B4%E6%8C%87%E5%8D%97.md)
- [MiniMax model-router 技能](https://skillsmp.com/creators/minimax-ai/minimax-code-plugins/plugins-antianqi-codex-harness-patterns-skills-model-router)（含 `task` schema 校验结论）
- [`opencode-worktree`](https://pkg.go.dev/github.com/danhenton/opencode-worktree) · [`zcode-executor`](https://github.com/KyoMio/zcode-executor) · [`zcode-loop-orchestra`](https://github.com/LEO001020/zcode-loop-orchestra) · [`dsh-worktree-space`](https://github.com/kangtsang/dsh-worktree-space) · [`dsh-subagent-library`](https://github.com/MaRi23333/dsh-subagent-library)
- [DSH 多 Agent 实战（七牛云）](https://news.qiniu.com/archives/1788251125637)
