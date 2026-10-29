# CI Phase 0 基线报告

## 状态

**阶段状态：** Partial（历史样本已采集；当前主干 fresh 证据已复核，逐样本基线仍需重新生成，正式独立复审待完成）
**历史采集日期：** 2026-10-22
**仓库：** weihuaguo270-ops/react-agent  
**历史默认分支 SHA：** 97c73014aa4b3787376a9fe07a1a2ec6f2c84a4e
**当前默认分支 SHA：** b78e18d24d7b92ddbeb2076810dc625af1da5673
**来源：** GitHub Actions、Pull Request、Branch Protection 只读 API 快照；对应逐样本结构化记录见 [phase0-baseline.json](phase0-baseline.json)，可读索引见 [phase0-sample-index.md](phase0-sample-index.md)。

当前主干的补充证据核验见 [phase0-fresh-evidence-review-2026-10-28.md](phase0-fresh-evidence-review-2026-10-28.md)。该记录不是正式独立复审；历史 JSON 尚未重新生成，不能把历史样本误读为当前主干的完整 fresh baseline。

历史失败 job 的原始 Actions 日志复核见 [phase0-failure-log-review-2026-10-28.json](phase0-failure-log-review-2026-10-28.json)。70 个失败 job 的日志均可获取；其中 62 个（88.57%）包含可操作的根因证据，8 个（11.43%）只有聚合失败结果或包装 job 失败，因此标为 `partial`。这份复核只补充日志证据，不替换原有 `classification_basis`，也不把 2026-10-22 的历史样本提升为当前主干验证。

Registry v2 的机器可读结构定义见 [registry-v2.schema.json](../registry-v2.schema.json)；当前 `docs/specs/registry.yaml` 仍为 v1，结构契约不代表 v2 校验器或迁移已落地。

该报告冻结当时可见的远程基线。它不代表本地未提交工作树通过 CI，也不把历史 run 视为当前 head 的 fresh verification。

## 样本与方法

- PR：最近 100 个 PR，覆盖 2026-09-07 至 2026-10-21；67 merged、33 closed、0 open。
- test.yml：最近 100 个 workflow runs，覆盖 pull_request 与 workflow_dispatch；41 failure、59 success，其中 94 个 pull_request、6 个 workflow_dispatch。
- daily-smoke.yml：最近 50 个 runs；7 failure、43 success，其中 46 schedule、4 workflow_dispatch。
- 失败 job 逐个从 Actions jobs API 读取；按 job 名统计，多个失败 job 可以来自同一个 run，因此各 job 数量不求和为失败 run 数。
- 失败 job 的日志根因复核单独记录在 `phase0-failure-log-review-2026-10-28.json`；其中 `confirmed` 表示日志给出了可操作根因，`partial` 表示日志只给出聚合结果或包装失败。
- 时长按 workflow createdAt 到 updatedAt 计算，包含排队和运行；这是端到端墙钟近似值，不是 runner 执行时长。

PR 和 run 样本已达到 Spec 建议的 100 个 PR / 100 个 test.yml run；另有 50 个 daily-smoke.yml run。JSON 中逐条保存 PR number、base/head SHA、run ID、事件、结论、时间、关联依据、失败/取消 job、失败 step、分类和分类依据。失败分类默认只表示 job/step 元数据能够支持的类别；没有逐条日志支持的地方不把类别写成确定根因。

## 逐样本复核与当前提交边界

