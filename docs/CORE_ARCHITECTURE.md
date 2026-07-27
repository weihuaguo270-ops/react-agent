# Core 架构

结构地图：[`STRUCTURE.md`](STRUCTURE.md)。主场景说明：[`EVIDENCE_DOCS_TROUBLESHOOT.md`](EVIDENCE_DOCS_TROUBLESHOOT.md)。

运行时默认走 **自建 Core**（不是 LangGraph）。主场景 **docs_troubleshoot** 是文档 / Runbook 问答 + 引用 / 拒答 + 结构化 `diagnosis`，**不是**完整 API 根因诊断 Agent。

## 分层

```
Apps (docs_troubleshoot)     ← 文档问答 + 引用/拒答 + diagnosis
  → Workflow v5（证据 → 检索 → synthesize → policy → diagnosis）
  → react_loop（自由 ReAct；探索 / 将来执行验证动作）
  → Tools + Permission gate + ToolGuard
  → Harness Format B / Eval
  → Server HTTP
```

## Workflow（当前实现）

v5 路径：**现场证据（可选）→ 检索 → 句级合成 → 引用/拒答 → 结构化 diagnosis**（`synthesize.py` + `policy.py` + `cause_rules.py` / `diagnosis.py`）。

- 有语料支撑：合成答案并带引用。
- 无依据：拒答，不编根因。
- 传入 HTTP 错误 / 日志 / Trace：规则映射候选原因；可执行 fix 走权限闸门（`pending_fix_steps`）。

```bash
python -m react_agent.workflow run docs_troubleshoot --query "401 怎么返回？"
python examples/eval/run_docs_troubleshoot_eval.py
```

还没做：自动拉线上日志流、分布式 Trace 平台对接、多轮假设验证推理。

## 与 LangGraph

| | Core | LangGraph (`experiments/`) |
|--|------|----------------------------|
| 默认 | 是 | 否 |
| 依赖 | 无框架 | 可选 `[langgraph]` |
| 用途 | 主场景 / 评测 / HTTP | 图编排对照 |

## 设计原则

1. 主场景先把文档证据链（引用 / 拒答 / 黄金集）跑稳；现场证据和 diagnosis 在 v0.3 有初版，继续扩 eval  
2. ReAct / 多 Agent 给探索和未来「验证动作」用，不是当前对外承诺  
3. 工具表 + 权限表集中维护；每条流水线尽量能离线回归
