# CI 重构目标与阶段计划

## 1. 文档状态

**状态：** Proposed  
**版本：** v1.2  
**最后更新：** 2026-10-22  
**负责人：** 仓库维护者（CI、Registry、各方向和 Branch Protection 角色统一由仓库维护者承担）

本文件是路线图，不是长期约束清单。长期规则见 [spec.md](spec.md)。

## 2. 重构目标

重构后的 CI 应让维护者能回答四个问题：这次变更影响了哪些规则、哪些规则实际运行了、失败能否定位、阶段完成是否有当前提交的证据。PR 快门禁负责快速发现合并风险；日跑和发布 gate 负责完整矩阵、长时方差和跨环境证据；阶段 gate 负责验证 progress.yaml 的完成声明。三类结果通过稳定聚合器和统一 evidence 关联，但不混成一条无边界的长任务。

## 3. 基线与假设

Phase 0 必须先读取现有 test.yml、daily-smoke.yml、最近 PR 运行和 Branch Protection 设置。目标样本优先取最近 100 个 PR；若仓库不足 100 个，记录实际 N，最低建议 30 个可用 PR，低于该数只能形成 provisional baseline。所有百分位数都要注明样本数、环境、取消/排队运行是否剔除。

“PR 快门禁 P95 不超过 15 分钟”是待校准的假设。若基线显示安装、队列或跨仓库下载使其不现实，Phase 0 必须提出新的目标和理由，不能把未经测量的数字直接变成硬门禁。

## 4. 现有到目标的迁移映射

| 现有工作流 | 迁移阶段 | 目标职责 | 初始 required 状态 |
|---|---|---|---|
| test.yml 的 pr-ready | Phase 2 | `CI / PR readiness` 输入 | report-only；由 `CI / PR gate` 聚合 |
| test.yml 的 lint、typecheck、security、Docker smoke | Phase 2-3 | P0/P1 规则和最小 PR gate | 先 report-only，再按稳定性提升 |
| test.yml 的 Python/Windows 矩阵 | Phase 2 | 完整环境 evidence | 日跑/发布 gate |
| test.yml 的评估与跨仓库契约 | Phase 1-3 | Registry 规则、阶段或发布 evidence | 默认 report-only |
| daily-smoke.yml | Phase 2 | 长时方差和可选真实 LLM smoke | 不加入普通 PR required |
| 新 `CI / PR gate` | Phase 3 | 唯一稳定聚合硬门禁 | Phase 4 后 required |

目标 required 关系固定为：

| 检查名称 | Phase 2/3 | Phase 4 后 | 语义 |
|---|---|---|---|
| `CI / PR readiness` | 始终创建，report-only | 始终创建，非 required | readiness、阶段声明、Registry 和 evidence 输入；缺失时 gate blocked |
| `CI / PR gate` | 始终创建，report-only | 唯一 required 聚合检查 | 聚合 readiness、受影响 P0/P1 规则、安全和 mapping 结论 |

两个检查都必须绑定当前 PR head SHA。`CI / PR readiness` 缺失、取消、超时、action_required 或 head SHA 不匹配时，`CI / PR gate` 必须为 blocked/fail；只有 readiness 明确报告适用且通过时，gate 才能继续聚合。

双轨期间旧工作流继续运行，新工作流以 shadow/report-only 方式比较选择结果、状态和时长。禁止在比较完成前删除旧工作流或直接替换 required check 名称。

## 5. 阶段计划

### Phase 0: 基线冻结与责任确认

**目标：** 记录当前失败分布、时长、required checks、事件和安全配置，形成可复核的起点。

**交付物：**

- [x] docs/specs/ci/evidence/phase0-baseline.md
- [x] 逐样本 PR/run 索引（实际 N、run ID、head SHA、失败 job/step、失败分类、运行模式）
- [x] 当前 Branch Protection required check 清单
- [x] 现有 test.yml/daily-smoke.yml 到逻辑测试组的初步迁移表

**当前状态：** Partial。汇总和逐样本证据已记录在 [Phase 0 基线报告](evidence/phase0-baseline.md) 及其 JSON 索引；CI、Registry、方向和 Branch Protection 责任均已指定为仓库维护者。v2 JSON Schema 结构契约已定义，但 Registry 仍为 v1，Phase 1 语义校验器和测试尚未启动；Spec/迁移计划仍需独立复审后才能进入 Phase 1。

**Schema 校验边界：** Phase 0 只确认 v2 Schema 的契约文件、语法和关键路径安全冒烟检查；完整正负例 fixture、JSON Schema 机器校验、语义校验器和规则匹配测试统一放在 Phase 1。Phase 0 的 Schema 冒烟通过不能替代 Phase 1 验收。

**验收标准：**

- [x] 每个频繁失败模块至少有 job、步骤、错误类别和可复现入口。
- [x] 区分代码失败、环境/依赖失败、权限/Secret 失败、取消/并发失败和测试断言失败。
- [x] 明确哪些失败来自当前 PR head，哪些只是历史运行。
- [x] 指定 Registry owner、阶段 progress owner 和 Branch Protection owner：均为仓库维护者角色，不臆造个人姓名。

