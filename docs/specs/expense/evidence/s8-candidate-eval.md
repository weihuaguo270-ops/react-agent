# S8 第二刀：扩展 candidate `dev` / `golden` / `held_out` 验收报告

日期：2026-11-14。权威进度见 [Expense 路线图](../roadmap-spec.md)。本切片只在当前 HEAD 复跑扩展 candidate 三组 split，核对 held_out 清单哈希，**不把 S8 标为 complete**，也**不宣称可以发布**。

本地报告目录（忽略、不提交凭据）：`artifacts/expense/smoke/s8-candidate/`，入口摘要为 `summary.json`（`result=hold`，`release_ready=false`，`s8_status=in_progress`）。

## 范围

已执行：

- `scripts/eval/acceptance/run_expense_candidate_eval.py --split dev`
- 同入口 `--split golden`
- 同入口 `--split held_out --allow-held-out`（冻结验收，不调参、不改用例、不改哈希）

明确未执行 / 继续冻结：

- PostgreSQL 物理重启 smoke（留待下一刀）
- JEV 类可选模型评估
- 真实邮件 / IM、后台常驻调度
- 交付线、Go 重写、`react_loop` 变更
- 把本刀通过率写成可发布，或用 S1 八案 / S3 历史 41/12/16 代替本批次结果

## 批次身份

| 字段 | 值 |
|---|---|
| batch | `s8-candidate-2026-11-14` |
| commit | `4a7ccba1b4e106c1ee25134732b27fedd401ca0f` |
| agent_version | `expense-s8-candidate-20261114` |
| fixture | `fixtures/expense/business_cases_expanded_v1.json` |
| fixture SHA-256 | `5f5dd9afea759009de37a41d078d6d008f3cf4a2fe93a49ee3155fcca77a5347` |
| held_out manifest SHA-256 | `f8801e86298c59260b8d510df9c965f953bcbc5430672fefdbb50b523457da36` |
| 已审查期望哈希 | `f8801e86298c59260b8d510df9c965f953bcbc5430672fefdbb50b523457da36`（与 [coverage-matrix-v1](coverage-matrix-v1.md) / `EXPECTED_HELD_OUT_MANIFEST_SHA256` 一致） |
| 哈希核对 | **匹配**（runner 未改哈希；本刀未改 fixture） |

## 复跑命令与结果

```powershell
$out = "artifacts/expense/smoke/s8-candidate"
$py = ".\.venv\Scripts\python.exe"
$ver = "expense-s8-candidate-20261114"

& $py scripts/eval/acceptance/run_expense_candidate_eval.py `
  --split dev --agent-version $ver `
  --report-out "$out/dev-report.json" --episodes-out "$out/dev-episodes"
# -> exit 0; 41/41; pass_rate=1.0; known_gap=0

& $py scripts/eval/acceptance/run_expense_candidate_eval.py `
  --split golden --agent-version $ver `
  --report-out "$out/golden-report.json" --episodes-out "$out/golden-episodes"
# -> exit 0; 12/12; pass_rate=1.0; known_gap=0

& $py scripts/eval/acceptance/run_expense_candidate_eval.py `
  --split held_out --allow-held-out --agent-version $ver `
  --report-out "$out/held_out-report.json" --episodes-out "$out/held_out-episodes"
# -> exit 0; 16/16; pass_rate=1.0; known_gap=0; held_out_manifest_sha256 匹配已审查值
```

| split | 本批次案数 | 通过 | pass_rate | exit | known_gap |
|---|---:|---:|---:|---:|---:|
| `dev` | 41 | 41 | 1.0 | 0 | 0 |
| `golden` | 12 | 12 | 1.0 | 0 | 0 |
| `held_out` | 16 | 16 | 1.0 | 0 | 0 |

说明：上表是 **当前 HEAD 本批次** 结果，不是 S2 的 39/41 known_gap 历史，也不是引用 S3 目录里的旧报告代替复跑。本刀 `dev` 无 `known_gap`、命令为零；若将来复现出现 `known_gap` 或非零退出，须如实记入报告，不得改写成全通过。

