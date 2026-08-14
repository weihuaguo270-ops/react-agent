# GitHub 工程 Agent 受控交付

这条流程补齐的是 Agent 应用研发的写侧业务闭环：从可追溯任务进入隔离验证，经过人工审批，再生成候选提交或 Draft PR。评测引擎和轨迹分析仍是发布门禁，不再充当业务产品本身。

## 流程

```text
Issue/任务单
  -> 计划指纹
  -> 隔离克隆
  -> 受限文件替换
  -> 真实测试子进程
  -> shadow 报告
  -> 人工审批（绑定计划指纹）
  -> 候选分支提交
  -> 可选 Draft PR
  -> EvaluationEpisode / 审计 / 告警
```

默认是 `shadow`，不会修改源仓库，也不会访问 GitHub 写接口。`guarded` 只有在审批文件中的 `plan_sha256` 与任务完全一致时才创建候选提交。推送 Draft PR 还要同时提供 `--publish-draft-pr` 和 `allow_external_write=true`，且源仓库必须配置 GitHub origin。

## 本地证据

```powershell
$env:PYTHONPATH = "src"
python examples/demos/run_github_delivery.py `
  examples/fixtures/github_delivery_task.json `
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
python examples/demos/run_github_delivery.py `
  examples/fixtures/github_delivery_task.json `
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
