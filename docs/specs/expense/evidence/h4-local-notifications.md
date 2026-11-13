# 限定 H4：本地通知重试与审计指标

日期：2026-11-13。进度以 [路线图](../roadmap-spec.md) 为准；契约见 [人工接管规格 H4](../human-handoff-spec.md#h4通知与运营视图)。本切片退出条件已通过，S6 仍为 in_progress。HTTP、route_review 自动建单、真实邮件/IM、后台调度和 S7 UI 未接入；不是生产通知或 SLA 保障。

## 实现与边界

- `notifications.py`：OutboxWorker.run_once 有界领取、持久化租约、失效恢复、默认 5–3600 秒指数退避；NotificationAdapter / DeliveryResult；LocalNotificationAdapter 使用同库本地回执去重。原始 pending 意图保留，新增 delivery/receipt 两张附加表可用于现有 H1–H3 schema，不改审批库或既有状态约束。
- 领取和结果各自事务，adapter 调用不持锁。租约 token 拒绝迟到确认，worker 崩溃后以稳定 outbox_id 至少一次重试；本地 adapter 复用 delivery_id。结果/通知审计原子写入，失败保留 retry_wait，不丢业务事件。SQL 状态与外部系统没有分布式恰好一次承诺。
- 新动作补齐 case_assigned、needs_applicant、case_resolved 意图，并覆盖原有 case_created、SLA warning/breach。旧类型映射继续兼容；unrouted、转派/升级运营意图保留。收件目标取来源动作，而非投递时的当前认领人。历史缺失意图不回填旧审计。
- `case_metrics.py`：单 SQL 快照导出两类审计，rebuild_metrics 只读导出事件；不依赖当前 case/work/审批行。队列按最新业务事件归属，待处理数包括 needs_applicant / unrouted。SLA 指标只记录已扫描违约，按工单与违约类型去重；不预测未扫描超时。
- 人工接管率 = 有 case_created 的 distinct Claim/version ÷ 有 claim_submitted 的 distinct Claim/version，范围为完整导出历史。多个 reason 工单不重复计分子；旧建单审计缺 Claim 关联、或缺提交证据返回 unavailable，不猜测。不是 Agent 成功率或生产业务通过率。
- 仅可信 finance_admin 可运行 worker 或全局导出；CaseActor 仍是原型身份上下文。所有 adapter 仅允许可信本地实现；外部网络渠道需后续独立权限/网络控制。本地 accepted 表示 adapter 接受，user_read=false，不写“已通知审批人”。

## 验证

现有 H1–H3 合同不覆盖投递租约、崩溃重复调用、adapter 失败和离线审计投影；按 validation-scope 增加同库 H4 合同并复用已有双数据库 fixture。既有权限/审批回归验证通知写入不会绕过或改变 H3 原子审批。跨存储与业务动作边界触发仓库离线 CI 等价回归，无新增发布 gate 或评测集。

- 容器内 H1–H4 SQLite/PostgreSQL 合同：176 passed、1 skipped（SQLite 不支持 TRUNCATE）。最终 H4 合同（追加旧 schema 兼容验证后）：29 passed。
- 覆盖失败后重开 Store、退避上限、并发唯一租约、adapter 接受后崩溃、过期确认拒绝、重复调用回执复用、结果写入失败的事务回滚、异常脱敏、越权拒绝、来源收件目标、等待工单不恢复、已批准 Claim 不变、审计重复/乱序去重与旧证据 unavailable。
- Ruff 全 src/tests 通过；CI 同参 mypy 通过（154 个源文件）。
- 仓库 offline CI 同等测试命令（排除真实 LLM 与两份在线闭环文件）：1563 passed、89 skipped。随后仅新增 H3 schema 升级兼容测试，最终双数据库 H4 合同已包含该测试并通过；没有为这项测试重复整仓运行。

可复现合同入口：

```powershell
./.venv/Scripts/python.exe -m pytest tests/apps/expense/test_expense_notifications.py tests/apps/expense/test_expense_case_store.py tests/apps/expense/test_expense_case_operations.py tests/apps/expense/test_expense_case_resolution.py -q
```

PostgreSQL 测试通过环境变量 REACT_AGENT_TEST_POSTGRES_URL 选择实际数据库，fixture 使用随机 schema 并清理。未配置时相应合同 skip，不代表 PostgreSQL 通过。生成 XML/日志保存在本地 artifacts/expense/smoke/h4，不提交数据库/审批凭据或轨迹。

## 实际 PostgreSQL 重启

先检查全部 11 个 Docker 容器及 Compose 归属，仅复用 D:/agent_learning_projects/react-agent 所属 react-agent-postgres-1、已有数据卷与 API 运行环境；未新建容器、未选择 learn 系列数据库。为验证临时启动项目 PostgreSQL/Redis/API。

本地验收脚本 artifacts/expense/smoke/h4/verify_restart.py 的 prepare 在随机 expense_h4_smoke_<uuid> schema 创建合成 case：一个合法审批后的 approved Claim，三条失败待重试通知；另一个在本地 adapter 接受后、worker 未确认时中断。保存业务快照、审计、指标、投递状态与 pg_postmaster_start_time，不打印数据库 URL。

实际执行 docker restart react-agent-postgres-1 后，finish 确认数据库启动时间变化，核对所有快照恢复，再消费三条 retry 和一个过期租约；崩溃记录复用原 delivery_id，重复 run_once 无新投递，四条结果均为本地 accepted / user_read=false。Claim、审批及工单业务状态不变；指标可从导出审计重建且不受通知审计影响。结果：restart_verified=true、local_accepted=4、approved_claim_unchanged=true、metrics_rebuilt=true、schema_cleaned=true。

验证后，三个临时启动的项目容器均已恢复原先停止状态，未改动 learn-redis 等无关容器。git-docs 评测 5/5，通过后按仓库规则刷新语料 baseline；docs/specs 被既有语料配置排除，当前查询断言和语料文件 hash 不变，只刷新 baseline 时间。

关闭工单仍不等于批准报销；本地通知回执也不等于已批准、已读或真实送达。交付线、Go 重写、react_loop 和 S7 UI 继续冻结。
