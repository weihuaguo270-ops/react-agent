# S7 第二刀：运营视图

日期：2026-11-14。权威进度见 [Expense 路线图](../roadmap-spec.md)，工单契约见 [人工接管规格](../human-handoff-spec.md)，表单边界见 [表单规格](../form-workflow-spec.md)。本切片与 [第一刀申请人表单](s7-claim-form.md) 一起构成完整 S7。

## 使用入口

沿用 `server/static/` 随包 HTML 与 `static_files.py` 加载方式，FastAPI 提供：

- `/expense`：申请人表单（补同一单 case 时间线与状态刷新）
- `/expense/ops`：有权队列摘要、待审列表与审批台

二者均不接入聊天或评测看板。配置 `REACT_AGENT_DATABASE_URL`、服务 Bearer、以及受信 `REACT_AGENT_EXPENSE_CASE_ACTORS_FILE`（处理人角色/队列）后启动：

```powershell
.\.venv\Scripts\react-agent-api.exe --host 127.0.0.1 --port 8765
```

浏览器打开上述路径，输入 Bearer 与 `X-Actor-Id`。CaseActor 仅由服务端目录构造；页面不能指定处理人或伪造角色。两外壳 GET 无业务数据且 `Cache-Control: no-store`；Claim/case API 仍受原鉴权保护。

## 行为和边界

- 申请人表单在刷新/打开单据时查询 `GET /v1/expense/cases` 与 `GET /v1/expense/cases/{id}/events`，只展示同一 `claim_id` 的工单状态与时间线；审批结果仍只来自 Claim status / review resolution。文案区分「已批准/已拒绝」与「工单已关闭」；不展示付款或入账完成。
- 运营台接线既有 `/v1/expense/cases`、`/queues` 与 case resolve；列表只显示有权队列，越权/不存在统一 `case_not_found`。可在页面验证认领、释放、转派、升级；转派目标为受控 `queue_id`（可见队列 datalist + 可填写）。
- 批准/拒绝必须绑定合法 `approval_id`、`claim_version`、`decision_hash` 与 `expected_case_version`。无审批绑定只能选择「仅结束人工作业」，不能改 Claim 终态；对已绑定审批的工单用 complete+空 approval 会失败关闭。
- 转派/升级后若当前身份失去队列可见性，写操作结果仍展示，后续时间线按 `case_not_found` 隐藏，不泄露单据。
- 不包含真实邮件/IM、后台常驻调度、S8 验收、交付线、Go 重写或 `react_loop` 变更。关工单或本地通知成功仍不等于批准报销。

## 可重复验证

浏览器 smoke 显式 opt-in；复用已安装 Chrome，也可 `REACT_AGENT_BROWSER_CHANNEL=msedge`：

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[browser]"
$env:REACT_AGENT_BROWSER_SMOKE = "1"
.\.venv\Scripts\python.exe -m pytest tests/browser/test_expense_form_ui.py tests/browser/test_expense_ops_ui.py tests/service/test_fastapi_expense_claims.py tests/service/test_fastapi_expense_reviews.py tests/service/test_fastapi_expense_cases.py -q -m "not real_llm" --junitxml=artifacts/expense/smoke/s7-ops/http-browser-junit.xml
```

运营浏览器 smoke 使用受控 Decision handoff（与 S6 HTTP 接线相同）以便 submit 建单；Claim/case API、权限闸门与 SQL store 为真实实现，不 mock case 端点。申请人第一刀路径仍可用实际规则 Workflow。

- 时间线：提交后申请人页显示工单排队与创建事件；审批台绑定批准后刷新为工单已关闭，与报销单已批准分开展示。
- 待审列表：处理人刷新后可见有权队列与待审工单；未登记身份队列为空。
- 并发认领：两处理人同时 claim，仅一人 200，另一人 `case_already_claimed`；败方可在运营台复现；随后可验证释放、转派、升级且不批准 Claim。
- 绑定 resolve：无审批 complete 只关工单；已绑定审批的 complete 失败；reject/approve 绑定合法版本与 hash。

截图与 JUnit 留在本地忽略目录 `artifacts/expense/smoke/s7-ops/`。

validation-scope：既有 case HTTP 合同不能覆盖浏览器时间线刷新、待审列表交互、页面并发认领反馈与审批台绑定结案文案，因此新增 opt-in 运营浏览器 smoke；外壳鉴权与错误码复验既有 Claim/review/case HTTP。不增加 S8 发布 gate。

## 本轮结果

- 运营浏览器 smoke 4 项通过；与第一刀表单浏览器及 Claim/review/case HTTP 联合运行合计 38 passed、20 skipped（未配置 PostgreSQL 测试连接，跳过不作通过证据）。
- 常规 CI 不设置浏览器 opt-in 时，浏览器项明确 skip。

这是可部署工程原型的 UI/HTTP 接线证据，不是生产财务成功率、生产身份系统、真实通知或 SLA 保障。
