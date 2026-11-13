# S6：HTTP 人工接管接线验收

日期：2026-11-13。权威进度见 [路线图](../roadmap-spec.md)，HTTP 字段与服务端身份配置见 [人工接管规格 §11](../human-handoff-spec.md#11-api-规划)。本次只接线既有 H0–H4 能力，不改变 Decision 指纹、react_loop 或 S5 正式审批事实来源。

## 实现

- `server/expense_cases.py` 注册 case 创建/列表/详情/事件、claim/release/transfer/escalate/start/needs_applicant/resume/resolve，以及 queues 摘要。FastAPI 原 Bearer 中间件继续负责服务鉴权；X-Actor-Id 沿用 Claim 原型身份语义。CaseActor 由服务端受信角色/队列文件构造，未配置的 actor 为 applicant；客户端角色、队列成员和处理人不参与授权。
- HTTP store 初始化调用 `enable_handoff(routing)`。受控 reason 的 submit / route_review 与 case/event/outbox 同一 SQL 事务提交；异常全部回滚。原有工单唯一约束和 Claim 行锁保证重复触发复用同一活动 case。创建 HTTP 请求还验证幂等键与 payload，冲突无副作用。
- suggested_queue 不覆盖 v1 的受控 reason 路由；reason_code 只能校验持久化值，不能改写 Decision。无路由/不可用队列保存 unrouted，保留 outbox。旧 S5 自由文本 reason 明确返回 blocked/invalid_handoff，仍保留原 S5 待审和指纹。
- resolve 绑定 approval_id、claim_version、decision_hash、expected_case_version，调用 H3 的既有 resolve_review 与权限闸门，在同事务写审批、Claim 和工单审计。无审批仅可 complete 人工作业，不改 Claim；版本替换、错绑、过期、已处理及重复 resolve 失败关闭。不存在和越权的工单访问统一 404 case_not_found。
- start、needs_applicant、resume 复用显式生命周期。等待补料不由扫描/关单自动恢复；申请人带版本/hash/证据引用 resume 后仅回 queued，保持原截止时间，须重新认领。通知 worker 与 SLA scan 仍为可信有界调用，无新维护 HTTP 或常驻调度。

## 验收入口与证据边界

新增 `tests/service/test_fastapi_expense_cases.py` 复用 H1 隔离 schema fixture；使用真实 FastAPI ASGI HTTP、SQL store、角色目录和审批闸门。受控 Decision 来自显式合成 Workflow fixture，以验证接线；另运行真实旧规则 Workflow 证明旧 reason 仍 blocked，不把合成接线报告为真实财务业务通过率。

```powershell
./.venv/Scripts/python.exe -m pytest tests/service/test_fastapi_expense_cases.py -q
./.venv/Scripts/python.exe -m pytest tests/apps/expense tests/service/test_fastapi_expense_cases.py tests/service/test_fastapi_expense_claims.py tests/service/test_fastapi_expense_reviews.py -q
```

设置 `REACT_AGENT_TEST_POSTGRES_URL` 才运行 PostgreSQL 项；未配置时的 skip 不作通过证据。本轮先检查 Docker 全部 11 个容器和 Compose 标签，复用项目 `react-agent-postgres-1` 及已有 API 运行环境，使用独立临时 schema 并清理；不新建容器、不连接其他项目数据库。H1–H4 的实际 PostgreSQL 重启恢复证据各自保留，本轮不把 Store 重开或 HTTP smoke 改称再次执行物理数据库重启。

具体覆盖：

- submit 自动建单、submit 重放、重复 HTTP handoff 和 SQL route_review 复用活动 case；同幂等键不同 payload 冲突；只产生一份 case_created/outbox；
- suggested_queue 不选人、不覆盖路由；伪造角色/队列/assignee 字段和 header 不提权；Bearer、缺失 actor、越权详情/事件/操作/创建/resolve；队列摘要只显示授权队列；
- 两名队列成员经 HTTP 并发认领只有一人成功，另一人为 case_already_claimed；升级和完整转派审计不改变 Claim；
- HTTP approve/reject 复用同一合法审批；缺失/跨单/过期审批、错误 hash、错误 case 版本、实际 Claim 版本替换、权限闸门拒绝、重复 resolve 均失败关闭；纯工单 complete 不改 Claim；
- 释放锁、开始、等待补料与申请人显式恢复；无路由和队列不可用保存 unrouted；outbox 写失败回滚提交、Decision、审批和工单。

验证结果及日志保存在本地 `artifacts/expense/smoke/s6-http/`。该目录不提交凭据、角色私有目录或轨迹。当前证据是可部署工程原型与合成接线验证；不构成真实通知、生产身份系统、SLA 保障或付款能力。

当前验证结果：

- 最终 HTTP handoff smoke：SQLite/PostgreSQL 合计 40 passed，无跳过。
- H1–H4 与 S6 HTTP 联合合同：218 passed、1 skipped（SQLite 不支持 TRUNCATE）；临时 schema 均由 fixture 清理，三个临时启动的项目容器恢复原先停止状态。
- 仓库全 src/tests Ruff 通过；CI 同参 mypy 通过（155 个源文件）。
- 整仓 offline CI 等价回归：1583 passed、110 skipped、1 failed；唯一失败是 baseline 刷新前的 STATUS.md 漂移断言。刷新后定向复验语料漂移合同、最终 HTTP/Claim/review 路径及新增配置失败关闭测试：37 passed、20 PostgreSQL skips；相应 PostgreSQL HTTP 路径已在上述 40 项双数据库 smoke 中通过。未把首轮失败报告改写为全绿，也未为基线刷新重复整仓运行。
- 配置失败关闭复验：缺失路由文件返回 503 invalid_routing_config，使用结构化存储错误，不能落入 S5 的 ValueError/无数据库兼容回退；非法角色目录返回 503 identity_unavailable，未配置目录无处理权限。
- git-docs 5/5；只有 STATUS.md 的语料 hash 变化，受影响用例为空；复核 must_any / prefer_sources 后刷新 98 文件 baseline，check_pr_ready.py 通过。docs/specs 继续由既有配置排除，不改语料收录范围。

validation-scope：已有 H1–H4 存储测试不能覆盖 HTTP 身份伪造、错误映射、header/请求契约和 submit 自动建单事务，因此新增同库 HTTP smoke；跨 server/Claim/case 边界再运行仓库 offline CI 等价回归。未新增评测集或独立发布 gate。Expense 进度仍以 roadmap-spec.md 为唯一索引，不改用 Harness 根 progress.yaml。

关闭工单仍不等于批准报销；本地 adapter accepted 不等于用户已读或审批人已收到。真实邮件/IM、后台常驻调度、S7 UI、交付线和 Go 重写继续冻结。
