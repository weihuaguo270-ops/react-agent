# S7 第一刀：独立报销表单

日期：2026-11-13。权威进度见 [Expense 路线图](../roadmap-spec.md)，交互与错误契约见 [表单规格 §9.3](../form-workflow-spec.md#93-s7-表单与运营视图入口)。本切片是申请人表单第一刀；运营视图见 [S7 第二刀](s7-ops-views.md)。整段 S7 在第二刀通过后标为 complete。

## 使用入口

沿用规范咨询的 `server/static/` HTML 随包发布和 `static_files.py` 加载方式，由 FastAPI 提供独立 `/expense`；不接入聊天或评测看板。配置现有 Claim PostgreSQL 连接 `REACT_AGENT_DATABASE_URL`，安装已有服务 extra 后启动：

```powershell
.\.venv\Scripts\react-agent-api.exe --host 127.0.0.1 --port 8765
```

浏览器打开 `http://127.0.0.1:8765/expense`，输入服务 Bearer token 和可信调用边界提供的 `X-Actor-Id`。`GET /expense` 仅返回无业务数据的外壳，Host 校验不豁免；Claim/case HTTP 仍受原鉴权保护。凭据不持久化到浏览器，也不拼进 URL。

## 行为和边界

- 新建后首次保存调用 `POST /v1/expense/claims`；编辑保存调用 PATCH 并携带 `expected_version`，提交前须先保存修改。餐饮、交通、住宿、办公采购展示各自必填项；凭证仅为受控引用，不上传文件。
- 所有写请求带幂等键，进行中阻止重复点击。响应丢失/超时后锁住表单并保留原请求供同键重试；当前页关闭/刷新会丢失内存中的待确认请求，不宣称跨页面持久化。已知 Claim ID 可以重新打开。
- 审核中、终态和未知状态的核心字段只读。过期版本不覆盖服务端，刷新前确认替换未保存修改。前端校验只改善交互，服务端仍为权威。
- Claim 详情、事件、修改和提交的越权与不存在统一 HTTP 404 `not_found`，不改变 case 的 `case_not_found` 契约。切换身份立即清空已展示单据与事件。
- 页面只从 Claim status 和持久化 review/resolution 展示待审、已批准、已拒绝及审批意见；决策 `approve_*` 仅为建议。审批由另一合成审批人调用既有 `resolve_review` 和权限闸门产生，页面没有批准按钮。Claim 事件不等同于 case 时间线。
- 本第一刀不增加待审列表、工单时间线或审批台（第二刀另见 [运营视图](s7-ops-views.md)）。不包含真实邮件/IM、后台常驻调度或 S8 验收。不修改业务规则、Decision 指纹、交付线、Go 或 react_loop。关工单和本地通知成功都不推算为批准；不展示付款/入账完成状态。

## 可重复验证

浏览器 smoke 是显式 opt-in；复用已安装 Chrome，也可通过 `REACT_AGENT_BROWSER_CHANNEL=msedge` 选择 Edge。无需下载浏览器，不增加常规 CI 的浏览器依赖：

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[browser]"
$env:REACT_AGENT_BROWSER_SMOKE = "1"
.\.venv\Scripts\python.exe -m pytest tests/browser/test_expense_form_ui.py tests/service/test_fastapi_expense_claims.py tests/service/test_fastapi_expense_reviews.py tests/service/test_fastapi_expense_cases.py -q -m "not real_llm" --junitxml=artifacts/expense/smoke/s7-form/http-browser-junit.xml
```

真实浏览器 → 本机临时 FastAPI → 隔离 SQLite Claim store → 实际规则 Workflow；未 mock Claim/审批结果。仅对 transport 注入断线/响应丢失；测试审批使用合成身份和 `auto_allow`，不改变服务默认权限策略，也不作为生产审批权限证明。本轮不重新运行数据库物理重启，沿用 S4–S6 各自证据。

- 主路径：新建→保存→编辑（版本 2）→提交待审→既有审批批准或拒绝→刷新结果与事件→重新打开单据。
- 重复点击和创建/更新/提交的“服务端写入成功但响应丢失”：原幂等键重试，目标事件各一份；单独事件查询失败不会误重试写操作。
- 版本冲突无覆盖、查询断线后刷新恢复、越权/不存在同文案、客户端必填提示和分类字段保存。
- 审批意见按文本渲染，脚本字符串不执行；桌面与 375px/320px 窄屏检查字段/页面无横向溢出，主路径输入框无重叠。截图和 JUnit 仅含合成数据，留在本地忽略目录 `artifacts/expense/smoke/s7-form/`。

validation-scope：已有 HTTP 合同不能验证表单状态管理、重复点击、浏览器响应丢失恢复与窄屏布局，因此新增 opt-in 实际浏览器 smoke；鉴权外壳和错误码跨服务边界，复验现有 Claim/review/case HTTP 及共享服务鉴权合同。不增加 S8 发布 gate 或评测样本。

## 本轮结果

- 浏览器 smoke 10 项通过；与既有 Claim/review/case HTTP 联合运行合计 34 passed、20 skipped（未配置 PostgreSQL 测试连接，跳过不作通过证据）。
- 最终中文决策展示再复验批准主路径：1 passed、9 deselected；桌面与窄屏截图位于 `test_form_lifecycle_and_review_result_approved_/`。申请人页面没有新增审批操作。
- CI 同参本地整仓回归（含覆盖率）：1586 passed、120 skipped，覆盖率 76.66%，报告 `ci-local-junit.xml`、`ci-local.log`。此命令只排除了顶层真实模型文件，本地 `.env` 使重复目录中的 9 个 `real_llm` 用例实际运行；它不是纯离线回归，也不作为 S8 或本切片必要的真实模型证据。后续本切片复验显式使用 `-m "not real_llm"`；没有为此再重复整仓运行。
- 仓库 `ruff check src/ tests/` 及 CI 同参 mypy 通过（155 源文件）；git-docs 5/5，受影响用例为空，复核断言后刷新 98 文件基线；最终就绪审计与 diff 检查通过。仅 STATUS/deploy 的语料 hash 变化，docs/specs 沿用既有收录排除。
- 浏览器与数据库使用隔离临时资源；本轮不操作 Docker、不执行物理数据库重启，不改写 S4–S6 历史证据。常规 CI 不设置浏览器 opt-in 时，这 10 项明确 skip，不宣称 CI 自动执行了浏览器验收。

这是可部署工程原型的 UI/HTTP 接线证据，不是生产财务成功率、生产身份系统、真实通知或 SLA 保障。
