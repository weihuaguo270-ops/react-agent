# Expense H3 审批衔接验证（2026-11-12）

本记录只覆盖 H3 存储切片，进度以 [路线图](../roadmap-spec.md) 为准，契约以 [人工接管规格 H3](../human-handoff-spec.md#h3处理结果与审批衔接) 为准。H3 的绑定、重复/过期失败关闭退出条件已通过；S6 仍为 in_progress，HTTP/自动建单、H4 发送和 S7 UI 未接入。历史 H1/H2 证据保持原样。

## 实现与边界

- `ExpenseCaseStore` 增加 `start_case`、`request_applicant`、`resume_case`、`resolve_case`，复用 H1/H2 的表、事务、case 版本与追加式事件，不另建批准记录。
- resolve 必须绑定审批 ID（complete 可空）、Claim/version/hash、case 版本；财务处理角色、队列成员及本人有效处理锁同时满足。approve/reject 由原 `resolve_review` 权限入口通过连接适配器调用 S5 SQL 逻辑；Claim、原审批决议、case 绑定和审计原子提交。两种业务决议都以 case resolved 表示人工作业完成，由原审批写 Claim approved/rejected。
- complete 经 `case.resolve` 闸门，只关闭人工作业、不改 Claim/审批。重复 resolve（包括相同幂等键）、旧版本、错绑、已完成审批和失效处理锁均拒绝，不静默重开。丢失响应可用存储 `get/events` 核对结果，不能重放批准。
- async 下的 H3 CONFIRM 凭据精确绑定工具与请求参数，并限一次；工具级 session grant 不能批准 H3。过期、deny、已消费、session、错绑或通过旧审批调用复用 H3 凭据均失败关闭。一次性凭据消费补上批准后 expires_at 检查；其他旧调用保持原语义。
- 权限文件凭据与 SQL 不构成分布式事务：凭据已消费后 SQL 审计失败，全部业务写入回滚，但凭据保持已消费，必须重新人工批准。已有 HITL、显式 auto_allow/关闭闸门仍遵循原配置；数据库恢复 smoke 的 auto_allow 不作为人工授权证据。
- needs_applicant 清锁并等待；仅原申请人显式提交补充 evidence_ref、原版本/hash 和当前 case 版本才能重新 queued。冻结 SLA 不暂停/重算，原 Claim 核心字段/附件不变；内容变化需新版本重新路由。扫描、转派、认领和关单都不隐式恢复等待工单；恢复后仍需重新认领和开始处理，不执行 Workflow。

## 验证选择与本地结果

H1 覆盖创建/审计，H2 覆盖锁/SLA，S5 覆盖独立审批；它们不能证明跨 case 与 review 的同事务回滚、跨入口并发、绑定凭据或补料恢复。按 validation-scope 复用已有两数据库 fixture，新增 H3 31 项合同，并运行受影响的 Expense、HTTP 审批、storage 和权限回归。共享权限闸门变化另触发仓库离线 CI 等价检查，结果为 **1549 passed, 76 skipped**（310.48 秒），保存于本地 `offline-ci.xml`。最后补充 session 凭据不授予旧入口工具级授权后，重跑相关权限及 H3 合同；不以单元合同代替全仓结论。

```powershell
$env:REACT_AGENT_PERMISSIVE_TEST_DIRS='1'
.\.venv\Scripts\python.exe -m pytest tests/apps/expense tests/service/test_fastapi_expense_claims.py tests/service/test_fastapi_expense_reviews.py tests/storage tests/service/test_async_approvals.py tests/service/test_fastapi_async_approvals.py tests/safety/test_permissions_gate.py -q --junitxml=artifacts/expense/smoke/h3/related-contracts.xml
.\.venv\Scripts\python.exe -m ruff check src/ tests/
```

结果：**259 passed, 76 skipped**；其中 75 项 PostgreSQL 未在宿主机配置，1 项是 SQLite 不支持 TRUNCATE。Ruff 通过。既有 Harness 弃用提示和 Windows pytest cache 写权限提示为警告。

覆盖合法批准/拒绝、可空或既有绑定、缺失/错误/已决审批、非批准角色、非本人/失效锁、未开始/等待状态、Claim/Decision/case 版本替换、重复关闭、case 审计故障整笔回滚、直接 S5 与 H3 的并发唯一审批、CONFIRM 绑定/过期/拒绝/重用、SQL 失败不恢复凭据、显式补料重放/越权/旧版本以及不可用队列进入 unrouted。

跨入口并发测试发现并修复 SQLite 延迟事务使双方读取 pending 的缺口：独立 S5 resolve 也使用 BEGIN IMMEDIATE。PostgreSQL 独立 S5 和 H3 统一 Claim→case→review 锁顺序，不以 SQLite 通过替代 PostgreSQL 并发证据。

## PostgreSQL 合同与实际重启

已读取全部 **11** 个容器清单并核对 Compose 标签、网络和卷。仅临时启动现有 `react-agent-postgres-1`、`react-agent-redis-1`、`react-agent-docs-troubleshoot-1`，项目 working_dir 为当前仓库，数据库卷为 `react-agent_react-agent-postgres-data`。没有新建容器、重建镜像或操作其他数据库。

在现有 API 容器 `/tmp/expense-h3-20261112` 使用源码/测试快照，复用 H1 隔离 pytest 依赖；不覆盖 `/app` 或安装全局依赖，不输出数据库 URL。PostgreSQL 测试逐案使用随机 schema 并清理。

```powershell
docker exec -w /tmp/expense-h3-20261112 -e PYTHONPATH=/tmp/expense-h3-20261112/src:/tmp/expense-h1-20261112/deps -e PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 react-agent-docs-troubleshoot-1 python -c 'import os,pytest; os.environ["REACT_AGENT_TEST_POSTGRES_URL"]=os.environ["REACT_AGENT_DATABASE_URL"]; raise SystemExit(pytest.main(["tests/apps/expense/test_expense_case_resolution.py","tests/apps/expense/test_expense_case_operations.py","tests/apps/expense/test_expense_case_store.py","tests/apps/expense/test_expense_store.py","-q","--junitxml=/tmp/expense-h3-20261112/contracts.xml"]))'
```

结果：**157 passed, 1 skipped**；H3 SQLite/PostgreSQL 各 **31** 项全部通过。唯一跳过是 SQLite TRUNCATE。报告取回 `artifacts/expense/smoke/h3/postgres-contracts.xml`。最后的 session 隔离补丁另跑 H3 双数据库 **62 passed**（各 31 项），报告 `final-h3-postgres.xml`；相关 H3/权限回归 **75 passed, 31 skipped**，报告 `final-permission-contracts.xml`。三个临时启动容器再次恢复停止状态。

实际重启使用本地独立脚本 `artifacts/expense/smoke/h3/verify_restart.py`：prepare 在随机 schema 保存批准结案、纯工单结案和等待补料三个合成 case 及 Claim/审批/事件快照；重启项目 PostgreSQL 后，finish 在新进程比较 pg_postmaster_start_time，读取恢复状态，验证重复 resolve 仍拒绝、等待扫描无写入、申请人显式补料仅重新排队且 Claim 不变。

```powershell
docker exec -w /tmp/expense-h3-20261112 -e PYTHONPATH=/tmp/expense-h3-20261112/src:/tmp/expense-h1-20261112/deps react-agent-docs-troubleshoot-1 python verify_restart.py prepare
docker restart react-agent-postgres-1
docker exec react-agent-postgres-1 pg_isready -U learn -d learn
docker exec -w /tmp/expense-h3-20261112 -e PYTHONPATH=/tmp/expense-h3-20261112/src:/tmp/expense-h1-20261112/deps react-agent-docs-troubleshoot-1 python verify_restart.py finish
```

结果：`ok=true, restart_verified=true, case_review_claim_recovered=true, repeated_resolve_denied=true, waiting_not_auto_resumed=true, explicit_resume_only_requeues=true, schema_cleaned=true`。重启 schema `expense_h3_smoke_8b6553f252c44207b755c4235d77748b` 已清理，查询 H3 smoke 残留为 **0**；三个临时启动容器已恢复原先停止状态，原 `learn-redis` 未操作。

基础提交 `bffab776cb67eec8682ae8e86f429ac237561e50` 加本轮未提交 diff。最终合同源码快照 SHA256：`209bb07048d552785ddbf5e19a2432c03d68c9c588fd88d8280d30dac1ff3150`；路由 fixture SHA256：`ddeef5c45f453d4b8357980a9f8547bccbb8967e7435b5dc068e115e54a80d33`；政策 v2 fixture SHA256：`7f51e378f09da333a90c7f26261be12de1e09a6a6cee3021024a687d4518cee2`。合同使用合成结构化 Decision，不运行模型或修改历史决策评测集。重启检查覆盖持久化路径；之后新增的 SQLite 并发修正及凭据跨入口绑定/session 隔离已在最终两数据库合同中独立验证。

## 文档与交付边界

文档修改均位于 `docs/specs`，按现有语料配置排除；文档评测 **5/5 PASS**、corpus clean，无受影响案例；已刷新 98 文件 baseline（仅生成时间变化），readiness **PASS** 与 diff check 通过。路线图中既有来源规格/S1 证据的失效链接已修正为现有路径。命令如下：

```powershell
.\.venv\Scripts\python.exe scripts/eval/docs/run_git_docs_eval.py
.\.venv\Scripts\python.exe scripts/eval/docs/run_git_docs_eval.py --refresh-baseline
.\.venv\Scripts\python.exe scripts/ci/check_pr_ready.py
git diff --check
```

当前是可部署工程原型的存储能力，不是主 Workflow 已自动接通工单、不是真实通知、付款或生产 SLA。未接 HTTP/自动建单、H4 通知和界面；交付线、Go 重写、S7 UI 与 react_loop 继续冻结。生成报告/源码快照仅留本地 artifacts，不提交数据库凭据、权限凭据或运行轨迹。
