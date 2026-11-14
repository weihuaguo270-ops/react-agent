# S8 第一刀：分阶段 smoke 汇总验收报告

日期：2026-11-14。权威进度见 [Expense 路线图](../roadmap-spec.md)。本切片只汇总并复跑可执行的既有 smoke，**不把 S8 标为 complete**，也**不宣称可以发布**。

本地报告目录（忽略、不提交凭据）：`artifacts/expense/smoke/s8-acceptance/`，入口摘要为 `summary.json`（`result=hold`，`release_ready=false`）。

## 范围

已执行：

- Expense 单测（`tests/apps/expense`）
- Expense HTTP（Claim / review / case）
- opt-in 浏览器 UI smoke（申请人表单 + 运营台）
- 仓库 CI 等价回归（显式 `-m "not real_llm"`）
- FastAPI 探针 `/health`、`/ready`、`/v1/info`（含未授权 401）
- 与 S1 冻结 8 案逐案兼容对比（`fixtures/expense/business_cases.json`）

明确未执行（本刀冻结）：

- 扩展 candidate 的 golden / held_out 发布门槛评测
- JEV 类可选专项模型评估
- PostgreSQL 物理重启 smoke 复跑
- 真实邮件 / IM、后台常驻调度
- 交付线、Go 重写、`react_loop` 变更

## 批次身份

| 字段 | 值 |
|---|---|
| batch | `s8-acceptance-2026-11-14` |
| commit | `6ac487e6ad304d205490cb0755d45ee51b994c0c` |
| `business_cases.json` SHA-256 | `092e54d453ad07e21943a789ffd86cf8730d66a7857d82bfea1cb215cf06d793`（与 [S1 baseline](s1-baseline-20261012.md) 相同） |
| `expense_policy_v2.json` SHA-256 | `7f51e378f09da333a90c7f26261be12de1e09a6a6cee3021024a687d4518cee2`（相对 S1 捕获时的政策文件已演进；8 案期望决策仍匹配） |
| `handoff_routing_v1.json` SHA-256 | `ddeef5c45f453d4b8357980a9f8547bccbb8967e7435b5dc068e115e54a80d33` |

## 复跑命令与结果

```powershell
$out = "artifacts/expense/smoke/s8-acceptance"
$py = ".\.venv\Scripts\python.exe"

# 单测
& $py -m pytest tests/apps/expense -q -m "not real_llm" --junitxml="$out/expense-unit-junit.xml"
# -> 215 passed, 90 skipped

# Expense HTTP
& $py -m pytest tests/service/test_fastapi_expense_claims.py `
  tests/service/test_fastapi_expense_reviews.py `
  tests/service/test_fastapi_expense_cases.py -q -m "not real_llm" `
  --junitxml="$out/expense-http-junit.xml"
# -> 24 passed, 20 skipped（未配置 REACT_AGENT_TEST_POSTGRES_URL；skip 不作通过证据）

# 浏览器 UI smoke
$env:REACT_AGENT_BROWSER_SMOKE = "1"
& $py -m pytest tests/browser/test_expense_form_ui.py tests/browser/test_expense_ops_ui.py -q -m "not real_llm" `
  --junitxml="$out/browser-ui-junit.xml"
# -> 14 passed

# S1 八案兼容（legacy fixture；不是扩展 candidate held_out/golden 发布门槛）
& $py scripts/eval/acceptance/run_expense_business_eval.py `
  --agent-version expense-s8-s1-compat-20261114 `
  --report-out "$out/s1-compat-report.json" `
  --episodes-out "$out/s1-compat-episodes"
# -> 8/8 pass_rate=1.0

# 仓库 CI 等价回归
Remove-Item Env:REACT_AGENT_BROWSER_SMOKE -ErrorAction SilentlyContinue
& $py -m pytest tests/ -q `
  --ignore=tests/test_real_llm.py `
  --ignore=tests/test_harness_closed_loop_decision.py `
  --ignore=tests/evaluation/test_harness_closed_loop_decision.py `
  -m "not real_llm" --cov=react_agent --cov-report=term-missing --cov-fail-under=35 `
  --junitxml="$out/ci-local-junit.xml"
# -> 1577 passed, 124 skipped, 9 deselected；覆盖率 76.55%
```

