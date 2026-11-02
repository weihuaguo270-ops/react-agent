# AI 审核总流程下的 CI 子系统迁移计划

## 1. 目的

AI 审核是代码变更保障的顶层编排；CI 是其中负责确定性执行和合并门禁输入的子系统。本计划只迁移 CI 的执行契约，不把 AI findings、风险审批、发布观察或 Harness/Evaluation 评分复制进 CI。

目标边界：

| 子系统 | 负责内容 | 输出 |
|---|---|---|
| AI Review | 生命周期、diff 审核、findings、风险和审批编排 | `pass/review_required/fail/blocked` |
| CI | diff 选择、lint、受影响测试、PR readiness、stage gate、required checks、安全确定性检查 | `pass/fail/blocked` 与结构化证据 |
| Security | Secret、依赖、权限、workflow 和不可信代码边界 | 安全结论和 findings |
| Harness/Evaluation | Fixture、Runner、评分、Replay、Episode、Trajectory 和长期 evidence | evidence-only artifact |
| Release/Deployment | 发布、观察、回滚和渠道管理 | 发布观察与回滚证据 |

AI Review 的权威定义见 [AI 审核与变更保障 Spec](../ai-review/spec.md)。

## 2. CI 稳定契约

### 2.1 PR 门禁

PR 事件产生 `CI / PR readiness` 和 `CI / PR gate` 两个稳定 job。readiness 检查当前基线、changed files、Registry 映射、`check_pr_ready.py` 和阶段声明；gate 聚合 readiness、lint、受影响 subset、stage gate、安全和 required checks。最终只有 `CI / PR gate` 进入 Branch Protection。

### 2.2 选择规则

Registry 只维护路径到规则和 gate 入口的映射。当前迁移先以 report-only 记录选择结果：映射明确时记录最小相关 subset；映射不明确时回退到完整确定性 PR CI，base/head 缺失或 SHA 不匹配时标记 `blocked`。完整回退不包含 Harness/Evaluation 长测、真实 LLM 或日跑，且在观察期内不改变 required checks。

### 2.3 阶段 gate

代码、配置或阶段完成声明变化时，CI 调用对应方向的 gate。方向 Spec 负责阶段语义和 evidence；CI 只负责触发、绑定当前 head SHA、读取退出码和聚合状态。`progress.yaml` 不是所有 Spec 的通用进度源。

### 2.4 外部评测

完整矩阵、真实 LLM、日跑、Harness acceptance 和长期趋势默认 evidence-only。它们失败时生成可定位 artifact 或 issue；只有独立发布 gate 明确提升后才阻断发布，不改变普通 PR 的 CI 结论。Harness/Evaluation 不把评分或 Replay 语义交给 AI Review 或 CI 重新定义。

## 3. CI 子系统迁移阶段

### Phase 0：基线冻结

记录当前 workflow、required checks、事件、权限、失败分类和近期运行样本。基线只说明当前 CI 合并风险，不把现有评测矩阵当作新架构。

### Phase 1：Registry 与选择器

- 定义并校验 `path_globs -> rule_id -> gate` 的机器可读结构；
- 为 lint、单测、PR readiness、stage gate 和安全检查建立最小规则；
- 增加重复 ID、失效路径、无约束命令、过期例外和 unmapped 的负例；
- 用冻结 PR 样本回放选择器，报告误选、漏选和未映射路径；
- 不把 Harness 场景、评分或 `PHASE_TESTS` 复制到 Registry。

### Phase 2：Shadow

新选择器和聚合器先 report-only，与现有 workflow 在相同 PR head SHA 上比较选择结果、状态语义、失败归因和时长。观察窗口内不改变旧 required checks。

### Phase 3：PR 快门禁

启用代表性环境加受影响 subset 的快速硬门禁前，必须完成 report-only 观察。固定样本没有漏选、选择器失败时稳定回退完整确定性 PR CI，且全映射 PR 的中位验证耗时至少下降 20% 后，才允许切换。观察期仍保留现有完整 OS/Python PR 检查；切换后，未被选择的矩阵和真实 LLM 继续作为 evidence-only。Evaluation/Harness 长测不进入普通 PR 回退。

### Phase 4：Branch Protection 切换

在 Phase 2/3 的误报、漏报、取消和权限问题有证据关闭或有明确 owner 后，将 `CI / PR gate` 提升为唯一 required check，保留可逆观察窗口，再移除旧的单 job required checks。切换必须验证普通 PR、fork PR、重跑、并发取消和当前 head SHA 绑定。

### Phase 5：稳定化

按真实 PR 失败数据复盘规则覆盖、时长和未映射率；成熟的完整矩阵按独立发布策略逐项提升。任何提升都必须有 owner、时长目标、回滚方法和安全审查。

## 4. AI Review 独立实施阶段

AI Review 不隶属于 CI 的 Phase 0–5，另行按其顶层 Spec 实施：

- **A0：架构与契约**：冻结生命周期、角色边界、artifact schema 和状态语义；
- **A1：离线审核**：使用固定 diff、Spec 和测试上下文生成结构化报告；
- **A2：PR report-only**：在当前 head SHA 上运行，不改变合并门禁；
- **A3：风险与审批编排**：接入 Security、CI 和人工审批要求；
- **A4：合并与合并后观察**：接入合并队列、发布观察、回滚和审计证据。

## 5. 失败与回滚

代码/配置错误、受影响检查失败、PR readiness 失败、stage gate 失败、安全检查失败、聚合输入缺失和完整确定性回退失败阻止 CI 合并输入。映射不完整本身先生成 report-only 证据并触发完整确定性回退；完整评测或真实 LLM 的失败默认只生成 evidence。

发现聚合器误报、漏报、无法创建或显著超时后，暂停提升 required checks，恢复上一版 Branch Protection 名称，保留 artifact 和失败样本，修复选择器/聚合器后从 Shadow 重新观察。回滚不删除历史 evidence，也不修改方向 Spec 的阶段完成记录。

## 6. 验收清单

- 当前 diff 能追溯到选择的规则、命令和 head SHA；
- lint、受影响单测、`check_pr_ready.py`、适用 stage gate 和安全检查均可单独定位；
- 缺失输入和完整确定性回退失败 fail closed；未映射路径必须记录并回退，不能静默缩减检查；
- 未映射路径回退到完整确定性 PR CI，不能静默缩减检查或触发长时 Evaluation/Harness；
- `CI / PR gate` 稳定创建且是唯一合并聚合器；
- CI 结果可被 AI Review 消费，但 CI 不依赖 AI Review 才能产生自身确定性结论；
- AI findings、风险和审批由 AI Review Spec 管理；
- Harness 评测结果与 CI 合并结论分层展示；
- docs 变更执行 git-docs evaluation，并在断言仍有效时刷新 baseline。

## 7. 相关文档

- [CI 执行子系统 Spec](spec.md)
- [AI 审核与变更保障 Spec](../ai-review/spec.md)
- [Harness 构建与统一契约 Spec](../harness/spec.md)
- [Phase 0 基线](evidence/phase0-baseline.md)
- [PR 就绪审计脚本](../../../scripts/ci/check_pr_ready.py)
