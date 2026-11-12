# Expense H2 存储操作验证（2026-11-12）

本报告仅记录本轮限定的 H2，进度以 [路线图](../roadmap-spec.md) 为准。**本切片退出条件已通过**：SQLite/PostgreSQL 合同及实际 PostgreSQL 重启检查完成。H1 的历史验收保持原样，本报告使用独立证据；S6 仍为 in_progress，H3/H4 未实现。

## 范围

- `case_store.py` 集成 `case_operations.py`，同一 Claim engine/metadata 新增 work 状态与动作幂等表，保留 H1 case 创建快照与追加式事件；不 ALTER 既有 H1 表。
- 自认领只接受受信操作者本人，队列角色与成员关系同时满足；乐观版本和事务行锁防止双认领。释放/到期清锁，转派/升级有队列、原因、操作者、锁和版本审计。
- `sla.py` 按建单 SLA 快照计算原始截止时间，转派/配置变化不延长。响应违约与解决升级分别只记录一次，重复或并发扫描不重复写事件/outbox。没有定时调度器或通知发送器。
- 缺失路由/队列不可用保存 unrouted 与运营 pending 意图；所有操作均不写 Claim/审批。未接 HTTP、`route_review` 自动建单、H3 resolve、H4 发送或 UI。

身份和配置是可信调用方的输入，不是新身份系统或生产多租户权限。合成 Decision 用于存储合同，不是主 Workflow 已完成自动建单的证明。创建时无 SLA 的 unrouted case 首次成功路由仍从原创建时间计算；历史时间和审计不被重写。

§9.2 的“连续两次无人认领”尚缺轮次/重置时钟定义，不在本次固定截止时间切片中另建循环计时器。处理锁到期只解锁；不能以重复锁到期为理由自动转派、关闭或批准。

## 本地验证

```powershell
$env:REACT_AGENT_PERMISSIVE_TEST_DIRS='1'
.\.venv\Scripts\python.exe -m pytest tests/apps/expense/test_expense_case_operations.py tests/apps/expense/test_expense_case_store.py -q
.\.venv\Scripts\python.exe -m pytest tests/apps/expense tests/service/test_fastapi_expense_claims.py tests/service/test_fastapi_expense_reviews.py tests/storage -q --junitxml=artifacts/expense/smoke/h2/related-contracts.xml
.\.venv\Scripts\python.exe -m ruff check src/react_agent/apps/expense tests/apps/expense/test_expense_case_operations.py
```

SQLite 定向：**43 passed, 45 skipped**；其中 H2 23 passed / 23 PostgreSQL skipped，H1 20 passed / 21 PostgreSQL skipped / 1 SQLite TRUNCATE skipped。相关 Expense/Claim/审批 HTTP/storage 回归：**184 passed, 45 skipped**。Ruff 通过。Windows `.cache/pytest` 写权限与既有 Harness 弃用提示为警告，未更改基础设施。

按 validation-scope 选择本轮验证：H1 只覆盖建单与证据追加，无法证明新增处理锁的并发唯一赢家、版本冲突无副作用、转派后授权切换、到期/违约扫描并发幂等。因此新增 H2 合同复用 H1 的 SQLite/隔离 PostgreSQL fixture，并运行相关 Claim/审批回归确认没有业务写入。覆盖连接释放/新 adapter 恢复、重复动作重放、扫描中途事件写失败整笔回滚、旧 H1 行懒初始化、SLA 快照固定和自指升级路由进入 unrouted；不扩大到无关全仓测试。

## PostgreSQL 重试、合同与重启结果

此前多次 `docker ps -a` 因自动审批服务 **503 Service Unavailable** 未执行。2026-11-12 用户要求重试后审批恢复，已检查全部 11 个容器，核实 PostgreSQL/API/Redis 的 Compose project 为 `react-agent`、working_dir 为当前仓库、配置文件为 `docker-compose.yml`，项目网络为 `react-agent_default`，数据库卷为 `react-agent_react-agent-postgres-data`。复用现有 `react-agent-postgres-1`，未选择无关数据库、未新建容器或重建镜像。

