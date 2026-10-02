# 项目状态

- 当前收口：统一离线验收入口 `examples/eval/run_portfolio_acceptance.py` 与跨仓证据账本已落地；主线闭环可复现，但 held-out/golden 发布门槛仍未满足，不能宣称生产成熟度。

- 默认入口的安全防线修复（2026-09-30）：容器默认入口是 `react-agent-api`（FastAPI 面），但它读的是从未被文档记录的 `REACT_AGENT_API_KEY`——#97 已把 `DEPLOY.md` 的过时变量名改成 `REACT_AGENT_AUTH_TOKEN`，却漏改了 `fastapi_app` 的读取处，于是**按文档配置等于没配**（鉴权 fail-open），且该面完全没有 Host 头校验，DNS rebinding 防线与 `REACT_AGENT_REQUIRE_HOST_ALLOWLIST=1` 的启动期 fail-closed 都只在 stdlib 面成立。现抽出 `server/auth.py` 的 header 版判据供两面共用（`REACT_AGENT_API_KEY` 保留为 legacy 别名、AUTH_TOKEN 优先），`request_guard` 改为「Host 先于鉴权」并把保护范围对齐文档（除探针外全部），`main()` 补启动期校验与未鉴权暴露告警。配置发现性同步补齐：`.env.example` 增加「服务鉴权与网络暴露」段，`docker-compose.yml` 把两个变量由注释改为直通——此前在 `.env` 里填 token 根本进不了容器。见 [#100](https://github.com/weihuaguo270-ops/react-agent/pull/100)。

