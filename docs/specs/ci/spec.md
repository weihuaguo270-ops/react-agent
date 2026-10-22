# CI 质量门规格

## 1. 文档状态

**状态：** Proposed  
**版本：** v1.2  
**最后更新：** 2026-10-22  
**负责人：** 仓库维护者（CI、Registry、各方向和 Branch Protection 角色由该维护角色承担）

本文档是 CI 模块的长期约束入口。阶段目标、迁移顺序和切换条件见
[redesign-plan.md](redesign-plan.md)，不得把阶段完成状态解释为永久规则。

## 2. 概述

### 2.1 目标

CI 对每个变更提供可重复、可定位、与变更范围相称的质量信号：阻止已知合并风险，生成可追溯的阶段验收证据，并把离线 fixture、历史结果和生产能力分开表达。CI 不应把所有现有脚本串成一条无边界的长任务，也不应用一次全量运行替代覆盖设计。

### 2.2 范围

#### 包含

- PR 快速硬门禁、完整矩阵和阶段验收报告。
- test.yml、daily-smoke.yml 及替代检查的触发、状态和迁移契约。
- 变更路径到测试门禁的 Registry、未映射变更处理和覆盖率指标。
- GitHub Branch Protection 的 required check、fork PR 安全边界和 evidence 保留。
- 本地 pre-commit 子集与 CI 完整规则的职责边界。

#### 不包含

- 业务方向 Spec 的内容、业务进度本身或生产 SLA 承诺。
- 把离线/fixture/mock 结果升级为真实 LLM、在线流量或跨硬件结论。
- 在本 Spec 中直接修改 GitHub Branch Protection、Secret 或远程分支。

### 2.3 依赖

- .github/workflows/test.yml
- .github/workflows/daily-smoke.yml
- scripts/ci/check_pr_ready.py
- progress.yaml
- docs/specs/registry.yaml（当前 registry 的迁移目标，字段以本 Spec 为准）
- GitHub Actions Branch Protection 和 artifact 服务

## 3. 术语与权威源

- **硬阻断（blocking）：** 作为 Branch Protection required check 的稳定聚合结论；失败、未完成或 mapping 不完整时不能合并。
- **阶段证据（evidence-only）：** 可在 PR、artifact 或 Spec evidence 文件中阅读，但不单独成为 required check；报告 complete、partial、review 或 not-applicable。
- **阶段完成声明：** progress.yaml 中某阶段的 status 从非 complete 变为 complete。PR 标题、标签和正文只能作为辅助说明，不能单独触发阶段 gate。
- **Registry 覆盖率：** 本次变更中被至少一条 Registry path_globs（扣除 exclude_globs）明确映射的文件数除以需要门禁的变更文件数。非执行性文档可单独计数，但必须出现在报告中。
- **权威进度源：** 当前为仓库根目录 progress.yaml。若未来迁移，必须在一个 PR 中同时更新本 Spec、Registry 和校验器，并保留字段映射。

## 4. 长期 Requirements

### R1: 稳定聚合门禁与 Branch Protection

**优先级：** P0  
**状态：** Proposed

迁移完成后必须始终创建两个稳定 job，并使用固定名称：`CI / PR readiness` 和 `CI / PR gate`。`CI / PR readiness` 负责 PR 就绪性、阶段声明和 Registry 输入检查；它是 `CI / PR gate` 的输入，不直接作为 Branch Protection required check。`CI / PR gate` 聚合 readiness、受影响规则和安全结果，是迁移完成后唯一的合并硬门禁。具体矩阵 job、条件 job、日跑 job 和阶段报告 job 不直接加入 required checks。

在 Phase 2/3 的双轨期，两个聚合 job 必须照常创建但只报告，不改变当前 9 个旧 required checks。Phase 4 切换时只新增 `CI / PR gate`，保留一个观察窗口后再移除旧的单 job required checks；`CI / PR readiness` 保留为稳定输入和可读报告。若任一聚合 job 缺失、skipped、cancelled、timed_out、action_required 或没有对应当前 head SHA 的结论，`CI / PR gate` 必须输出 `blocked` 或 `fail`，不能把缺失折算为通过。

CI / PR gate 至少聚合代码/配置语法、受影响的离线回归、最小导入和打包检查、必需的安全检查、Docker smoke（Docker 路径变化或该检查被标记为 P0 时）以及映射完整性。聚合器必须在所有输入 job 结束后显式写出 pass、fail、blocked 或 mapping-incomplete；任何未完成、取消、权限错误或输入缺失都不能折算为通过。

