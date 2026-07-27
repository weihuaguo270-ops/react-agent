# Core 架构

结构地图：[`STRUCTURE.md`](STRUCTURE.md)。主场景产品定位：[`EVIDENCE_DOCS_TROUBLESHOOT.md`](EVIDENCE_DOCS_TROUBLESHOOT.md)。

运行时以 **自建 Core** 为默认实现。主场景 **docs_troubleshoot** 当前是证据化文档问答后端，不是完整 API 根因诊断 Agent。

## 分层

```
Apps (docs_troubleshoot)     ← 当前：文档/Runbook 问答 + 引用/拒答
  → Workflow（检索 → 片段 draft → policy）
  → react_loop（自由 ReAct，探索 / 未来诊断步骤执行）
  → Tools + Permission gate + ToolGuard
  → Harness Format B / Eval
  → Server HTTP
```

## Workflow（当前实现）

实质：**检索 → 拼接语料片段（约 280 字/段）→ 引用校验 / 无依据拒答**（`draft.py` + `policy.py`）。  
不综合多源根因、不读现场日志、不输出结构化修复步骤。

```bash
python -m react_agent.workflow run docs_troubleshoot --query "401 怎么返回？"
python examples/eval/run_docs_troubleshoot_eval.py
```

下一阶段在相同 Workflow 骨架上扩展：资料 ingest、现场 evidence step、结构化 final（见 [`EVIDENCE_DOCS_TROUBLESHOOT.md`](EVIDENCE_DOCS_TROUBLESHOOT.md)）。

## 与 LangGraph

| | Core | LangGraph (`experiments/`) |
|--|------|----------------------------|
| 默认 | 是 | 否 |
| 依赖 | 无框架 | 可选 `[langgraph]` |
| 用途 | 主场景 / 评测 / HTTP | 图编排对照 |

## 设计原则

1. 主场景优先文档证据链（引用 / 拒答 / 黄金集）；诊断闭环为下一阶段唯一扩张方向  
2. ReAct / 多 Agent 服务探索与将来「验证动作」执行，非当前产品承诺  
3. 工具表 + 权限表集中扩展；每条流水线可离线回归
