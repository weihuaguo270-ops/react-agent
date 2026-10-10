# GitHub 工程 Agent 受控交付

这条流程补齐的是 Agent 应用研发的写侧业务闭环：从可追溯任务进入隔离验证，经过人工审批，再生成候选提交或 Draft PR。评测引擎和轨迹分析仍是发布门禁，不再充当业务产品本身。

## 流程

```text
Issue/任务单
  -> 计划指纹
  -> 隔离克隆
  -> 受限文件替换
  -> 真实测试子进程（或 SoftwareTaskRunner）
  -> 失败回归门禁（默认开启：tdebug + eval-engine）
  -> shadow 报告
  -> 人工审批（绑定计划指纹）
  -> 候选分支提交
  -> 可选 Draft PR
  -> EvaluationEpisode / 审计 / 告警
```

验收通过后会默认调用 `react_agent.eval.failure_regression_gate`。sibling 缺失或
`release_decision` 为 `hold`/`review` 时，状态为 `failure_regression_unavailable` /
`failure_regression_hold`，**不会**创建候选提交，并标注 `reverify.required`。

修复后必须再跑强制复验：`run(..., reverify_from=<上次 failure-regression 目录>)`，
仅当 `improved_to_pass` 才可放行；也可注入 `WorkflowConfig.repair_loop` 在同一次 run
内自动修复并复验。详见 `docs/FAILURE_REGRESSION_PIPELINE.md`。

## 统一软件任务验收门

`DeliveryTask` 现在可以携带 `allowed_paths`、`hidden_test_command`、
`timeout_seconds` 和 `max_output_bytes`，并转换为统一的 `SoftwareTask`。
在 `WorkflowConfig` 注入 `SoftwareTaskRunner` 后，公开测试和隐藏测试都会在
Docker 中执行，容器使用断网、只读根文件系统、非 root 用户和资源上限；测试失败、
超时或修改允许路径之外的文件都会把交付置为失败。`SoftwareTaskRunner` 出口同样默认挂上
失败回归门禁。未配置该验收门时，保留原有的本地测试路径，便于离线开发和历史夹具兼容。

这项接入解决了两套任务契约并存、隐藏测试无法进入交付报告的问题，但目前仍需在
真实公开 Issue 上冻结 baseline/candidate 版本，才能比较 Agent 版本变化带来的业务结果。

Agent 生成的修改必须先返回结构化 `replacements` 数组，再由
`react_agent.apps.patch_planner.parse_patch_plan` 校验路径、字段和替换内容，最后
转换为 `Replacement` 交给本流程。该解析器不直接写文件；文件替换仍由交付流程执行，
因此模型不能通过自由文本绕过路径限制。

受控修复循环由 `react_agent.eval.repair_loop.RepairLoop` 提供。它接收可注入的
`planner` 和 `executor`：每轮先校验补丁、执行公开测试；失败时把结构化失败信息
交回 planner，最多执行 `max_attempts` 轮；公开测试通过后才执行隐藏测试。隐藏测试
失败或达到轮次上限都会结束任务，不会继续尝试或发布外部写操作。该循环本身不绑定
具体模型，因此可以接入现有 ReAct，也可以接入可选 LangGraph。

默认是 `shadow`，不会修改源仓库，也不会访问 GitHub 写接口。`guarded` 只有在审批文件中的 `plan_sha256` 与任务完全一致时才创建候选提交。推送 Draft PR 还要同时提供 `--publish-draft-pr` 和 `allow_external_write=true`，且源仓库必须配置 GitHub origin。

## 本地证据

```powershell
$env:PYTHONPATH = "src"
python demos/run_github_delivery.py `
  fixtures/github_delivery_task.json `
  --artifact-dir artifacts/github-delivery `
  --idempotency-key local-delivery-demo-1 `
  --episode-out artifacts/github-delivery/episodes/local-delivery-demo.json
```

产物：

| 文件 | 用途 |
|------|------|
| `runs/<run_id>/report.json` | 状态、测试、延迟、审批、回滚和证据边界 |
| `audit.jsonl` | 追加式运行审计 |
| `idempotency.json` | 请求键与计划指纹绑定，阻止重复副作用 |
| `episodes/*.json` | 给 llm-eval-engine 和 trace-debugger 的统一业务终态证据 |

账本和审计文件只保存相对于 `artifact-dir` 的产物路径，整个证据目录可以随项目迁移。

## 审批文件

先运行 shadow，从报告读取 `plan_sha256`，再由审批人生成：

```json
{
  "plan_sha256": "<shadow 报告中的指纹>",
  "approver": "reviewer@example.com",
  "approved_at": "2026-08-14T12:00:00+08:00",
  "allow_external_write": false
}
```

候选提交验证：

```powershell
python demos/run_github_delivery.py `
  fixtures/github_delivery_task.json `
  --artifact-dir artifacts/github-delivery `
  --mode guarded `
  --approval approval.json `
  --idempotency-key local-delivery-demo-2
```

## 控制边界

- 文件路径必须位于克隆工作区内；每个替换目标必须唯一命中。
- 测试命令不经过 shell，默认只允许 `python -m pytest`、`python3 -m pytest` 或 `pytest`。
- Base 分支从不直接修改；候选提交位于隔离克隆的 `agent/*` 分支。
- 发布 Draft PR 是显式外部写操作，不能由 shadow 或普通审批隐式触发。
- 测试失败、待审批和 SLO 超限进入结构化告警；失败 Episode 可进入现有回归与失败治理流程。
- Docker 验收门的结果包含 `public_test`、`hidden_test`、`changed_paths`、
  `unauthorized_paths` 和 `task_hash`，可直接用于版本对比和发布门禁。

## 当前证据等级

本地影子运行和候选提交使用真实 Git、真实文件变更和真实测试子进程，可标记为 `local_real`。
独立 [`agent-delivery-sandbox`](https://github.com/weihuaguo270-ops/agent-delivery-sandbox)
进一步完成了真实 GitHub 写入和 PR 生命周期验证，可标记为 `external_real_sandbox`：

- 冻结 24 条合成 Issue（dev/golden/held-out = 6/10/8），Shadow 24/24，外部写入为 0，P95 606.258 ms；
- guarded 4/4 创建 Draft PR，P95 8457.034 ms；人工接受 3 条、拒绝 1 条；
- PR #27 合并后由 PR #29 回滚；故障注入在写入前被测试拦截；
- 选定发布集 task_01 + task_18 的跨仓门禁为 `pass`，包含 1 条 held-out；保留全部候选时因拒绝案例为 `hold`。

证据见沙箱仓库的 [`evidence/experiment_20260814.json`](https://github.com/weihuaguo270-ops/agent-delivery-sandbox/blob/main/evidence/experiment_20260814.json)
和 [`evidence/selected_release_20260814.json`](https://github.com/weihuaguo270-ops/agent-delivery-sandbox/blob/main/evidence/selected_release_20260814.json)。
这些任务和审批均为沙箱实验，不包含生产用户、真实流量、人工执行耗时基线或单任务模型成本，因此不能标记为生产证据。

下一项项目级证据是接入有明确责任人的真实业务任务，测量人工基线、Agent 增益、成本和长期运行稳定性，并接入企业权限与发布阻断系统。