阶段验收报告、完整 OS/Python 矩阵、真实 LLM smoke 和日跑方差属于 evidence-only，除非单独的发布 gate 明确把它们提升为 required。提升前必须满足 Phase 4 准入条件。

**验收标准：**

- [ ] `CI / PR readiness` 和 `CI / PR gate` 在 PR、重跑和条件分支上都会创建；迁移完成后只有 `CI / PR gate` 是 required check。
- [ ] failure、cancelled、timed_out、action_required、缺失输入和 mapping-incomplete 均使聚合器失败或阻塞。
- [ ] `CI / PR gate` 对 readiness 缺失、输入 job 缺失或 head SHA 不匹配给出可定位的失败原因。
- [ ] 阶段 evidence 不会因 progress.yaml 普通编辑自动成为合并硬门禁。

### R2: 阶段完成声明的机器检测

**优先级：** P0  
**状态：** Proposed

CI 在 PR base 与 head 上解析同一份 progress.yaml。当任一阶段的 status 从非 complete 变为 complete，或在已有 complete 阶段新增/替换完成 evidence 字段时，PR 被标记为声明阶段完成，并运行对应 Registry gate 和 evidence 校验。PR 标题、phase 标签和正文可以改善可读性，但缺失这些文本不能绕过机器检测。

如果文件结构无法解析、同一阶段出现冲突状态、完成状态没有对应 evidence，CI 必须 fail closed：CI / PR gate 不通过，同时在 summary 中指出字段路径和修复方式。没有状态变化的文档修订只运行普通文档/语料检查，不运行阶段 gate。

**验收标准：**

- [ ] 测试覆盖非完成到完成、完成到完成补证据、无变化、非法 YAML 和冲突字段。
- [ ] 每个被声明完成的阶段都有 gate 命令、head SHA、退出码和 evidence URI。
- [ ] PR 文本与 progress.yaml 冲突时，以 progress.yaml 为权威并报告冲突。

### R3: 可校验的 Spec/测试 Registry

**优先级：** P0  
**状态：** Proposed

**阶段边界：** R3 的 P0 部分只验收 Registry v2 Schema 文件存在、JSON 语法有效，以及仓库路径规则等关键安全约束的最小冒烟检查。P0 不把完整 JSON Schema 正负例套件、语义校验器或规则匹配测试作为已完成条件。完整的有效/无效 fixture 校验、语义约束和验收矩阵属于 Phase 1，必须由 Phase 1 的独立 gate 报告通过后，才能宣称 Registry v2 校验完成。

Registry 是路径选择和门禁归属的唯一索引。当前仓库 `docs/specs/registry.yaml` 仍声明 `spec-registry/v1`，现有 `spec_workflow.py validate` 也只校验 v1；[registry-v2.schema.json](registry-v2.schema.json) 是本轮定义的 v2 机器可读结构契约，下方示例帮助阅读。该 JSON Schema 不能替代 Phase 1 的语义校验器：跨规则 ID 唯一性、路径存在性、gate 引用、例外到期和路径授权仍需代码与测试。当前 v1 validate 通过不构成 v2 验收证据。每个方向至少包含以下字段：

    schema_version: spec-registry/v2
    directions:
      <direction_id>:
        display_name: "..."
        owner: "repository_maintainers"
        goal: "docs/specs/goals/<id>.md"
        progress_source: "progress.yaml"
        source_spec: "docs/specs/<id>/spec.md"
        rules:
          - id: "<stable-rule-id>"
            path_globs: ["src/<area>/**", "tests/<area>/**"]
            exclude_globs: ["docs/**"]
            gate:
              argv: ["python", "-m", "pytest", "tests/<area>"]
              working_directory: "."
              timeout_minutes: 15
              network: "none|allowlist"
              allowed_domains: []
              secret_refs: []
              write_paths: ["artifacts/ci/<rule-id>/**"]
              # argv executes directly; do not invoke a shell.
            priority: P0
            execution: "automated|manual"
            local: "subset|none"
            evidence: "artifacts/ci/<rule-id>/"
            applicability: "always|changed|stage-claim|nightly|release"
            maintainer: "repository_maintainers"
            reviewer_role: "repository_maintainers"
            approver_role: "repository_maintainers"
        unmapped:
          - id: "unmapped-<stable-id>"
            path_globs: ["<path/**>"]
            reason: "why no rule is safe yet"
            safety_gate_rule_id: "ci-unmapped-safety"
            owner: "repository_maintainers"
            expires_at: "YYYY-MM-DD"
        exceptions:
          - id: "exception-<stable-id>"
            rule_id: "<stable-rule-id>"
            reason: "bounded one-time exception"
            approved_by_role: "repository_maintainers"
            approved_at: "YYYY-MM-DDThh:mm:ssZ"
            expires_at: "YYYY-MM-DD"
            evidence: "artifacts/ci/exceptions/<id>/"

