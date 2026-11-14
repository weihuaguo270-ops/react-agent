# S8 第四刀：最终汇总（原型验收 complete）

日期：2026-11-14。权威进度见 [Expense 路线图](../roadmap-spec.md)。本切片**不再重跑**评测，只把前三刀本阶段复跑证据收成最终汇总。

判定：**S8 = complete（原型验收完成）**；**`release_ready=false`（不是可以发布到生产）**。

本地摘要（忽略、不提交凭据）：`artifacts/expense/smoke/s8-final/summary.json`。

## 裁决口径

| 判定 | 含义 |
|---|---|
| S8 complete | 本阶段必需项均有可追溯复跑证据；跳过项仍记为跳过 |
| 不是生产可发布 | 无生产身份、真实渠道、付款/入账、生产 SLA；JEV 未评估 |
| 对外表述 | 可部署工程原型；关工单或本地通知成功 **不等于** 批准报销 |

## 前三刀证据索引（本刀不重跑）

| 刀 | 证据 | 本阶段复跑要点 |
|---|---|---|
| 1 | [s8-acceptance-aggregate.md](s8-acceptance-aggregate.md) | 单测 215p；Expense HTTP 24p；浏览器 UI 14p；仓库回归 1577p；`/health` `/ready` `/v1/info`；S1 八案 8/8 兼容 |
| 2 | [s8-candidate-eval.md](s8-candidate-eval.md) | 扩展 candidate：dev 41/41、golden 12/12、held_out 16/16；held_out 哈希仍为已审查值；exit 0、无 `known_gap` |
| 3 | [s8-postgres-restart.md](s8-postgres-restart.md) | 现有项目容器 Claim/case 物理重启均 `ok`；case `restart_verified=true`；隔离 schema 清零 |

批次身份（各自报告为准，本刀不改写）：

| 刀 | batch / commit（报告记载） |
|---|---|
| 1 | `s8-acceptance-2026-11-14` @ `6ac487e` |
| 2 | `s8-candidate-2026-11-14` @ `4a7ccba` |
| 3 | `s8-postgres-restart-2026-11-14` @ `f3324f2` |
| 4（本汇总） | `s8-final-2026-11-14` @ `db32067`（汇总起点；不重跑） |

## 必需项核对

| 必需项 | 状态 | 证据 |
|---|---|---|
| Expense 单测 | 本阶段已复跑通过 | 第一刀 |
| Expense HTTP（Claim / review / case） | 本阶段已复跑通过 | 第一刀 |
| 浏览器 UI smoke（申请人 + 运营台） | 本阶段已复跑通过 | 第一刀 |
| 仓库 CI 等价回归 | 本阶段已复跑通过 | 第一刀 |
| `/health` `/ready` `/v1/info` | 本阶段已复跑通过 | 第一刀 |
| S1 八案逐案兼容 | 本阶段已复跑通过 | 第一刀 |
| 扩展 candidate `dev` | 本阶段已复跑通过 | 第二刀 |
| 扩展 candidate `golden` | 本阶段已复跑通过 | 第二刀 |
| 扩展 candidate `held_out`（独立、不调参） | 本阶段已复跑通过；哈希匹配 | 第二刀 |
| PostgreSQL Claim 物理重启 | 本阶段已复跑通过 | 第三刀 |
| PostgreSQL case 物理重启 | 本阶段已复跑通过 | 第三刀 |

说明：第一刀单独结果曾为 `hold`，是因为当时扩展 candidate 与物理重启尚未复跑；第二、三刀补齐后，本最终汇总将必需项记为齐备。不以 S3 历史 41/12/16 或仅 S1 八案代替第二刀结果。

## 跳过项（仍为跳过，未解冻）

| 项 | 状态 | 说明 |
|---|---|---|
| JEV 类可选模型（Decision P5） | **跳过** | 本阶段不评估；S8 complete 不要求完成可选模型 |
| 真实邮件 / IM | **跳过 / 冻结** | 本地通知 accepted ≠ 真实送达或已批准 |
| 后台常驻调度 | **跳过 / 冻结** | |
| 交付线 | **跳过 / 冻结** | |
| Go 重写 | **跳过 / 冻结** | |
| `react_loop` 变更 | **跳过 / 冻结** | |
| 生产身份 / 付款入账 / 生产 SLA | **未接入** | 不得从本验收推断 |

## 与「发布」的边界

- **允许说**：Expense 场景完成 S0–S8 原型验收；规则、审批、审计、人工作业、HTTP/UI 与重启恢复有本阶段复跑证据。
- **禁止说**：可以发布到生产、生产财务系统已接通、已付款/已入账、生产 SLA、多租户合规平台。
- held_out / golden 仅作冻结验收附录，不作为对外主叙事。

## validation-scope

S8 第四刀的风险是「缺最终汇总时把单刀 hold 或历史通过误写成可发布，或把可选 JEV 当成 complete 阻塞」。本刀只做证据收口与状态裁决，不重跑、不改用例、不评估 JEV、不解冻渠道与交付线。

## 结论

必需项均有本阶段复跑证据；跳过项仍记为跳过。**S8 标为 complete（原型验收完成）**；**不是可以发布到生产**（`release_ready=false`）。JEV、真实邮件/IM、常驻调度、交付线、Go 与 `react_loop` 继续冻结。关工单或本地通知成功仍不等于批准报销。
