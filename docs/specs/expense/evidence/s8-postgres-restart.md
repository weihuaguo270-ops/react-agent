# S8 第三刀：PostgreSQL 物理重启 smoke 复跑

日期：2026-11-14。权威进度见 [Expense 路线图](../roadmap-spec.md)。本切片只复跑既有 Claim / case 物理重启 smoke，**不把 S8 标为 complete**，也**不宣称可以发布**。

本地报告目录（忽略、不提交凭据）：`artifacts/expense/smoke/s8-postgres-restart/`，入口摘要为 `summary.json`（`result=hold`，`release_ready=false`，`s8_status=in_progress`）。报告与状态文件**不含**数据库连接串或凭据。

## 范围

已执行：

- Claim：`scripts/eval/smoke/run_expense_postgres_restart_smoke.py`（`prepare` → 外部重启已核实项目容器 → `finish`）
- Case：`scripts/eval/smoke/run_expense_case_postgres_restart_smoke.py`（同上；脚本本身不重启容器；隔离 `expense_h1_smoke_<uuid>` schema）

明确未执行 / 继续冻结：

- JEV 类可选模型评估
- 真实邮件 / IM、后台常驻调度
- 交付线、Go 重写、`react_loop` 变更
- 把本刀通过写成 S8 complete 或可发布

## 容器边界

| 项 | 值 |
|---|---|
| 批次 | `s8-postgres-restart-2026-11-14` |
| commit | `f3324f24d594be1339ef3a3ef81b41e8cd5c2f22` |
| 复用容器 | `react-agent-postgres-1`（Compose project=`react-agent`，service=`postgres`，卷=`react-agent_react-agent-postgres-data`，working_dir=本仓库） |
| 临时配套 | 仅为执行启动既有 `react-agent-redis-1`、`react-agent-docs-troubleshoot-1`；**未新建容器** |
| 原状态 | 上述三者均为 `exited`；`learn-redis` 保持 `running` 未操作 |
| 结束后 | 项目 postgres/redis/API 恢复 `exited`；`learn-redis` 仍为 `running` |
| 隔离 schema 残留 | `expense_h1_smoke_*` 数量 **0** |

## 复跑命令与结果

在已核实的项目 API 容器内挂载本 HEAD 的 `src`/`scripts`/`fixtures` 到临时目录后执行（URL 仅来自容器环境变量，不写入状态或本报告）：

```powershell
# Claim
python scripts/eval/smoke/run_expense_postgres_restart_smoke.py --phase prepare
docker restart react-agent-postgres-1
docker exec react-agent-postgres-1 pg_isready -U learn -d learn
python scripts/eval/smoke/run_expense_postgres_restart_smoke.py --phase finish --state-json <claim-state>

# Case（同一份 state-file；脚本不重启容器）
python scripts/eval/smoke/run_expense_case_postgres_restart_smoke.py --phase prepare --state-file case-state.json
docker restart react-agent-postgres-1
docker exec react-agent-postgres-1 pg_isready -U learn -d learn
python scripts/eval/smoke/run_expense_case_postgres_restart_smoke.py --phase finish --state-file case-state.json
```

| smoke | 结果 | 关键断言 |
|---|---|---|
| Claim | `ok=true`，`status=approved`，事件 `claim_created`→`claim_updated`→`claim_submitted`→`review_routed`→`review_resolved`；合成行已清理 | `pg_postmaster_start_time` 在 prepare 与 finish 之间已变化 |
| Case | `ok=true`，`restart_verified=true`，`events=2`，`outbox_pending=1`；schema `expense_h1_smoke_cd85cf1f93fa48ce9ecb82debe53841b` 已删除 | finish 断言 postmaster 启动时间相对 prepare 已变化；case/events/outbox 恢复、去重、越权 `case_not_found`、事件不可改、Claim/审批快照不变 |

Claim `claim_id`：`clm_a6d8399a9b4f48a5b86a20110dc420e6`。Case `case_id`：`case_7aeea7439e13419087e3af5eaed32465`。二者均为合成验收数据，不代表生产 SLA。

## 与其他证据的边界

| 证据 | 关系 |
|---|---|
| [S8 第一刀 smoke 汇总](s8-acceptance-aggregate.md) | 本刀不重跑；第一刀未做物理重启 |
| [S8 第二刀 candidate](s8-candidate-eval.md) | 规则评测，不代替本刀数据库重启 |
| H1–H4 历史重启证据 | 仅索引；**不得**用历史通过代替本 HEAD 复跑 |

## 仍未满足的发布门槛（如实）

1. 即使 Claim / case 物理重启均过，S8 退出标准还要求发布级汇总门禁闭合；第一刀仍为 `hold`，JEV 未评估。
2. **S8 保持 `in_progress`，不可发布**。
3. 生产身份系统、真实邮件/IM、付款/入账回写、生产 SLA 均未接入。
4. 关工单或本地通知成功仍不等于批准报销；对外只能表述为可部署工程原型。

## validation-scope

S8 第三刀的风险是「引用 S4–S6 历史重启通过，冒充当前 HEAD 的物理恢复证据」。既有 Claim/case 重启脚本已覆盖隔离 schema 与 postmaster 变化断言，因此只复跑并新增本批次证据；不新建容器、不改脚本行为、不扩展为全仓测试、不评估 JEV。

## 结论

本刀 Claim 与 case PostgreSQL 物理重启 smoke 均在现有项目容器上复跑通过，`summary.json` 仍判定 **`hold`**：S8 **in_progress**，**不可发布**。JEV、真实通知、常驻调度、交付线、Go 与 `react_loop` 继续冻结。