- `pull_requests.samples[]` 保存最近 100 个 PR 的完整索引；`workflows.test.yml.runs[]` 保存最近 100 次 test.yml run；`workflows.daily-smoke.yml.runs[]` 保存最近 50 次 daily-smoke.yml run。
- 每条 workflow run 至少可由 `run_id`、`head_sha`、事件、结论和时间定位；失败或取消运行继续展开到 `reviewed_jobs[]` 及其 `failed_steps[]`。`classification_basis` 明确该分类是否只有 job/step 名称依据。
- `pull_request_numbers` 依次使用 GitHub 返回的 PR 关联、run 标题明确写出的 PR 编号、完全相等的 PR head SHA；只有以上方式都无法匹配时，才使用唯一 head branch 匹配。每条记录都列明 `association_basis`；不唯一或无证据时保留空数组，不根据时间猜测 PR。
- 复核命令、Jobs API 命令和映射规则写在 JSON 的 `reproduction` 字段。报告中的汇总数必须能由逐样本数组重新计算。
- 当前 `spec-registry/v1` 没有 path rules，因此本 Phase 0 不报告历史 mapping coverage；Phase 1 完成 v2 候选映射后，须对冻结 PR 样本离线 backtest，并在 Phase 2 前给出覆盖率和误选/漏选证据。
- 该基线对应默认分支 `main` 的 SHA `97c73014aa4b3787376a9fe07a1a2ec6f2c84a4e`。当前工作树 SHA 为 `e8b23d186a63c9fdc1cf7553f834498bc107241d`；样本中的历史 run 即使 head SHA 相同，也不能替代本次修改后的 fresh rerun。历史 run `39582035222` 曾在该 SHA 上失败，但它只作为历史证据。

## 频繁失败模块

| test.yml 失败 job（最近 100 次 run） | 次数 | 主要失败步骤/现象 |
|---|---:|---|
| test (3.11) | 18 | Pytest (offline)；复现入口：`pytest tests/ -q --ignore=tests/test_real_llm.py` |
| test (3.10) | 14 | Pytest (offline)；同上，完整逐 run step 与分类见 JSON |
| PR ready audit | 15 | Check PR readiness；复现入口：`python scripts/ci/check_pr_ready.py --ci --base-sha <PR_BASE_SHA> --allow-revert` |
| Real LLM (smoke) | 7 | 6 次 live smoke step、1 次 install；复现命令和 provider 前提见逐 run JSON，不能与离线回归混为一类 |
| docker-smoke | 3 | Run container 健康检查或部署 smoke；逐 run JSON 记录复现入口 |
| typecheck | 3 | 2 次 mypy、1 次依赖安装；逐 run JSON 记录失败 step |
| lint | 1 | Ruff lint；入口：`ruff check src/ tests/` |
| security | 1 | pip-audit 安装/审计步骤；逐 run JSON 记录失败 step |
| test-windows (3.11) | 1 | 依赖安装；逐 run JSON 记录失败 step |

