# Harness P0 基线冻结报告

**日期：** 2026-10-14（Asia/Shanghai）  
**范围：** Runtime Harness、Evaluation Harness、Format B 轨迹和跨仓闭环  
**状态：** `frozen-clean-head-baseline`

## 1. 结论

项目已有产物不会阻止 P0 基线确认，但会改变基线记录方式。本次采用分层基线：

1. **HEAD 基线：** Git 提交 `f2cf3936b89061f120ba5a272e9483e24dfb5305`，用于识别迁移前可追溯代码状态。
2. **工作区候选快照：** 当前迁移后的工作区，用于记录本轮实际可运行行为，但不能冒充迁移前基线。
3. **历史/已有产物：** 只保留原路径、来源、时间和 hash；不重新计入本次通过率，也不覆盖历史报告。

因此，本报告同时确认了干净 HEAD 基线和工作区候选快照。后续 Phase 1/2 比较必须明确选择其中一个来源，不得混用。

## 2. 工作区边界

采集命令：

```powershell
git rev-parse HEAD
git status --porcelain=v1
```

结果：

| 项目 | 值 |
|---|---:|
| HEAD | `f2cf3936b89061f120ba5a272e9483e24dfb5305` |
| 状态项总数 | `153` |
| 删除 | `101` |
| 修改 | `32` |
| 未跟踪 | `20` |
| 状态清单 SHA256 | `d63d1b204f25363caa57fd6b13e1b5b40fb8a1e493649c54b85f1f0dcf741b6e` |

工作区包含本次 Harness 迁移文件，因此迁移结果必须记录 `source_state=working_tree_candidate`；本报告的干净 HEAD 结果记录为 `source_state=head_clean_archive`。

## 3. 当前可复现实验

### 3.1 Harness 闭环 fixture

命令：

```powershell
.\.venv\Scripts\python.exe scripts/eval/acceptance/harness_closed_loop.py `
  --fixture `
  --report-out artifacts/harness-baseline-20261014-closed-loop.json
```

结果：

| 项目 | 结果 |
|---|---|
| Schema | `OK`，Format B，1-based steps |
| Trace Debugger | `success=true`，`needs_fix=false`，`failures=[]` |
| 工具 | `web_search`, `web_search` |
| Eval Engine | `overall_score=4.333`，`num_steps=3`，`pass_rate=1.0` |
| release decision | `pass` |
| 报告 SHA256 | `93d1fa401f139152ead22148ae89fd0e5da9a696a281b9dc1c38b29b73677eab` |

该结果是当前工作区的 fixture smoke 证据，不是端到端真实模型成功率，也不是生产质量结论。

### 3.2 干净 HEAD 聚焦回归

命令：

```powershell
.\.venv\Scripts\python.exe -m pytest -q `
  tests/test_harness_schema.py `
  tests/test_harness_reliability.py `
  tests/test_harness_closed_loop_decision.py `
  tests/test_reliability_harness.py `
  tests/test_workflow.py `
  tests/test_execution_http_smoke.py
```

结果：`27 passed`，1 条 pytest 缓存目录权限警告。该结果来自 HEAD clean archive。

### 3.3 工作区候选回归

迁移工作区的新增契约测试和适配测试另行运行，结果为 `33 passed`；该结果不回写为 HEAD 基线。

## 4. 产物分类规则

| 分类 | 处理方式 | 示例 |
|---|---|---|
| `current_worktree_reverified` | 可以用于本轮迁移前后比较，但必须记录工作区状态和命令 | `artifacts/harness-baseline-20261014-closed-loop.json` |
| `historical_report` | 保留原始文件和 hash，不重新统计 | `docs/reports/`、`docs/snapshots/` 中带历史日期的报告 |
| `fixture_offline` | 可验证协议、评分和失败分类，不代表生产行为 | `fixtures/harness_closed_loop.json`、软件任务 fixtures |
| `held_out_or_golden` | 保持不可变；模型/服务/协议变化建立新 batch | `eval/blind_pilot_v1/`、各 held-out episode |
| `unverified_or_environment_limited` | 只能记录限制，不得计为 pass 或 fail | 依赖 Docker、网络、sibling repo 或 ACL 的产物 |

当前 `artifacts/` 目录确实存在大量 Expense、software-task、delivery 和 Harness 产物。它们不影响基线确认，但不能在没有来源和重验证标记的情况下合并为 Harness 总分。

## 5. P0 验收判定

| P0 项 | 判定 | 说明 |
|---|---|---|
| HEAD 和工作区状态可追溯 | `pass` | 已记录 commit、状态计数和状态清单 hash |
| 现有产物有分类口径 | `pass` | 已区分当前重验证、历史、fixture、held-out 和未验证 |
| Format B fixture 可运行 | `pass` | Schema、Trace Debugger、Eval Engine 均有结果 |
| 聚焦 Harness 回归可运行 | `pass` | `33 passed` |
| 干净迁移前基线 | `pass` | 从 HEAD `f2cf3936...` 解包 clean archive 后独立运行，fixture pass、聚焦测试 27 passed |
| 生产 SLA/安全/真实用户效果 | `unobserved` | 本 P0 不采集这些证据 |

## 6. 后续比较规则

- Phase 1/2 的新结果必须写入新的 batch 目录，不覆盖本报告或已有历史 artifacts。
- 代码、fixture、模型、工具协议或配置变化时，生成新的 `source_state` 和 manifest hash。
- 通过率按 `dev`、`golden`、`held_out`、`production` 分栏统计；不合并不同来源。
- `pass_existing_fix`、历史报告和已有 patch 不能自动转化为 `reverified=true`。
- HEAD clean archive 的 fixture 报告 SHA256 为 `93d1fa401f139152ead22148ae89fd0e5da9a696a281b9dc1c38b29b73677eab`。
- 当前工作区候选结果只能与 `source_state=working_tree_candidate` 的结果比较，不能覆盖 HEAD 基线。
