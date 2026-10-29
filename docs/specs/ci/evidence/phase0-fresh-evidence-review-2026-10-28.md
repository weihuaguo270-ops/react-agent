# CI Phase 0 当前证据核验（2026-10-28）

## 核验结论

**结论：Phase 0 Partial；fresh workflow 与保护规则已核验，逐样本基线和正式独立复审仍待完成。**

本记录核验当前主干 SHA、Branch Protection 和合并后 Actions 运行。它由本次实施上下文整理，不构成正式独立复审。正式复审应由未参与本次证据整理的审查者检查逐样本数据、Registry v2 设计契约、迁移边界和 Phase 1 验收矩阵；Phase 1 的 validator/backtest 实现、Phase 2 的 shadow 和 R9 执行验收不应提前当成 Phase 0 实现要求。

## 当前主干证据

核验时间为 2026-10-28，远端只读 API 返回：

| 项目 | 当前证据 |
|---|---|
| `main` | `b78e18d24d7b92ddbeb2076810dc625af1da5673`，2026-10-27 的 daily-smoke variance 提交 |
| PR #173 合并 | `8446201e6495c7a302a80347bcaa0c8e7bf613fd` |
| 合并后 CI push | run `40104979097`，head `8446201`，success |
| 合并后 Harness push | run `40104979076`，head `8446201`，success |
| 合并后 Evaluation push | run `40104979077`，head `8446201`，success |
| 最新 Daily smoke | run `40458769216`，success；之后机器人提交 `b78e18d` |

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

1. `phase0-baseline.json` 的历史样本冻结在 `97c73014`，采集日期为 2026-10-22。它是历史样本，不是当前主干 fresh baseline。
2. `docs/specs/registry.yaml` 仍是 `spec-registry/v1`，没有 CI 方向 path rules；`registry-v2.schema.json` 只是结构契约，不是已落地的 v2 registry 或 validator。
3. 尚无冻结 PR 样本上的 selector backtest，无法报告 mapped coverage、unmapped paths、false positives 或 missed expected rules；这是 Phase 1 的实现/验收产物，不是 Phase 0 的完成门槛。
4. 尚无稳定的 `CI / PR readiness` 与 `CI / PR gate` 聚合 job；Branch Protection 仍直接要求多个独立 job。这是 Phase 4 迁移目标，不是 Phase 0 的完成门槛。
5. `daily-smoke` 具有写权限并能创建 PR/推动合并，仍需在后续阶段执行 R9 安全审计并与观察性 smoke 职责分离。
6. 当前逐样本数据尚未按最新 main 刷新，且正式独立复审未完成，因此 Phase 0 保持 Partial，Phase 1 尚未启动。

## 正式独立复审前置项

1. 重新生成 `phase0-baseline.json` 和 `phase0-sample-index.md`，把最新 100 PR、100 个 CI runs、50 个 daily-smoke runs、当前 `main` SHA、PR #172/#173 及合并后 push runs 纳入明确的样本范围。
2. 对每条失败/取消样本保留 job/step 分类依据，不能以当前成功运行覆盖历史失败证据。
3. 将 `registry-v2.schema.json`、CI/Harness/Evaluation 职责边界、Phase 1 验收矩阵及 R9 审计计划作为设计契约提交独立复核；validator、selector backtest 与安全执行测试留待对应阶段实施。

## 复现入口

```powershell
gh api repos/weihuaguo270-ops/react-agent/commits/main
gh run list --branch main --limit 30 --json databaseId,workflowName,event,status,conclusion,headSha,createdAt,updatedAt,url
gh api repos/weihuaguo270-ops/react-agent/branches/main/protection
```