CI 总体 41 个失败 run 中，失败 job 主要集中在离线 pytest 和 PR readiness audit。逐样本分类采用失败 job/step 名称；只有下列显式日志例子可以作为根因证据，其他样本需按对应 run URL 查看 failed logs。run [39588383542](https://github.com/weihuaguo270-ops/react-agent/actions/runs/39588383542) 的 `Pytest (offline)` 日志包含 MCP mock 未知工具 `no_such_tool` 与错误码断言不一致；同一 run 内 3.10 job 被 fail-fast 取消，不能计作第二个独立失败根因。run [39229492516](https://github.com/weihuaguo270-ops/react-agent/actions/runs/39229492516) 的 readiness job 失败于 `Check PR readiness`，已检查日志显示 docs corpus baseline changed；Python matrix 的被取消 job 单独标作取消，不混算为根因。逐 run 映射与每个失败 step 分类见可读索引及 JSON。

daily-smoke.yml 的 7 次失败中，5 次停在 `Run daily smoke (offline / mock)`，2 次停在具写权限的创建 PR / 驱动合并步骤。逐 run 的 step 名、分类和复现入口均可在 JSON 复核；step 名分类不等于根因，需在 run 日志确认具体断言或权限错误。

## 时长基线

test.yml 的 created-to-updated 端到端墙钟近似值：

| 事件 / 结论 | N | P50 | P95 | 最大 |
|---|---:|---:|---:|---:|
| pull_request / failure | 38 | 1.52 分钟 | 2.97 分钟 | 6.50 分钟 |
| pull_request / success | 56 | 2.62 分钟 | 4.53 分钟 | 21.87 分钟 |
| workflow_dispatch / failure | 3 | 2.18 分钟 | 2.18 分钟 | 2.35 分钟 |
| workflow_dispatch / success | 3 | 3.20 分钟 | 3.20 分钟 | 4.82 分钟 |

daily-smoke.yml 的 50 次样本：schedule failure N=7，P50 0.37、P95 2.97、最大 3.18 分钟；schedule success N=39，P50 0.45、P95 3.72、最大 4.07 分钟；workflow_dispatch success N=4，P50 3.27、P95 3.55、最大 9.17 分钟。小样本的 P95 只作描述，不作为容量承诺。

因此 15 分钟目标暂未显示为当前 PR run 总时长的主要瓶颈，但这组数字含排队时间、重试和工作流整体跨度，不能替代 Phase 1/2 中实际 PR gate job 的运行时长。仍按 Spec 将 15 分钟保留为待校准假设。

## 当前 Required Checks（2026-10-28 只读复核）

main 当前 Branch Protection 为 strict，并启用管理员保护与线性历史。当前 9 个 required contexts 是：

- lint
- test (3.10)
- test (3.11)
- test-windows (3.10)
- test-windows (3.11)
- typecheck
- security
- docker-smoke
- Harness P4 stage gate

目前没有稳定聚合器作为 required check。`Evaluation evidence` 和真实 LLM 仍是 evidence-only；`Harness P4 stage gate` 是当前唯一纳入保护规则的阶段检查。矩阵、不同平台和下游检查仍直接作为 required contexts，尚未迁移到 Spec 目标中的 `CI / PR gate` 聚合器。

## 当前工作流映射

| 工作流 | 触发与职责 | Phase 0 观察 |
|---|---|---|
| .github/workflows/test.yml | `main` push、pull_request、workflow_dispatch；包含 PR readiness、lint、Python/Windows 测试、typecheck、security 和 Docker smoke | PR #173 合并后的 main push run `40104979097` 成功；当前仍是多个独立 job，尚未形成稳定 `CI / PR gate` |
| .github/workflows/harness.yml | `main` push、pull_request、workflow_dispatch；按 scope 调度 Harness P4 stage gate | 合并后 run `40104979076` 成功；阶段语义仍由 Harness Spec 拥有 |
| .github/workflows/evaluation.yml | `main` push、workflow_dispatch；离线评测和真实 LLM evidence | 合并后 run `40104979077` 成功；不属于普通 PR required check |
| .github/workflows/daily-smoke.yml | 定时与 workflow_dispatch；offline/mock smoke 后可提交变更、创建 PR 并自动推动合并 | 最新 run `40458769216` 成功；写权限自动化仍需 R9 审计 |

## Phase 0 判定

已完成：历史 100 PR、100 个 test.yml run、50 个 daily-smoke run 的样本采集；以及当前 main push、required checks 和拆分后 workflow 的 fresh 复核。

待完成：重新生成当前主干逐样本 JSON/索引；由未参与本次整理的审查者独立复核基线证据、迁移设计和 Phase 1 验收契约。Registry v2 实例与语义校验、selector backtest、聚合器 shadow 和 R9 执行验收属于后续阶段，不作为 Phase 0 的实现任务。证据核验记录见 [phase0-fresh-evidence-review-2026-10-28.md](phase0-fresh-evidence-review-2026-10-28.md)。Phase 1 尚未启动。

## 后续动作

1. 先刷新逐样本基线并完成独立复审；Phase 0 通过后，再进入 Phase 1 定义并校验 Registry v2，逐项映射当前 CI 工作流并保留无法映射命令的 unmapped 项。
2. 将 Python/Windows/离线评估、Real LLM、Docker 和写权限自动化按职责拆成规则，避免把 smoke 探测误读为 live 验证。
3. 进入 shadow 前以同一 PR head SHA 比较旧 workflow 与新选择器；本阶段不改 Branch Protection。