**退出条件：** 基线证据可由第三方按 run ID、head SHA 和命令复核。`phase0-baseline.json` 的 `pull_requests.samples[]`、`workflows.test.yml.runs[]` 和 `workflows.daily-smoke.yml.runs[]` 是逐样本索引；每个失败/取消运行包含 job、step、分类和分类依据，复现命令集中在 `reproduction` 字段。样本不足时允许退出，但必须标注 provisional，并禁止据此固化 15 分钟等硬数字。

### Phase 1: Registry 与阶段信号

**目标：** 建立唯一测试映射和“声明阶段完成”的机器判定。

**交付物：**

- [x] Registry v2 的机器可读 JSON Schema 结构契约：[registry-v2.schema.json](registry-v2.schema.json)
- [ ] Registry v2 JSON Schema 正负例校验、语义校验器和单元测试（当前 v1 校验器不视为完成）
- [ ] 现有 test.yml/daily-smoke.yml 的规则迁移清单
- [ ] 对 Phase 0 冻结 PR 样本做 Registry path 选择器离线 backtest，报告覆盖率、误选/漏选和 unmapped 路径
- [ ] progress.yaml base/head 比较器和非法状态测试
- [ ] 未映射变更报告与 unmapped-safety gate
- [ ] R9 安全交付物：workflow 事件/权限审计、外部 Action 与 Docker 基础镜像固定版本清单、fork PR 无 Secret 证明、写权限 job 隔离证明

**验收标准：**

- [ ] 重复 rule ID、空路径、非法 priority、失效 gate 命令都会失败。
- [ ] progress.yaml 的非完成到完成变化稳定触发阶段 gate。
- [ ] 映射覆盖率、未映射路径和 fallback 状态出现在 check summary 与 JSON artifact。
- [ ] 未映射变更不会静默放行，也不会无界扩张为每个 PR 的全量运行。
- [ ] Phase 0 基线明确注明当前 v1 不具备 path rules，未伪报历史映射覆盖率；v2 的历史 backtest 在进入 Phase 2 前完成。
- [ ] 人工规则缺 reviewer/approver、owner 或 evidence，自动规则缺 gate 执行约束，或 exception 缺审批/到期日时均失败。
- [ ] 多条规则命中同一文件时按优先级合并并去重；完成阶段补 evidence、冲突状态和非法 progress 状态均有负例测试。
- [ ] 安全交付物验证 `pull_request` 隔离、fork 无 Secret、固定依赖和写权限 job 分离；普通 PR gate 不具备写权限。

Phase 1 验收矩阵（本阶段尚未启动；这些是进入 Phase 1 前冻结的测试契约）：

| 场景 | 最小测试输入 | 预期结果 |
|---|---|---|
| 重复 rule ID | 两条规则使用同一 `id` | Registry validate 失败，指出两条路径 |
| 空/失效 glob | `path_globs: []` 或不存在路径 | validate 失败 |
| 自动规则约束缺失 | 缺 `gate.argv`、working_directory、timeout、network、secret_refs 或 write_paths | validate 失败 |
| 人工规则归属/审批缺失 | `execution: manual` 但无 owner、reviewer、approver 或 evidence | validate 失败 |
| unmapped 记录不完整 | 缺 reason、safety_gate_rule_id、owner 或 expires_at | validate 失败 |
| exception 不完整/过期 | 缺审批角色、evidence 或到期日已过 | validate 失败并阻塞 |
| 多规则命中 | 一个变更同时命中 P0、P1 和重复 rule | 按 P0/P1/P2 合并，同一 rule 只执行一次 |
| 阶段状态变化 | base 非 complete，head complete 且有 evidence | 触发阶段 gate，并写 head SHA/退出码/evidence URI |
| 完成阶段补 evidence | base/head 均 complete，仅新增/替换 evidence | 触发阶段 gate |
| 无状态变化 | 只改普通文档 | 不触发阶段 gate，只运行文档规则 |
| 非法/冲突 progress | 非法 YAML、冲突状态或 complete 无 evidence | fail closed，指出字段路径 |
| 声明文本冲突 | PR 标题/正文称阶段完成但 progress.yaml 未完成，或反之 | 以 progress.yaml 为权威并在 summary 报告冲突 |
| 安全边界 | fork PR、无 Secret、固定 Action/镜像、写权限 job | 普通 PR gate 无 Secret/写权限；审计 artifact 可复核 |

### Phase 2: 双轨 Shadow 运行

**目标：** 新旧选择器并行运行，比较结论、覆盖和耗时，不改变合并规则。

**交付物：**

- [ ] 新聚合器始终创建，但标记为 report-only
- [ ] 旧 job 与新 rule 的对应关系报告
- [ ] 至少一个完整矩阵和一个日跑样本的比较 evidence
- [ ] 迁移失败时恢复旧 workflow 的操作手册

