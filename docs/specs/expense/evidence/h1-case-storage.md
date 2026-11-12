# Expense H1 存储验收（2026-11-12）

本报告记录 H1 存储切片验收，不替代 [Expense 路线图](../roadmap-spec.md)。**H1 退出条件已通过**：SQLite/PostgreSQL 合同与实际 PostgreSQL 重启 smoke 均完成。S6 保持 in_progress；不推断完整人工接管、生产能力、真实财务接入或 SLA。

## 交付范围

- `src/react_agent/apps/expense/case_store.py`：使用正式 Claim store 的同一 engine/metadata，提供 create/get/list_cases/append_event/events/outbox。
- 三张表：case、追加式事件、pending outbox；受控 queue definition 与 routing/SLA 版本作为 case 创建快照保存，不新增可变队列目录。
- 创建事务同时保存 case、首事件和 outbox；Claim 行锁及触发作用域唯一约束保证重复创建复用同一工单。追加事件在 case 行锁内分配序号，事件键和序号分别唯一。
- PostgreSQL trigger 拒绝事件 UPDATE/DELETE/TRUNCATE，SQLite trigger 拒绝 UPDATE/DELETE；这不防御拥有 schema 管理权限的数据库管理员。
- 申请人按 Claim 归属访问；处理角色还须有受信队列成员关系；不存在和无权限同为 404/case_not_found。财务管理员可审计读取，不因此获得批准权。
- approval_id 可空，非空必须匹配已有审批的 Claim/version/hash。H1 不写 Claim、审批或审批终态，不复制 `resolve_review`，不实现 case.resolve。

`CaseActor` 是可信调用方输入，不是认证系统；禁止将客户端自报的角色/队列直接作为受信身份。事件仅接受受限的不透明 evidence_ref，调用方仍负责脱敏；outbox payload 只含 case/event ID。outbox 未发送、未接入 Worker、没有生产通知或 SLA。

## 验证与阻塞重试结果

起点为干净 main `b285909ff3f6605c0901c64cb39c9a1a5a276c01`，本轮没有修改 S4–S5、HTTP、权限闸门、Agent 循环、交付线或 UI。

```powershell
$env:REACT_AGENT_PERMISSIVE_TEST_DIRS='1'
.\.venv\Scripts\python.exe -m pytest tests/apps/expense tests/service/test_fastapi_expense_reviews.py tests/storage -q
.\.venv\Scripts\python.exe -m ruff check src/react_agent/apps/expense/case_store.py tests/apps/expense/test_expense_case_store.py scripts/eval/smoke/run_expense_case_postgres_restart_smoke.py
```

结果：**160 passed, 22 skipped**。其中 21 项为未配置 `REACT_AGENT_TEST_POSTGRES_URL` 的 PostgreSQL 合同，1 项为 SQLite 不支持 TRUNCATE。Ruff 通过。已有 harness 弃用提示与 `.cache/pytest` Windows 写权限警告不影响通过；未修改测试基础设施。

合同覆盖连接释放/重建后恢复、并发建单及事件追加、数据库唯一约束、outbox 写失败全事务回滚、历史 SQL 更新/删除拒绝、幂等键冲突、越权查询隐藏存在性、可空或合法审批绑定、陈旧版本/指纹及无 Decision 拒绝、旧自由文本 reason 失败关闭和 unrouted 运营意图。上述 Windows 回归未配置 PostgreSQL，新增的真实数据库合同及进程重启结果见下文。

验证范围按 validation-scope 选择：既有 H0 是纯函数，S4–S5 合同不覆盖新增 case/event/outbox 的原子性、事件触发器或队列读取隔离，因此新增 H1 同库合同及重启 smoke；相关 Expense/审批 HTTP/storage 回归用于确认既有 Claim 与审批行为未变，未扩大到全仓测试。

文档评测 `python scripts/eval/docs/run_git_docs_eval.py` **5/5**、语料 clean、无受影响断言；`docs/specs` 按已有配置排除于检索语料。已执行 `--refresh-baseline` 刷新 98 文件 baseline，文件哈希不变，仅刷新时间；`python scripts/ci/check_pr_ready.py` **PR READY: PASS**，`git diff --check` 通过。这些本地文档检查不能替代 H1 PostgreSQL 退出条件。

早先 Docker 检查受自动审批服务 **503 Service Unavailable** 阻塞，命令未执行。2026-11-12 重试审批成功，已检查全部 11 个容器，并核对 PostgreSQL/API 的 Compose project、working_dir、config_files、service、网络及卷。使用现有 `react-agent-postgres-1`，项目目录为当前仓库，卷为 `react-agent_react-agent-postgres-data`，API 连接 postgres:5432/learn；没有选用无关数据库、没有新建容器或重建镜像。