priority 只允许 P0/P1/P2，人工执行由 execution: manual 表达；人工规则必须提供 reviewer/approver 角色和 evidence 要求。自动 gate 的 `argv` 数组直接执行，不经 shell；`working_directory` 必须位于仓库内，`timeout_minutes` 必须为正数，`network: allowlist` 时必须列出域名，`secret_refs` 必须显式列出，`write_paths` 只能指向该规则的 evidence 目录。`unmapped` 必须引用固定 P0 安全子集 rule、owner、原因和到期日；`exceptions` 必须绑定规则、审批角色、原因、到期日和 evidence。not-applicable 是每次运行的适用性结论，不是 priority，也不是通过状态。

校验器必须检查唯一 direction_id、唯一 rule id、路径存在性、合法 priority/applicability/execution、自动规则 gate argv、工作目录和执行约束、人工规则审批角色、evidence 目标、owner、unmapped 到期日和 exception 审批字段。现有 test.yml 的每个逻辑测试组先登记为一条 rule；无法安全归属的命令登记为 unmapped，不得静默删除。Registry 由仓库维护者维护，方向 owner 角色审核路径和 gate，变更 Registry 的 PR 必须带迁移 evidence。

**验收标准：**

- [P0] Registry v2 Schema 文件可解析，仓库路径规则的关键穿越/绝对路径负例冒烟检查通过。
- [P1] Registry v2 Schema 有完整机器校验和针对重复 ID、空 glob、失效路径的测试；v1 校验通过不能替代此项。
- [ ] 自动、人工、N/A 三种执行/适用性结果有不同字段和聚合语义。
- [ ] 现有 test.yml、daily-smoke.yml 的逻辑组都有迁移表和 owner。
- [ ] 多规则命中时按 P0/P1/P2 合并并去重，且同一 rule 只执行一次。
- [ ] `unmapped`、人工 exception 和自动 gate argv/timeout/network/secret 范围都有 schema、负例测试和 JSON 报告字段。
- [ ] 人工规则没有 reviewer/approver、自动规则没有 gate 执行约束或 exception 缺少到期日时，校验器失败。

### R4: 映射覆盖、回退和时间预算

**优先级：** P0  
**状态：** Proposed

Phase 0 冻结 PR/run 样本与 wall-clock 分布。当前 Registry v1 没有 path rules，因此 Phase 0 不伪报历史映射覆盖率；Phase 1 完成 v2 候选映射后，必须对冻结 PR 样本做离线 backtest，并在 Phase 2 shadow 前报告覆盖率、未映射路径和误选/漏选。映射覆盖率达到经批准的阈值（初始建议至少 90%，最终值以不少于 30 个可用 PR 样本校准）后，才启用严格的 P95 时间目标。阈值未达到时报告 mapping-incomplete，允许超时作为迁移期例外，但不得把未映射文件当作无影响。

未映射变更不直接触发无界全量测试。PR gate 运行固定的 unmapped-safety 子集（语法、导入、最小离线回归、配置/Schema 校验），同时让聚合器保持 mapping-incomplete 阻塞，要求 Registry owner 补映射，或由 CI owner 在 PR review 中留下带原因和到期时间的一次性例外批准。例外不能绕过其他失败检查，且必须进入 evidence。全量回退只允许在日跑、发布 gate 或明确的手工 dispatch 中运行，并单独计入时长。

15 分钟是待基线校准的目标假设，不是当前永久硬门槛。校准后分别记录快门禁 P50/P95、完整矩阵 P50/P95、队列等待和安装时间；硬超时只能在样本量和环境稳定后写入 Branch Protection 策略。

**验收标准：**

- [ ] 报告包含映射覆盖率、未映射列表、选择的 rules 和每个 job 的 wall-clock。
- [ ] 映射不足时聚合器阻塞，不会静默全量或静默放行。
- [ ] P95 目标批准记录包含样本数、环境、异常值处理和复核日期。

### R5: 分层矩阵与 fail-fast 策略

**优先级：** P0  
**状态：** Proposed

PR 快门禁使用一条代表性环境（默认 Ubuntu、Python 3.11）加受影响规则的最小测试集。Python 3.10/3.11、Windows、完整离线评估和跨仓库契约进入日跑或发布 gate；只有在 Phase 4 通过稳定性和时长准入后，才逐项提升为 required。