**验收标准：**

- [ ] 新旧运行使用相同 PR head SHA，不能拿不同提交比较。
- [ ] 对每个差异给出新增覆盖、遗漏、重复、状态语义或时长分类。
- [ ] Shadow 运行本身的取消、权限和 Secret 问题不会污染旧 required checks。
- [ ] 至少连续 10 个可用 PR 或两周（取较晚者）没有未解释的聚合器误报。

### Phase 3: PR 快门禁上线

**目标：** 启用代表性环境和受影响规则的快速硬门禁，完整矩阵继续作为 evidence。

**交付物：**

- [ ] `CI / PR gate` 和 `CI / PR readiness` 稳定 job；前者是唯一合并聚合器，后者作为必需输入但不直接 required
- [ ] 本地 subset 命令与 CI rule 的共享实现
- [ ] 快门禁时长、mapping coverage 和失败归因报告

**验收标准：**

- [ ] 聚合器在 job skipped、cancelled、action_required、timeout 和缺失输入时给出明确非通过状态。
- [ ] 映射覆盖率低于批准阈值时阻塞并指向 owner，不直接跑无界全量。
- [ ] 基线校准后的 P95 目标连续满足两个观察窗口；若未满足，更新目标而不是隐藏超时。
- [ ] fork PR 不获得 Secret，普通 PR gate 不执行写操作。

### Phase 4: Branch Protection 切换

**目标：** 仅在新聚合器稳定后切换 required checks，保留可逆迁移窗口。

**准入条件：**

- [ ] Phase 2/3 的误报、漏报和取消原因已关闭或有 owner/截止日期。
- [ ] 至少 20 个新 PR head 的聚合结果可复核；若样本不足，写明限制并由仓库 owner 明确批准。
- [ ] required check 名称稳定、永远创建，且与当前 PR head SHA 绑定。
- [ ] 回滚动作已在 staging 或演练 PR 中验证。

**切换动作：**

1. 先把 `CI / PR gate` 加入 Branch Protection，同时保留旧 required check 一个观察窗口；`CI / PR readiness` 继续作为稳定输入，不直接加入 required checks。
2. 确认两个聚合 job 在普通 PR、fork PR、重跑和并发取消场景均能创建并绑定当前 PR head SHA。
3. 移除旧的单 job required checks，旧 workflow 继续保留为 shadow 或 evidence。
4. 在仓库变更记录中写入切换时间、操作者、required check 名称和回滚版本。

### Phase 5: 稳定化与按需扩展

**目标：** 根据真实失败数据调整规则边界，把成熟的完整矩阵逐项提升为发布 gate 或 required。

**交付物：**

- [ ] 每月 Registry 未映射率、失败类别和时长复盘
- [ ] 日跑 artifact 和阶段 evidence 的保留/清理策略
- [ ] 完整 Python/Windows、Docker、跨仓库和真实 LLM gate 的逐项准入记录

**验收标准：**

- [ ] 新增路径、测试和工作流必须有 Registry 规则或明确的 unmapped 记录。
- [ ] 每个被提升为 required 的检查都有独立 owner、时长目标、回滚方法和安全审查。
- [ ] production-like、real-llm、offline、fixture 和历史结果在报告中保持独立标签。

## 6. 失败处理、切换和回滚

### 硬阻断

代码/配置错误、受影响 P0 回归失败、安全检查失败、聚合输入缺失、阶段完成声明缺 evidence、Registry 解析失败和未处理的 mapping-incomplete 都阻止合并。

### 只报告证据

完整 OS/Python 矩阵、日跑方差、真实 LLM smoke、非当前方向的阶段报告和历史趋势默认只报告。它们失败时创建可定位 issue 或 PR comment；如果发布 gate 需要阻断，必须由 Phase 4/5 的独立配置提升，不能通过修改普通 PR 文本临时改变语义。

### 回滚

发现新聚合器误报、漏报、无法上报或显著超时后：暂停提升新的 required check，恢复上一版 Branch Protection required 名称，保留新 workflow 的 artifact 和失败样本，修复 Registry/聚合器后从 Phase 2 的 shadow 重新观察。回滚不删除历史 evidence，也不重写 progress.yaml 的阶段完成记录。

## 7. 阶段证据模板

每个阶段 evidence 至少记录：目标和状态、提交 head SHA、运行/比较的 run ID、Registry 版本、gate 命令及退出码、样本数、通过/失败/取消/不适用数量、artifact 链接和 hash、未解决问题、owner 与下一步。Phase 0 的逐样本索引还必须能从 run ID 追到 head SHA、PR（若可精确匹配）和失败 job/step。只有当前 head 的可读取运行结果可以把阶段标为 complete。

## 8. 相关文档

- [CI 长期约束与边界](spec.md)
- [当前进度源](../../../progress.yaml)
- [PR 就绪审计脚本](../../../scripts/ci/check_pr_ready.py)