## PostgreSQL 验收命令与结果

本次在现有 `react-agent-docs-troubleshoot-1` 的 `/tmp/expense-h1-20261112` 放入当前源码/fixture/测试快照，通过 Compose 网络连接同一 PostgreSQL。容器没有 pytest，下载未完成后改用本地已安装的纯 Python pytest 9.1.1 及依赖，隔离放在临时 deps 目录；没有更改容器应用代码或全局依赖。禁用第三方 pytest 自动插件加载。

```powershell
docker exec -w /tmp/expense-h1-20261112 -e PYTHONPATH=/tmp/expense-h1-20261112/src:/tmp/expense-h1-20261112/deps -e PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 react-agent-docs-troubleshoot-1 python -c 'import os,pytest; os.environ["REACT_AGENT_TEST_POSTGRES_URL"]=os.environ["REACT_AGENT_DATABASE_URL"];raise SystemExit(pytest.main(["tests/apps/expense/test_expense_case_store.py","-q","--junitxml=/tmp/expense-h1-20261112/contracts.xml"]))'
```

结果：**41 passed, 1 skipped in 5.55s**；21 项 PostgreSQL 合同全部通过，唯一跳过是 SQLite 不支持 TRUNCATE。运行报告保存在本地 `artifacts/expense/smoke/h1/contracts.xml`（生成物，不提交）。

同一合同文件参数化 SQLite/PostgreSQL。配置已核实项目数据库 URL 为 `REACT_AGENT_TEST_POSTGRES_URL` 后运行：

```powershell
.\.venv\Scripts\python.exe -m pytest tests/apps/expense/test_expense_case_store.py -q
```

每个 PostgreSQL 测试创建随机 `expense_h1_test_<uuid>` schema，结束只删除该测试 schema；不禁用事件触发器、不删除正式历史。

新增 `scripts/eval/smoke/run_expense_case_postgres_restart_smoke.py`：在同一项目 PostgreSQL 中用独立 `expense_h1_smoke_<uuid>` schema，通过两个进程完成 prepare/finish。数据库 URL 从已核实环境 `REACT_AGENT_DATABASE_URL` 读取，不写入状态文件：

```powershell
.\.venv\Scripts\python.exe scripts/eval/smoke/run_expense_case_postgres_restart_smoke.py --phase prepare --state-file artifacts/expense/smoke/h1/state.json
# 外部操作：仅重启已核实的现有项目 PostgreSQL，等待 ready；不新建容器。
.\.venv\Scripts\python.exe scripts/eval/smoke/run_expense_case_postgres_restart_smoke.py --phase finish --state-file artifacts/expense/smoke/h1/state.json
```

finish 必须检测 `pg_postmaster_start_time()` 变化，并验证 case/events/outbox 恢复、去重、事件不可修改、越权失败、Claim/审批不变，再清理自己的随机 schema。失败保留隔离 schema 和状态供诊断，不自动抹去证据。

本次实际命令（prepare 与 finish 为不同 Python 进程）：

```powershell
docker exec -w /tmp/expense-h1-20261112 react-agent-docs-troubleshoot-1 python scripts/eval/smoke/run_expense_case_postgres_restart_smoke.py --phase prepare --state-file /tmp/expense-h1-20261112/state.json
docker restart react-agent-postgres-1
docker exec react-agent-postgres-1 pg_isready -U learn -d learn
docker exec -w /tmp/expense-h1-20261112 react-agent-docs-troubleshoot-1 python scripts/eval/smoke/run_expense_case_postgres_restart_smoke.py --phase finish --state-file /tmp/expense-h1-20261112/state.json
```

结果 `ok=true, restart_verified=true, events=2, outbox_pending=1`；case ID 为 `case_4c808e9998934391b240f3efc9d6fc8e`，隔离 schema `expense_h1_smoke_10760e3e00cc4e32a171e30b6a026607` 已删除。合成状态快照保存在本地 `artifacts/expense/smoke/h1/restart-state.json`，不含数据库凭据，不提交。

最终只读检查 `expense_h1_test_*` / `expense_h1_smoke_*` schema 数量为 **0**。本次为验收启动的 API、项目 Redis、项目 PostgreSQL 均恢复原先停止状态；原有运行中的 `learn-redis` 未操作。没有删除正式 Claim、审批或历史事件。

测试和 smoke 使用合成结构化 Decision，不改写旧 Workflow 的自由文本 handoff reason，不代表 HTTP/Agent 自动建单已接通。H2 认领、H3 case.resolve、H4 通知、S7 UI、Go 重写与交付线继续冻结。