- 默认入口的异步审批链路补齐（2026-09-30）：`GET/POST /v1/approvals` 与响应里的 `awaiting_approval`/`approval_id` 此前只在 stdlib 面成立，文档承诺的「命中 CONFIRM → 落盘待批 → 人工批准 → 带 id 重试放行」在默认入口走不通。根因是审批信号用 ContextVar 传递（闸门写、响应侧读），而 FastAPI 面在 `run_in_threadpool` 之外捕获——跨该边界读永远是 `None`。现把「设置请求上下文 + 捕获审批状态」与对话本身放进同一次线程池调用，`/v1/chat`、`/v1/chat/stream`、`/v1/tasks` 统一走它，并新增两个审批路由（错误码与 stdlib 面逐字对齐：找不到 404，已决议/过期/取值非法 409）。见 [#101](https://github.com/weihuaguo270-ops/react-agent/pull/101)。

- `/v1/chat/stream` 事件流对齐（2026-09-30）：`DEPLOY.md` 的事件表对两个入口点都承诺了 Runtime 进度事件，但 FastAPI 面此前只是「跑完 handler 再吐一个终态」，且终态是个从未进过文档的 `completed`——进度事件、心跳、取消语义都没有。现改为 worker 线程 + 事件队列（帧带 `id:`、空闲发心跳、生成器被回收时置位取消信号让 Agent 真的停下来而不是空烧 LLM），终态改为文档承诺的 `done`，补 `GET /v1/chat/stream` 查询参数入口，帧构造与查询解析收敛到 `server/streaming.py` 共用。两个面的共享契约从此有专门的回归测试：`test_server_surface_parity.py`（同一契约矩阵打两个面）与 `test_stream_surface_parity.py`（同一解析器解析 stdlib 真实 SSE 端点与 FastAPI ASGI 的帧），后者还用变异测试确认「断连叫停」断言不是恒真。见 [#102](https://github.com/weihuaguo270-ops/react-agent/pull/102)。

- 本轮合并与验证（2026-09-30）：三个 PR 依次 squash 合并（#100 → #101 → #102，无 merge commit，保持线性历史；main 分支保护为 strict + 线性历史 + 9 项必需检查，且 enforce_admins）。#101/#102 与更新后的 `main` 冲突面固定在三处——`fastapi_app.py`（保留两侧新增、中间件取 #100 版本）、`CHANGELOG.md`（两侧条目都保留）、`docs/` 语料基线（重跑 `eval_git_docs --refresh-baseline`）；「凡改 `docs/` 必刷基线」这条约束本轮再次生效。合并后实测：全量 pytest 11 failed / 538 passed / 7 skipped，失败集与合并前完全相同（`test_failure_regression_gate` 7 项 + `test_github_delivery_workflow` 4 项，均为本地缺 sibling 仓库/网络的既有失败）；三个新测试文件 30 passed；git_docs 评测 5/5、`corpus=clean`。

- 服务层补回（2026-09-28）：`#73` 的测试引用了不存在的模块。根因**不是逻辑缺失，而是拆分丢件**——完整半成品在 `backup/pre-split-wip`（`2a6d272`），拆成 #72–#75 时只带走了测试与部分源码。现按字节补回 `skills/`（schema/contracts/registry/business_boundaries/builtins/evaluation/tools）、`multimodal.py`、`query_policy.py`、`server/fastapi_app.py`、`server/task_manager.py`，并补 `[service]` extra 与 `react-agent-api` 入口点。对 main 已有文件只做最小语义移植（`evidence.py` 的 multimodal 分支、`agent_runner.py` 的按需检索门控、`prompt.py` 一条硬规则）。相关 7 个测试文件 35 passed。#73 已关闭（由 #95 取代），#72 随后按原意合并。见 [#95](https://github.com/weihuaguo270-ops/react-agent/pull/95)。

- 服务入口点对齐（2026-09-28）：合并 #72 时 `DEPLOY.md` 声明"默认启动 `react-agent-api`"而 Dockerfile 仍为 stdlib 入口，两者矛盾。已修 `server/__main__.py` 为「装了 `[service]` 走 FastAPI，否则回退 stdlib」、Dockerfile CMD 改回 `react-agent-api`、`DEPLOY.md` 里过时的 `REACT_AGENT_API_KEY` 改为 `REACT_AGENT_AUTH_TOKEN`。见 [#97](https://github.com/weihuaguo270-ops/react-agent/pull/97)。

- daily-smoke 日志断档修复（2026-09-28）：工作流只创建 PR、**从未包含合并步骤**，导致 `docs/daily_smoke/` 停在 2026-08-16，而此后每天的计划任务都成功运行并开出 PR（累计 42 个未合并）。已给工作流加 `gh pr merge --squash --auto` 并启用仓库级 `allow_auto_merge`（#93 用 `app/github-actions` 开启了 auto-merge，但当时**并未真正落地**：bot 建的 PR 其 `pull_request` 运行会停在 `action_required`（0 个 job），必需检查只能由 `workflow_dispatch` 提供，而 dispatch 的检查**不关联到 PR**，分支保护因此永远不放行；#96/#99/#104/#106 于是又各自残留了一个 PR。直到 2026-10-01 才修好，见 #107/#108/#110/#112：提交前刷新 docs 语料基线、把合并闭环收回 workflow、改为批准被门禁拦下的 `pull_request` 运行、合并后删除 automation 分支）；42 个存量 PR 的内容以**一次性重建**方式补齐（`log.jsonl` 29→71 行、`VARIANCE.md` 42→84 行，日期连续覆盖 2026-08-17~09-27，无重复行）后统一关闭。见 [#93](https://github.com/weihuaguo270-ops/react-agent/pull/93)、[#94](https://github.com/weihuaguo270-ops/react-agent/pull/94)。

- 语料基线的跨平台缺陷修复（2026-09-28）：`sha256_file` 原按原始字节哈希，而 CI 同时在 ubuntu 与 windows 上跑 `test_git_docs_corpus_drift`；Windows 侧 `core.autocrlf=true` 会把 `docs/` 检出为 CRLF，使基线只在生成它的平台上成立。现改为哈希前把 CRLF/CR 归一化为 LF，并加两条用例锁住该不变量（同内容不同行尾必须同哈希、真实内容变更仍可检出）。

- 同轮的其他加固：#92 合并 Subagent 能力（Worker 工具面声明化、**写冲突检测默认开启**、委派深度/并发上限、摘要式 fork、指令解析三处鲁棒性修复，并使 Core 导入路径不再连带装配 RAG 语料）。注：`docs/` 同时是 docs_troubleshoot 的 RAG 语料并带 sha256 基线，**凡改 `docs/` 下文件都需用 `eval_git_docs --refresh-baseline` 刷新基线**。

- held-out/golden 状态**未变**：Click 仍为 `invalid_run`，Jinja 为唯一有效 held-out，golden 仍为 0；本轮改动不涉及盲测成绩。

- v10 协议补丁：发现 v9 终态请求只允许 submit，但服务仍返回 shell，旧运行器继续执行。现已增加完整调用批次校验，违规响应停止为 `protocol_violation`，与 hidden 成绩分开记录。16 项离线测试通过，尚未在线复测；held-out 保持未运行。见 [补丁说明](../eval/blind_pilot_v1/V10_PROTOCOL_PATCH.md)。

- v10 在线复测（2026-09-22）：仅运行新版 Pydantic development。结果为 `terminal_submitted`、hidden passed、51140 tokens、budget compliant；普通阶段 25 次 shell，终态 1 次合法 submit，未触发 protocol violation，因此没有生成违规证据文件。证据完整，Click/Jinja held-out 仍未运行。见 [在线复测报告](../eval/blind_pilot_v1/V10_ONLINE_RETEST_REPORT.md)。

- v10 HTTPX identity 复测触发协议异常：终态请求只开放 submit，但兼容服务返回 shell；运行器正确停止为 `protocol_violation`，未执行违规命令。hidden passed 仅说明已有补丁有效，不计为正常提交。剩余 2 条 development 暂停，待服务工具约束稳定后继续。见 [异常报告](../eval/blind_pilot_v1/V10_HTTPX_PROTOCOL_EXCEPTION.md)。

- 兼容层已改用单工具 `tool_choice: "required"`。HTTPX identity 重测通过：`terminal_submitted`、hidden passed、53473 tokens、21 次 shell + 1 次 submit，未触发协议异常。见 [重测报告](../eval/blind_pilot_v1/V10_HTTPX_REQUIRED_RETEST.md)。

- v10 development 复测汇总：Pydantic、HTTPX identity、HTTPX activity 均 `terminal_submitted` 且 hidden passed；Werkzeug 仍因服务返回终态 shell 触发 `protocol_violation`，hidden failed。服务端工具选择遵循仍不稳定，held-out 暂停。见 [汇总报告](../eval/blind_pilot_v1/V10_DEVELOPMENT_RETEST_REPORT.md)。

- Werkzeug v10 重跑未复现协议异常：合法 `terminal_submitted`、52415 tokens、预算合规，但 hidden failed。模型补丁只覆盖参数为空，遗漏 `Digest` 空值尾随空格；问题转为补丁完整性，held-out 仍未运行。见 [重跑报告](../eval/blind_pilot_v1/V10_WERKZEUG_RETRY_REPORT.md)。

- v10 补丁完整性门禁已接入：结果区分 `patch_empty`、`patch_invalid`、`hidden_failed`、`verified_fix`，并记录 patch 字节数与 SHA256。HTTPX identity 门禁重跑为 `verified_fix`、hidden passed、51707 tokens、562 bytes、SHA256 `efbebdcbe36ecdf13f8073f167e63619b1828546be97b13de9ad614b58b1b2ac`。17 项离线测试通过。见 [门禁报告](../eval/blind_pilot_v1/V10_PATCH_GATE_REPORT.md)。

- v10 development 补丁门禁已完成：Pydantic、HTTPX identity、HTTPX activity、Werkzeug 均 `verified_fix` 且 hidden passed；Werkzeug 本轮为唯一模型主动 `submitted`，其余为 `terminal_submitted`。v6-v10 历史统计未改写，Click/Jinja held-out 未运行，golden 仍为 0。见 [最终结果](../eval/blind_pilot_v1/V10_DEVELOPMENT_PATCH_GATE_FINAL.md)。

- v10 development 审计：hidden 4/4、补丁证据 4/4、主动提交 1/4、token 合计 202933。Pydantic 的运行早于补丁字段接入，已通过原始 diff 离线核验但未改写历史结果。考虑到兼容服务曾出现跨任务终态工具异常，Click/Jinja held-out 暂缓，golden 仍为 0。见 [审计报告](../eval/blind_pilot_v1/DEVELOPMENT_V10_AUDIT.md)。

- held-out 前整改：Pydantic 已补写后核验 patch 字段并明确标注非原始输出；submit-only 探针返回唯一 `submit`（valid=true，335 tokens）；四条 development hidden 与补丁证据复核通过。held-out 仍待独立性最终决策，golden 保持 0。见 [整改记录](../eval/blind_pilot_v1/V10_PRE_HELDOUT_REMEDIATION.md)。

- v10 held-out 已分别运行：Click 为 `protocol_violation`、hidden failed、patch `hidden_failed`；Jinja 为 `terminal_submitted`、hidden passed、patch `verified_fix`。两条结果独立保存，不与 development 合并，golden 仍为 0。见 [分项报告](../eval/blind_pilot_v1/HELDOUT_V10_SEPARATE_REPORT.md)。

- Click 原始异常审计确认：请求仅暴露 submit 且使用 `tool_choice: required`，服务仍返回 shell；保留为 invalid_run。submit-only 探针随后通过，故仅重跑 Click 验证稳定性。

- Click 重跑仍为 `protocol_violation`：两次终态均返回 shell 并被拦截，初次 hidden failed/756 bytes，重跑 patch_empty/0 bytes。Click held-out 标记 `invalid_run`，Jinja 保持 `terminal_submitted` + hidden passed，golden 仍为 0。见 [Click 审计](../eval/blind_pilot_v1/HELDOUT_CLICK_PROTOCOL_AUDIT.md)。
- held-out 结果已冻结：Click 三次原始运行统一标记 `invalid_run`，原因 `service_tool_choice_violation`，不纳入通过率、主动提交率或 golden；Jinja 是唯一有效 held-out（`verified_fix`、hidden passed、`terminal_submitted`，不计主动提交）。不再为凑数量重跑 Click；后续需更换稳定支持强制工具选择的模型/兼容服务并建立新批次，v6-v10 历史记录保持不变。见 [held-out 总报告](../eval/blind_pilot_v1/HELDOUT_V10_SEPARATE_REPORT.md)。

- 最新盲测（2026-09-20）：v6 development 4 条全部完成，隐藏验收 3/4、主动提交 1/4、预算合规 4/4。Pydantic 在限定协议内未形成补丁；另两条验收通过但预算护栏终止。合计 234562 tokens，费用未知。held-out 未运行；详见 [v6 全量报告](../eval/blind_pilot_v1/DEVELOPMENT_V6_FULL_REPORT.md)。

- v7/v8 协议校准：v7 HTTPX identity 的补丁通过 hidden，但预算耗尽且未主动 submit；v8 Pydantic 由控制器进入 `terminal_submitted`，hidden 失败且补丁为空。`terminal_submitted` 不计为主动提交，校准结果不覆盖 v6 全量成绩。Pydantic 任务描述已升级为明确的 PEP 695 named alias / `TypeAliasType` 语义，后续运行作为新输入版本单独统计。详见 [v7/v8 校准报告](../eval/blind_pilot_v1/V7_V8_PROTOCOL_CALIBRATION.md)。

- Pydantic 输入 v2 已单任务重跑：模型正确定位 `RootModel.__eq__` 的 alias 解包缺口，但在 60767 tokens 内未写补丁或运行测试，最终为 `terminal_submitted`、hidden failed、patch 0 bytes。输入歧义已排除，剩余问题是定位后的执行收敛；下一轮协议应增加无编辑进度门禁，不扩大预算。

- 版本基线：`pyproject.toml` 为 **0.9.0**（CHANGELOG 最新已发布段同为 0.9.0）。仓库里另有 `v0.10.0` / `v0.10.1` 两个 tag，但它们只存在于侧分支（`backup/pre-split-wip`、`codex/daily-smoke-pr`），**不在 main 历史里**，也未随 CHANGELOG 发布。
- 最近验证：FastAPI task runner、失败门禁、修复后复验、Docker sandbox、HTTP 应用（可选 Milvus RAG **未随 main 发布**，见 `DEPLOY.md`）
- 可声称：受控软件任务执行、权限闸门、Format B 轨迹、回归评测、容器工具隔离
- 不能声称：生产部署、长期线上 SLA、企业多租户权限体系、Milvus 生产容量（该后端未随 main 发布）
- P0：将 task runner、轨迹、trace-debugger findings 和 eval-engine 发布判断串成单命令验收报告
- 验证：`python examples/eval/harness_closed_loop.py --fixture`
- 闭环报告：`python examples/eval/harness_closed_loop.py --fixture --report-out artifacts/portfolio_acceptance.json`
- 统一离线验收：`python examples/eval/run_portfolio_acceptance.py`，输出 `artifacts/portfolio_acceptance_v1.json`
- 数据账本：[`eval/eval_dataset_ledger.json`](../eval/eval_dataset_ledger.json)，当前真实任务 3 条、全部来自 FastAPI；sandbox 24 条单独计为合成故障样例
- 第一阶段账本校验：`python scripts/validate_eval_dataset_ledger.py` 已验证 60 条来源记录（真实 3、合成 24、规则回归 29、契约样例 4）；所有来源均逐条登记，`verified` 仅在重新运行验收后回填
- 规则回归验证：trace-debugger 黄金集 `42 passed`，已通过工作区可写临时目录补跑此前失败初始化的 10 条 step-watcher 用例；29 条规则回归已回填 verified
- 第一阶段验收状态：已正式闭环（账本来源校验、规则回归补跑和结果回填均完成）
- 第二阶段：跨仓库账本记录 6 条 verified 任务、无待补名额、golden 0 条。无真实来源的旧占位项已移入 placeholder_history，不计入任务数量；不再限制 Pydantic/HTTPX 各 3 条。
- 本轮新增：Werkzeug issue #3127 / PR #3129，无参数 WWW-Authenticate 尾随空格缺陷；独立虚拟环境离线运行，before/after 各重复两次，原始日志、退出码、轨迹及源码归档均已保存并校验 SHA256。
- 新任务验证是上游缺陷可复现性验证，不代表 Agent 解题成绩；隐藏测试位于仓库快照之外，真正 Agent 运行时仍须只挂载代码快照。
- 证据校验：`python scripts/validate_cross_repo_evidence.py`；账本：[`cross_repo_task_candidates.json`](../eval/cross_repo_task_candidates.json)。校验通过已有任务不表示 6 条批次已齐备。
- 6 条任务已完成来源固化、before/after 重复执行、独立 hidden acceptance 和 SHA256 证据校验；下一步是审查多样性与隔离独立性，再决定 golden。
- 数据集缺口：尚未达到 3 个项目、30 条真实任务和 10 条独立 held-out 真实任务的发布门槛

- v5 终态审计（2026-09-20）：四条均由预算护栏停止，显式 submit 0/4，隐藏验收 2/4，实测 token 均未超过 64k。撤回“及时提交已验证有效”的结论；详见 [审计更正](../eval/blind_pilot_v1/V5_TERMINATION_AUDIT.md)。

详细定位与对外口径见 [`PROJECT_CONTEXT.md`](PROJECT_CONTEXT.md)。

- Click PR #2930：新建隔离环境、固定 colorama wheel 离线安装；before 两次目标断言失败，after 两次通过 11 个 CLI 行为场景。原始 stdout/stderr、完整命令、退出码、轨迹和 SHA256 均校验一致。
- Jinja PR #1782 已完成异步生成器去重/过滤器集成的 before/after 验收，状态为 verified。

- 盲测准备：全量任务校验 6/6；已生成固定基线输入包及 4 development / 2 provisional held-out 切分（Click、Jinja）。见 eval/blind_pilot_v1。v3 已完成 1 条 development 协议校准，结果为预算耗尽，未形成补丁；该结果不计入 Agent 成绩，held-out 仍未运行，golden 保持 0。

- deepseek-flash v1/v2/v3/v4 原始流程结果已保留；v5 已完成上下文压缩、本地历史摘要和显式 `submit` 终态优化。development 全量实测为 2/4：`httpx-activity-review` 与 `werkzeug-auth-whitespace-3129` 通过，`pydantic-identity-review` 与 `httpx-identity-review` 预算耗尽；成本仍未知，Click/Jinja held-out provisional 未运行，golden 仍为 0。见 eval/blind_pilot_v1/DEVELOPMENT_V5_FULL_REPORT.md。
