# Expense H0 契约冻结验收（2026-11-11）

本报告记录 S6 的 H0 小步验收，不替代 [`roadmap-spec.md`](../roadmap-spec.md) 的唯一进度入口。H0 退出条件已通过；S6 仍在进行，H1–H4 尚未实现。

## 范围与证据

- [纯契约模块](../../../../src/react_agent/apps/expense/handoff.py)：reason、队列、角色、错误词表、静态状态机、精确条件映射、路由/SLA 快照和复用校验。
- [受控模拟配置](../../../../fixtures/expense/handoff_routing_v1.json)：`expense-routing-v1`、`expense-sla-v1`；无外部财务系统、身份目录或生产 SLA 承诺。
- [契约测试](../../../../tests/apps/expense/test_expense_handoff.py)：不连接数据库，不创建工单，不调用审批接口。

| H0 退出标准 | 验证内容 |
|---|---|
| 非法状态 | 穷举全部状态之间的边；终态、自转移、未知状态以及 escalated 直接关闭全部拒绝 |
| 非法队列 | 未注册队列、非法升级目标、申请人/错误处理角色、不可用队列均失败关闭 |
| 重复触发 | 显式传入活动 case 快照时返回同一个对象与 case ID；路由/SLA 版本变化不改旧快照；Claim/version/reason/hash 冲突被拒；终态不重开 |
| 无匹配路由 | 空规则返回 unrouted、高优先级、unrouted_case，queue/SLA 为空；没有默认指派 |

额外契约覆盖现有 Skill 的全部三项 `human_handoff_conditions`、预留条件标识、未知条件、不合法 SLA 格式、配置版本/规则唯一性、普通建议及硬拒绝不生成假工单。显式要求人工例外的拒绝可规划待处理工单，不能因此批准 Claim。

## 验证命令与结果

```powershell
$env:REACT_AGENT_PERMISSIVE_TEST_DIRS='1'
.\.venv\Scripts\python.exe -m pytest tests/apps/expense -q
.\.venv\Scripts\python.exe -m ruff check src/react_agent/apps/expense/handoff.py tests/apps/expense/test_expense_handoff.py
.\.venv\Scripts\python.exe scripts/eval/docs/run_git_docs_eval.py
.\.venv\Scripts\python.exe scripts/eval/docs/run_git_docs_eval.py --refresh-baseline
.\.venv\Scripts\python.exe scripts/ci/check_pr_ready.py
git diff --check
```

Expense 回归 **126 passed**，其中 H0 契约用例 53 项。Ruff 通过。pytest 有已有弃用提示及 Windows 沙箱中 `.cache/pytest` 写缓存权限警告，不影响测试通过；使用仓库已有的临时目录开关，没有修改测试基础设施。

git-docs 评测 **5/5**，语料 clean、无受影响断言；当前 `docs/specs` 按既有配置排除于检索语料。已刷新 98 个文件的 baseline（文件哈希未变，只更新刷新时间），`check_pr_ready.py` 为 **PR READY: PASS**，`git diff --check` 通过。没有修改评测用例或断言。

## 尚未接通的运行能力

H0 的 `HandoffPlan` 是计划快照，只有未来 H1 原子落库后才有真实 case ID。测试中的既有 case 是显式构造的契约输入，不是数据库去重证据。H1 需用事务和唯一约束落实并发去重及审计。

本轮没有调整 `route_review` / `resolve_review`、Claim/审批 SQL、权限闸门、HTTP 路由或 Agent 循环；没有 dispatch/认领、截止时间计算、SLA 扫描、通知 outbox worker 或 UI。现有 S5 handoff 的兼容 reason 适配需在后续可信接入层明确实现，不能假定 H0 已接入主链路。交付线与 Go 重写继续冻结。