若干案带有既有 `resolved_gap` 注解（缺口已按规则关闭后的标记），例如 `D-PO-001`、`D-PO-004`、`H-TRANS-004`、`H-LODG-001`、`H-LODG-003`；它们计入 pass，**不是**未关闭的 `known_gap`。

## held_out 逐案（冻结验收）

| case_id | rule_id | status | known_gap | resolved_gap |
|---|---|---|---|---|
| H-MEAL-001 | meal.just_below_limit | passed | - | - |
| H-MEAL-002 | meal.just_above_limit | passed | - | - |
| H-MEAL-003 | meal.employee_weekend | passed | - | - |
| H-MEAL-004 | meal.entertainment_missing_participant | passed | - | - |
| H-TRANS-001 | transport.allowed_public_transit | passed | - | - |
| H-TRANS-002 | transport.flight_quote_boundary | passed | - | - |
| H-TRANS-003 | transport.flight_quote_just_over | passed | - | - |
| H-TRANS-004 | transport.category_limit_over | passed | - | yes |
| H-LODG-001 | lodging.standard_market_exact | passed | - | yes |
| H-LODG-002 | lodging.standard_market_over | passed | - | - |
| H-LODG-003 | lodging.preapproved_over_limit_within_market | passed | - | yes |
| H-LODG-004 | lodging.check_out_not_after_check_in | passed | - | - |
| H-PO-001 | purchase.exact_limit | passed | - | - |
| H-PO-002 | purchase.missing_po_precedes_decision | passed | - | - |
| H-CROSS-001 | currency.foreign_over_limit | passed | - | - |
| H-CROSS-002 | trip.critical_without_preapproval | passed | - | - |

完整 `dev` / `golden` 逐案与 episode 见本地 `artifacts/expense/smoke/s8-candidate/`（`.gitignore` 忽略）。

## 与其他证据的边界

| 证据 | 关系 |
|---|---|
| [S8 第一刀 smoke 汇总](s8-acceptance-aggregate.md) | 本刀不重跑；第一刀的 S1 八案兼容 **不能** 代替本刀扩展 candidate |
| S3 历史 `artifacts/expense/smoke/s3/` | 仅作历史索引；**不得**用其 41/12/16 代替本批次 |
| S1 八案 `business_cases.json` | 不同 fixture；本刀未跑、不计入 |

## 仍未满足的发布门槛（如实）

1. 即使本刀三组 split 全过，S8 退出标准还要求发布级 HTTP/UI 与分阶段 smoke 汇总门禁闭合；第一刀结果仍为 `hold`，PostgreSQL 物理重启未在本阶段复跑。
2. **S8 保持 `in_progress`，不可发布**；不得因 candidate 全过写成 complete / release-ready。
3. 生产身份系统、真实邮件/IM、付款/入账回写、生产 SLA 均未接入。
4. Form P4 / Decision P5 的可选模型对比未开始；JEV 类模型禁止在本刀评估。
5. 关工单或本地通知成功仍不等于批准报销；对外只能表述为可部署工程原型。

## validation-scope

S8 第二刀的风险是「用历史 candidate 通过率或 S1 八案冒充当前 HEAD 的扩展 golden/held_out 发布门槛」。既有 runner 与 held_out 哈希保护已覆盖执行与清单冻结，因此只复跑并新增本批次证据目录与本文件；不改用例、不改哈希、不新增发布 gate、不评估 JEV。

## 结论

本刀扩展 candidate：`dev` 41/41、`golden` 12/12、`held_out` 16/16，exit 均为 0，无 `known_gap`；held_out 清单哈希与已审查值一致。`summary.json` 仍判定 **`hold`**：S8 **in_progress**，**不可发布**。下一刀处理 PostgreSQL 物理重启等剩余门槛；真实通知、常驻调度、交付线、Go 与 `react_loop` 继续冻结。