快门禁可对同一规则启用 fail-fast；证据矩阵必须关闭 fail-fast 或保留已启动分片的结果，保证失败归因和 artifact 完整。一个 job 失败不能取消无关 evidence job；取消、队列超时和安装失败都必须显式报告。

### R6: not-applicable、skipped 与聚合状态

**优先级：** P0  
**状态：** Proposed

GitHub 没有独立的 not-applicable required-check 状态。条件 job 可以 skipped，但不直接加入 Branch Protection。始终创建的聚合器读取规则适用性并报告 not-applicable，然后按规则配置决定聚合结果：不适用的 P1/P2 规则不阻塞；P0 规则若无法判定适用性则阻塞并要求人工确认。skipped、缺失 job 和聚合器未运行不能被解释为通过。

### R7: Evidence 形态、权威源和保留

**优先级：** P0  
**状态：** Proposed

合法 evidence 必须包含规则 ID、gate 命令、head SHA、运行时间、退出码、测试摘要、适用性、artifact URI 及 SHA-256（如有）、聚合结论和阶段字段路径。原始日志、JSON/JUnit 报告和诊断输出存 GitHub Actions artifact；PR check summary 只放结论、关键失败和 artifact 链接；阶段长期结论写入 docs/specs/<module>/evidence/，并由 progress.yaml 引用。

建议 PR artifact 保留 30 天，发布/阶段验收 artifact 保留 180 天；最终期限由仓库设置确认并记录。文档、fixture 或历史报告可以说明预期和背景，但不能单独证明本次运行通过。没有 head SHA 或无法读取的 artifact 不得作为完成证据。

### R8: 本地 pre-commit 与 CI 完整规则

**优先级：** P1  
**状态：** Proposed

本地检查与 CI 共用 Registry 和规则实现，但不追求相同重量：

| 内容 | 本地提交前 | PR CI | 日跑/发布 |
|---|---|---|---|
| 格式、语法、快速 lint | 必须 | 必须 | 必须 |
| 受影响 P0 单测/导入/Schema | 必须 | 必须 | 必须 |
| 完整 Python/Windows 矩阵 | 可选 | evidence-only | 必须或发布 gate |
| Docker、跨仓库契约 | 可选 smoke | 按路径或 P0 | 必须 |
| 真实 LLM、长时方差 | 不运行 | evidence-only | 按 Secret/调度运行 |

本地通过不等于 CI 通过；CI 规则新增或变更时必须更新本地 subset 映射，避免两套规则漂移。

### R9: 安全、fork PR 和依赖固定

**优先级：** P0  
**状态：** Proposed

默认使用 pull_request 执行不可信代码，权限按 job 最小化，fork PR 不读取写入 Secret。禁止使用 pull_request_target checkout 或执行 PR 提交内容；确需维护者批准的写操作时，必须拆成不执行不可信代码的独立 job，并记录理由。Actions 和外部依赖使用固定 commit SHA 或仓库批准的受控版本，网络下载、兄弟仓库和 Docker 基础镜像都必须可追溯。任何需要 contents: write、pull-requests: write 或 actions: write 的自动化必须与普通 PR gate 分离。

### R10: 结论边界和可追溯性

**优先级：** P0  
**状态：** Proposed

CI 报告必须标明 offline、fixture、mock、real-llm、production-like 等运行模式。历史通过、阶段 evidence、当前 head 的 fresh rerun 和生产/SLA 结论分开计数。任何 Spec 完成声明都需要当前 head 的 gate 结果和可读取 evidence，不能只引用旧 PR 或文档中的数字。

## 5. Phases

阶段定义、退出标准、双轨迁移和回滚在 [redesign-plan.md](redesign-plan.md) 中维护。阶段完成不会自动改变本节的长期约束。

## 6. 风险与限制

- GitHub 对条件 job 的 required-check 语义受 workflow 事件和 job 创建时机影响，必须以稳定聚合器隔离。
- 现有 CI 含大量跨仓库、Docker 和评估脚本，Phase 0 前不能假设每个命令都适合 PR 快门禁。
- 15 分钟、90% 映射覆盖率等数字是校准起点，不是未经基线批准的事实。
- daily-smoke.yml 目前包含提交、开 PR 和合并自动化；该写操作路径必须与普通 PR gate 分开审计。

## 7. 相关文档

- [CI 重构目标与阶段计划](redesign-plan.md)
- [Spec 编写标准](../SPEC_WRITING_STANDARD.md)
- [Spec 组织规则](../ORGANIZATION_RULES.md)
- [当前测试工作流](../../../.github/workflows/test.yml)
- [当前日跑工作流](../../../.github/workflows/daily-smoke.yml)
