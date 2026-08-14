# Harness 健康度（Agent Work Loop）

**读者：** Agent 开发、质量负责人、集成评审  
**用途：** 将 P0 四层证据映射到 Better Harness 启发的 **五维 Agent Work Loop**，并说明证据状态口径。  
**原则：** 分栏报证据，**不合成单一总分**；缺失证据显式标 `unobserved`。

---

## 五维映射

| Agent Work Loop 维度 | 评什么 | 本仓库机制 | 证据状态（2026-07-30） |
|---------------------|--------|-----------|------------------------|
| **Task Understanding** | 目标与验收是否清晰 | execution/capability eval case `id` → `task_episode_id`；`acceptance_criteria` 写入轨迹 | **wired** — eval case 有 id；轨迹字段已支持 |
| **Controlled Execution** | 路径可复现、权限受控 | `workflow/` · `safety/HITL` · `ToolGuard` · execution **36/36** | **exercised** — [P0 execution](./P0_EVIDENCE_MAP.md) |
| **Change Validation** | 变更可验证、失败可诊断 | trace-debugger 8 类 taxonomy · StepWatcher · golden **27/27** | **exercised** — 包含沙箱 `acceptance_failed` 回流 |
| **Reliable Delivery** | 发版有门禁、风险有 hold | `THRESHOLDS v1` · `--compare` · 跨仓 release gate | **exercised** — 选定集 pass、全量实验 hold |
| **Learning Capture** | 修复是否纵向验证 | [intervention_ledger.json](../trace-debugger/docs/intervention_ledger.json) · flywheel offtrack 6→1 | **outcome_supported** — 一条；其余 **exercised/wired** |

---

## 证据状态定义

借鉴 Better Harness，区分「机制存在」与「机制被用过」：

| 状态 | 含义 | 例子 |
|------|------|------|
| `present` | 仓库里有这套机制 | 存在 `THRESHOLDS.md` |
| `wired` | CI/默认路径能触达 | golden 在 GitHub Actions |
| `exercised` | 本次/近期 run 用过并留痕 | scan compare 触发 review |
| `outcome_supported` | 可比样本证明改进有效 | offtrack 6→1 同批重扫 |
| `missing` | 确认缺失 | 无 intervention ledger |
| `unobserved` | 观测边界外，不推断 | 无 session 时不评 Cursor 规则 |

---

## Task Episode 约定

一个 **Task Episode** = 同一用户目标 + 同一验收边界。

| 字段 | 位置 | 说明 |
|------|------|------|
| `task_episode_id` | 轨迹 JSON / eval case `id` | 稳定 id，跨 scan 与 Process Reward 对齐 |
| `acceptance_criteria` | 轨迹 JSON / eval case | 可读 done 条件，如 `expect_equals`、无 `llm_offtrack` |

```python
from react_agent.harness.recorder import start_trajectory

start_trajectory(
    query="17 * 19",
    task_episode_id="exec_calc_mul",
    acceptance_criteria=["tool calculator returns 323", "no failure_tags"],
)
```

---

## 结构化 findings（CLI）

```bash
cd trace-debugger

tdebug scan ../react-agent/src/react_agent/trajectories 100 \
  --json-out docs/snapshots/pilot_latest.json \
  --compare docs/snapshots/pilot_baseline.json \
  --findings-out docs/snapshots/pilot_latest_findings.json \
  --project-root .
```

输出 `findings.json` 含：

- `gate_decision`: `pass` / `review` / `hold`（THRESHOLDS v1）
- `findings[]`: 每条含 `repair_boundary` + `validation_route`
- `dimensions[]`: 五维证据状态摘要
- `mechanisms[]`: 静态探测（golden、baseline、ledger）

Schema: [findings.schema.json](../trace-debugger/schemas/findings.schema.json)

---

## 干预 Ledger（Learning Capture）

纵向记录「改了什么 → 可比样本 before/after」：

- 文件：[docs/intervention_ledger.json](../trace-debugger/docs/intervention_ledger.json)
- Schema：[intervention_ledger.schema.json](../trace-debugger/schemas/intervention_ledger.schema.json)

新增干预时填写 `comparable_sample`、`before`、`after`、`outcome_state`。

---

## 与 P0 证据地图的关系

| P0 层 | 主要 Work Loop 维度 |
|-------|---------------------|
| 能不能干成 (Execution) | Controlled Execution |
| 坏了能不能撑住 (Reliability) | Controlled Execution + Change Validation |
| 坏在哪 (Failure/tdebug) | Change Validation |
| 评得清不清 (Judge κ) | Task Understanding + Change Validation |

详见 [P0_EVIDENCE_MAP.md](./P0_EVIDENCE_MAP.md)。

---

## 我们保留、不照搬 Better Harness 的

- **不合成 58/100 式总分** — 继续分栏 + gate_decision
- **LLM 自评不作 ground truth** — golden CI + THRESHOLDS 优先
- **Host adapter 全家桶** — 仅 react-agent + Format B 互操作

---

## 修订

| 日期 | 说明 |
|------|------|
| 2026-07-30 | 初版：五维映射、证据状态、findings CLI、intervention ledger |
| 2026-08-14 | 同步外部 GitHub 沙箱的第 8 类失败回流及发布门禁证据 |
