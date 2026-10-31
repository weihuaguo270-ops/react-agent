# CI Phase 0 当前证据核验（2026-10-30）

## 核验结论

**结论：Phase 0 Partial；fresh 逐样本基线已生成，正式独立复审仍待完成。**

本记录核验当前主干 SHA、Branch Protection、逐样本 API 快照和 PR #172/#173 合并后 runs。它由本次实施上下文整理，不构成正式独立复审。正式复审应由未参与本次证据整理的审查者检查逐样本数据、Registry v2 设计契约、迁移边界和 Phase 1 验收矩阵；Phase 1 的 validator/backtest 实现、Phase 2 的 shadow 和 R9 执行验收不应提前当成 Phase 0 实现要求。

## 当前主干证据

当前基线已于 2026-10-30 在干净 checkout 刷新；本文件只记录当前证据边界，正式独立复审仍待未参与整理的审查者完成。

| 项目 | 当前证据 |
|---|---|
| `main` | `8805e5e9a875eb6584aa12d1ce79917ee7e73076` |
| PR #173 合并 | `8446201e6495c7a302a80347bcaa0c8e7bf613fd` |
| 合并后 CI/Harness/Evaluation push | runs `40104979097` / `40104979076` / `40104979077`，success |
| PR #172 合并 | `e9187069684797ef5dd6cab830cafd3332880a06`；Harness/Evaluation push runs `40101578011` / `40101578014`，success |
| 当前样本 | 100 PR、100 test.yml runs、50 daily-smoke runs |

这组证据证明 PR #173 修复了合并提交的自动 CI 触发。它不证明每次机器人提交都应触发同一套 CI，也不替代逐样本基线刷新。

## 当前 Branch Protection

`main` 的 required contexts 为：

- `lint`
- `test (3.10)`
- `test (3.11)`
- `test-windows (3.10)`
- `test-windows (3.11)`
- `typecheck`
- `security`
- `docker-smoke`
- `Harness P4 stage gate`

当前仍启用 strict、管理员保护和线性历史；`Real LLM gate` 已移除，`Evaluation evidence` 未设为 required。

## 未关闭事项

1. 历史样本 `97c73014` 和旧当前快照 `e641adc7` 已分别保存在 archive；它们不能替代当前主干 fresh baseline。
2. Registry v2 实例、语义 validator 和 selector backtest 已实现；100 个 PR 的 backtest 显示 1534 个 changed files 中 1017 个已映射、517 个未映射，覆盖率 66.30%，因此 selector 仍按契约 blocked。误选/漏选仍需独立 expected-rule 标注集。
4. 尚无稳定的 `CI / PR readiness` 与 `CI / PR gate` 聚合 job；Branch Protection 仍直接要求多个独立 job。这是 Phase 4 迁移目标，不是 Phase 0 的完成门槛。
5. `daily-smoke` 具有写权限并能创建 PR/推动合并，仍需在后续阶段执行 R9 安全审计并与观察性 smoke 职责分离。
6. 当前逐样本数据已按 `8805e5e` 刷新，但正式独立复审未完成，因此 Phase 0 保持 Partial；Phase 1 已启动但 R9 运行时验收仍 blocked。

## 正式独立复审前置项

1. 由独立审查者复核已重新生成的 `phase0-baseline.json` 和 `phase0-sample-index.md`，确认最新 100 PR、100 个 CI runs、50 个 daily-smoke runs、当前 `main` SHA、PR #172/#173 及合并后 runs 的样本范围。
2. 对每条失败/取消样本保留 job/step 分类依据，不能以当前成功运行覆盖历史失败证据。
3. 将 `registry-v2.schema.json`、CI/Harness/Evaluation 职责边界、Phase 1 验收矩阵及 R9 审计计划作为设计契约提交独立复核；validator、selector backtest 与安全执行测试留待对应阶段实施。

## 历史独立复审结果（2026-10-29，基于 e641adc7）

独立审查者在只读上下文中检查了旧基线、CI Spec、迁移计划和 Registry v2 schema，并通过 GitHub 只读 API 复核了当时的 `main` 与 Branch Protection。该结论只对 `e641adc7c95907a1bf55f7185c90faaa87b78829` 有效；旧原文已保存在 `archive/2026-10-29-e641adc7/`，不作为当前 `8805e5e` 的独立复审结论。

复审确认：历史 2026-10-22 SHA `97c73014` 的快照未被覆盖；当前 JSON、Markdown 和样本索引的 SHA、样本数量、失败统计和 required checks 一致；CI、Harness、Evaluation 职责边界清楚；Phase 1 Registry v2、Phase 2 shadow、Phase 3 PR gate 和 Phase 4 Branch Protection 切换未被误算为已完成。

**独立结论：Partial。** `fresh_rerun_required_for_completion` 仍为 true，Registry v2 mapping/backtest 尚未测量，R9 仍是静态 attention-required 快照，Phase 1 语义校验和安全执行验收尚未完成。因此当前不能把 CI Phase 0 标记为 Complete，也不应在此阶段修改 Branch Protection。

## 复现入口

```powershell
gh api repos/weihuaguo270-ops/react-agent/commits/main
gh run list --branch main --limit 30 --json databaseId,workflowName,event,status,conclusion,headSha,createdAt,updatedAt,url
gh api repos/weihuaguo270-ops/react-agent/branches/main/protection
```
