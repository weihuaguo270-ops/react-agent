# 业务试点闭环

本模块把脱敏后的真实任务接入一条可审计闭环：

```text
任务导入 → 脱敏 → baseline → candidate → 人工复核 → 最终状态 → 版本比较
```

入口：`examples/eval/run_business_pilot.py`。

```bash
python examples/eval/run_business_pilot.py
python examples/eval/run_business_pilot.py --source expense
python examples/eval/run_business_pilot.py \
  --dataset artifacts/pilot/redacted_tasks.json \
  --out artifacts/pilot/report.json
```

## 数据要求

每个任务至少包含：

| 字段 | 说明 |
|------|------|
| `task_id` | 稳定任务标识，不能重复 |
| `split` | `dev`、`golden` 或 `held_out` |
| `baseline` / `candidate` | Agent 原始执行结果和时延 |
| `human_review.decision` | `accepted`、`rejected` 或 `pending` |
| `final_status` | `resolved`、`needs_review` 或 `unresolved` |
| `evidence.source_ref` | 脱敏后的工单、Issue 或审计记录引用 |
| `redaction.applied` | 是否已经完成脱敏 |

费用受控试点还会记录 `baseline_provenance` 和 `candidate_provenance`。其中
`baseline_provenance.mode=fault_injection` 表示故意不调用业务工具的失败基线，不能当作历史生产版本的自然失败率。

运行器会在内存中再次脱敏，不覆盖输入文件。输入文件不得提交真实 API Key、Cookie、密码或未脱敏个人信息。

本模块是闭环的评测与证据层，不直接连接工单、GitHub、部署平台或人工审批系统。生产接入时，采集器负责把真实任务和脱敏后的来源引用写入数据集，Agent 运行器写入
`baseline` / `candidate`，复核系统写入 `human_review`，业务系统回填 `final_status`；本模块再统一比较版本。

个人开发者可以跳过企业系统，直接使用仓库内的 `business_cases.json`、公开 GitHub 快照或手工编写的脱敏 JSON。没有真实人工复核和业务终态时，报告应保持 `hold` 或标记为受控夹具，不需要为了运行项目注册企业 SaaS。

`--source expense` 会实际运行仓库内费用业务集：用故障注入 profile 生成 baseline，用参考 Agent 生成 candidate，再转换成闭环报告。该路径的 `evidence_level` 为
`controlled_fixture`，用于验证采集和门禁逻辑，不等于真实工单或生产业务试点。

公开 GitHub 数据采集命令：

```bash
python examples/eval/run_github_business_tasks.py \
  --repository weihuaguo270-ops/react-agent \
  --out docs/snapshots/github_public_read_only_YYYYMMDD.json
```

该报告的 `evidence_level` 为 `public_read_only`：数据来自 GitHub 公共 REST API，查询是只读的，Issue 内容是动态快照，不能当作生产流量或冻结评测集。

## 门禁口径

- baseline 成功：Agent 结果通过且最终状态为 `resolved`。
- candidate 成功：上述条件成立，并且人工复核为 `accepted`。
- 缺少人工复核、最终状态、来源引用或脱敏确认时，报告为 `hold`。
- 候选任务成功率低于 baseline 时，报告为 `hold`。

示例夹具只验证流程，不能作为生产业务成功率或人工节省证据。接入真实数据后仍需保留任务责任人、验收标准、人工处理基线和最终业务状态。

## 2026-08-20 执行记录

| 项目 | 结果 | 证据边界 |
|------|------|----------|
| 费用参考版本 `expense-reference-v1` | 8/8；dev 2/2、golden 3/3、held_out 3/3 | 仓库内确定性费用台账，不是生产流量 |
| 费用故障基线 `expense-no-action-v0` | 0/8；逐用例比较 `hold` | `no_action` 故障注入，专门验证门禁，不是历史版本 |
| GitHub 公开组合集 | 10 个公开仓库、50 条任务；dev 15、golden 20、held_out 15；门禁通过 | GitHub REST 只读元数据，动态快照，无业务写入 |
| Sandbox 回归 | 真实 Docker live-check 23/23；安全专测 17 passed | 本机 Docker 路径已验证；仍不替代生产逃逸测试和供应链审计 |

尚未完成、也没有用合成数据替代的事项：真实脱敏业务任务、真实历史旧版本 baseline、独立业务人员复核、线上最终状态回填和跨多个真实发布版本的持续比较。这些需要外部业务数据与授权；当前报告不得升级为生产收益结论。