`/health`、`/ready`、`/v1/info` 在本机临时 FastAPI（Bearer 开启）上实测：健康/就绪 200；`/v1/info` 鉴权后 200，无凭据 401。原始响应见 `health-ready-info.json`。

## 分阶段历史 smoke 索引（本刀不重写）

| 阶段 | 历史证据 | 本刀关系 |
|---|---|---|
| S1 | [s1-baseline-20261012.md](s1-baseline-20261012.md) | 复跑同一 8 案 fixture 并核对决策码；fixture hash 未变 |
| S3 | 路线图记载的 Workflow smoke / candidate 报告目录 | 单测套件内含 `test_expense_workflow_smoke.py`，随 Expense 单测复跑 |
| S4–S5 | PostgreSQL 重启 smoke 与 SQL/HTTP lifecycle | HTTP SQLite 路径复跑；物理重启未在本刀复跑 |
| S6 | [s6-http-handoff.md](s6-http-handoff.md) | case HTTP 合同复跑 |
| S7 | [s7-claim-form.md](s7-claim-form.md)、[s7-ops-views.md](s7-ops-views.md) | 浏览器 smoke 14 项复跑 |

## S1 逐案对比

`business_cases.json` 哈希与 S1 baseline 一致。当前 Workflow 参考执行器对 8 案全部通过：

| case_id | split | 期望决策 | 本刀结果 |
|---|---|---|---|
| expense_dev_meal_manager | dev | approve_manager | pass |
| expense_dev_missing_receipt | dev | reject_no_receipt | pass |
| expense_golden_meal_limit | golden | reject_over_limit | pass |
| expense_golden_transport_finance | golden | approve_finance | pass |
| expense_golden_lodging_director | golden | approve_director | pass |
| expense_heldout_boundary | held_out | approve_manager | pass |
| expense_heldout_preapproved_over_limit | held_out | approve_finance | pass |
| expense_heldout_purchase_no_receipt | held_out | reject_no_receipt | pass |

说明：表中 `golden` / `held_out` 是 **S1 八案 fixture 内部 split 标签**，用于兼容对比；**不等于** 扩展 candidate 的 golden/held_out 发布门槛，后者本刀未执行。

## 仍未满足的发布门槛（如实）

1. S8 退出标准要求 held_out 独立、不调参，且 HTTP/UI 与分阶段 smoke 全部纳入发布 gate；本刀汇总结果为 `hold`，**S8 保持 in_progress**。
2. 扩展 candidate golden / held_out 验收未跑，不得用本刀通过率替代。
3. PostgreSQL 物理重启 smoke 未在本批次复跑；S4–S6 历史证据只作引用，不作本刀新证据。
4. 生产身份系统、真实邮件/IM、付款/入账回写、生产 SLA 均未接入。
5. Form P4 / Decision P5 的可选模型对比未开始；JEV 类模型禁止在本刀评估。
6. 关工单或本地通知成功仍不等于批准报销；对外只能表述为可部署工程原型。

## validation-scope

S8 第一刀的风险是「缺少可追溯的汇总批次，容易把历史阶段通过误写成可发布」。既有分阶段证据目录分散且不含当前 HEAD 复跑摘要，因此新增独立报告目录与本证据文件；不新增发布 gate、不扩展评测集、不把 browser opt-in 拉进默认 CI。

## 结论

本刀 scoped 检查全部通过并留下可追溯 artifacts，但 **`summary.json` 判定为 `hold`**：S8 **in_progress**，**不可发布**。下一刀需单独处理 held_out/golden 发布门槛与其余未满足项；真实通知、常驻调度、交付线、Go 与 `react_loop` 继续冻结。