数据库没有宿主机映射端口，因此在同项目现有 API 容器的 `/tmp/expense-h2-20261112` 运行当前源码与测试快照，复用 `/tmp/expense-h1-20261112/deps` 的隔离 pytest 依赖。未覆盖 `/app` 应用代码或修改全局依赖；未输出数据库连接凭据。实际命令：

```powershell
docker exec -w /tmp/expense-h2-20261112 -e PYTHONPATH=/tmp/expense-h2-20261112/src:/tmp/expense-h1-20261112/deps -e PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 react-agent-docs-troubleshoot-1 python -c 'import os,pytest; os.environ["REACT_AGENT_TEST_POSTGRES_URL"]=os.environ["REACT_AGENT_DATABASE_URL"];raise SystemExit(pytest.main(["tests/apps/expense/test_expense_case_operations.py","tests/apps/expense/test_expense_case_store.py","-q","--junitxml=/tmp/expense-h2-20261112/contracts.xml"]))'
```

结果：**87 passed, 1 skipped in 14.02s**。H2 的 SQLite/PostgreSQL 各 23 项全部通过；H1 PostgreSQL 21 项及 SQLite 20 项通过，唯一跳过是 SQLite TRUNCATE。报告保存为本地 `artifacts/expense/smoke/h2/postgres-contracts.xml`。PostgreSQL 每案使用随机隔离 schema，结束只删除该 schema，不禁用事件触发器或改正式历史。

实际重启使用本地验收脚本 `artifacts/expense/smoke/h2/verify_restart.py`（生成物，不提交），复制到同一临时目录后分别执行 prepare/finish。prepare 在独立 `expense_h2_smoke_<uuid>` schema 保存两个合成 case：有效认领锁和已扫描升级的超期工单；记录 case、事件、outbox、Claim/审批与数据库启动时间。finish 必须验证 `pg_postmaster_start_time()` 已变化后才执行恢复断言：

```powershell
docker exec -w /tmp/expense-h2-20261112 -e PYTHONPATH=/tmp/expense-h2-20261112/src:/tmp/expense-h1-20261112/deps react-agent-docs-troubleshoot-1 python verify_restart.py prepare
docker restart react-agent-postgres-1
docker exec react-agent-postgres-1 pg_isready -U learn -d learn
docker exec -w /tmp/expense-h2-20261112 -e PYTHONPATH=/tmp/expense-h2-20261112/src:/tmp/expense-h1-20261112/deps react-agent-docs-troubleshoot-1 python verify_restart.py finish
```

结果：`ok=true, restart_verified=true, locks_restored=true, action_replay=true, scan_idempotent=true, expiry_only_unlocks=true, claim_approval_unchanged=true`。实际重启后锁/截止时间/违约标记和事件恢复；旧认领动作重放返回原结果；重复扫描无变更；模拟处理锁到期仅解锁，Claim/审批及其审计始终不变。

状态快照保存为本地 `artifacts/expense/smoke/h2/restart-state.json`，不含连接凭据。隔离 schema `expense_h2_smoke_4d678b3373f147a68d7bae0016604ae9` 已清理，最终查询本轮测试/重启 schema 遗留数为 **0**。为验收启动的 API、项目 Redis、项目 PostgreSQL 均恢复原先停止状态；原有 `learn-redis` 仍运行，未操作其他容器。

文档评测 **5/5 PASS**，corpus clean、无受影响断言；本轮修改在 `docs/specs`，按已有配置排除于检索语料。已按要求执行 `run_git_docs_eval.py --refresh-baseline`，刷新 98 文件 baseline，仅生成时间变化；`check_pr_ready.py` **PR READY: PASS**，`git diff --check` 通过。这些文档检查与上述数据库验证分别记录，不替代 S6 全阶段验收。

生成报告位于本地 artifacts，不提交凭据或本地运行轨迹。本报告不将 H2 宣称为生产 SLA、真实通知或完整人工接管闭环。
