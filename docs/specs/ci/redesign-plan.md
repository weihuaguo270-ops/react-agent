# CI 合并门禁收敛计划

## 1. 目的

当前 CI 文档同时描述合并门禁、Spec 阶段、Evaluation Harness、完整评测矩阵和长期 evidence，造成职责重复和执行成本失控。本计划把 CI 收敛为一个交付控制平面：判断当前变更能否合入 `main`；把评测执行、评分、Replay、长期趋势和生产质量结论留在 Harness 或日跑/发布系统。

目标架构：

| 平面 | 负责内容 | 输出 |
|---|---|---|
| CI | diff 选择、lint、受影响单测、PR ready、stage gate 调度、required checks、安全 | 当前 head 的 `pass/fail/blocked` |
| 方向 Spec | 阶段目标、阶段命令、唯一 progress source、阶段 evidence | 方向阶段 gate 结果 |
| Evaluation Harness | Fixture、Runner、评分、Replay、Episode、Trajectory、评测 artifact | 可复核评测 evidence |
| 日跑/发布 | 完整矩阵、长时方差、真实 LLM、跨环境质量 | evidence-only 或独立发布结论 |

CI 可以调用后两层的入口，但不复制它们的内部语义。

## 2. 收敛后的稳定契约

### 2.1 PR 门禁

PR 事件产生 `CI / PR readiness` 和 `CI / PR gate` 两个稳定 job。readiness 检查当前基线、changed files、Registry 映射、`check_pr_ready.py` 和阶段声明；gate 聚合 readiness、lint、受影响 subset、stage gate、安全和 required checks。只有 `CI / PR gate` 进入 Branch Protection required checks。

### 2.2 选择规则

Registry 只维护路径到规则和 gate 入口的映射。映射明确时运行最小相关 subset；映射不明确时运行固定安全子集并标记 `blocked`，要求补映射或审批有期限的例外。普通 PR 不因为映射不清而静默放行或无界全量回退。

### 2.3 阶段 gate

代码、配置或阶段完成声明变化时，CI 调用对应方向的 gate。方向 Spec 负责阶段语义和 evidence；CI 只负责触发、绑定当前 head SHA、读取退出码和聚合状态。`progress.yaml` 不再被定义为所有 Spec 的通用进度源。

### 2.4 外部评测

完整矩阵、真实 LLM、日跑、Harness acceptance 和长期趋势默认 evidence-only。它们失败时生成可定位的 artifact 或 issue；只有独立发布 gate 明确提升后才阻断发布，不改变普通 PR 的职责。

## 3. 迁移阶段

### Phase 0：基线冻结

记录当前 workflow、required checks、事件、权限、失败分类和近期运行样本。基线只说明当前合并风险，不把现有评测矩阵当作新 CI 架构。该阶段完成证据见 `evidence/phase0-baseline.*`。

<a id="phase-1-registry-and-stage-signals"></a>

### Phase 1：Registry 与选择器

- 定义并校验 `path_globs -> rule_id -> gate` 的机器可读结构；
- 为 lint、单测、PR ready、stage gate 和安全检查建立最小规则；
- 增加重复 ID、失效路径、无约束命令、过期例外和 unmapped 的负例；
- 用冻结 PR 样本回放选择器，报告误选、漏选和未映射路径；
- 不把 Harness 场景、评分或 `PHASE_TESTS` 复制到 Registry。

### Phase 2：Shadow

新选择器和聚合器先 report-only，与现有 workflow 在相同 PR head SHA 上比较。比较项只包括选择结果、状态语义、失败归因和时长；完整评测内容仍归 Harness/日跑。观察窗口内不得改变旧 required checks。

### Phase 3：PR 快门禁

启用代表性环境加受影响 subset 的快速硬门禁；`CI / PR gate` 在所有输入完成后输出明确结论。完整 OS/Python 矩阵、跨仓和真实 LLM 继续作为 evidence-only。映射覆盖不足时阻塞并指向 Registry owner。

### Phase 4：Branch Protection 切换

在 Phase 2/3 的误报、漏报、取消和权限问题有证据关闭或有明确 owner 后，将 `CI / PR gate` 提升为唯一 required check，保留可逆观察窗口，再移除旧的单 job required checks。切换必须验证普通 PR、fork PR、重跑、并发取消和当前 head SHA 绑定。

### Phase 5：稳定化

按真实 PR 失败数据复盘规则覆盖、时长和未映射率；成熟的完整矩阵按独立发布策略逐项提升。任何提升都必须有 owner、时长目标、回滚方法和安全审查，不能把 CI Spec 重新扩展成 Harness Spec。

## 4. 失败与回滚

代码/配置错误、受影响检查失败、PR ready 失败、stage gate 失败、安全检查失败、聚合输入缺失和未处理的 mapping-incomplete 都阻止合并。完整评测或真实 LLM 的失败默认只生成 evidence。

发现聚合器误报、漏报、无法创建或显著超时后，暂停提升 required checks，恢复上一版 Branch Protection 名称，保留 artifact 和失败样本，修复选择器/聚合器后从 Shadow 重新观察。回滚不删除历史 evidence，也不修改方向 Spec 的阶段完成记录。

## 5. 验收清单

- 当前 diff 能追溯到选择的规则、命令和 head SHA；
- lint、受影响单测、`check_pr_ready.py`、适用 stage gate 和安全检查均可单独定位；
- 缺失输入和未映射路径 fail closed；
- `CI / PR gate` 稳定创建且是唯一合并聚合器；
- Harness 评测结果与 CI 合并结论分层展示；
- docs 变更执行 git-docs evaluation，并在断言仍有效时刷新 baseline。

## 6. 相关文档

- [CI 合并门禁 Spec](spec.md)
- [Harness 构建与统一契约 Spec](../harness/spec.md)
- [Phase 0 基线](evidence/phase0-baseline.md)
- [当前进度源](../../../progress.yaml)
- [PR 就绪审计脚本](../../../scripts/ci/check_pr_ready.py)
