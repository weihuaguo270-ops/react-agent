# 生产成熟度

**定位**：可服务化、可回归的 Agent 运行时；主场景为 [**证据化文档排障**](EVIDENCE_DOCS_TROUBLESHOOT.md)（当前），目标是 API 故障诊断闭环（下一阶段）。  
**非目标**：多租户平台、自动根因定位、完整鉴权网关。

## 成熟度矩阵

| 能力 | 状态 | 说明 |
|------|------|------|
| ReAct 控制流 + Tool Calling | 已具备 | Core `react_loop`（探索路径） |
| 声明式 Workflow | 已具备 | 检索 → 片段 draft → 引用 policy |
| 权限闸门 deny→ask→allow | 已具备 | 非 OS ACL |
| ToolGuard 超时/重试 | 已具备 | 非容器隔离 |
| Format B 轨迹 | 已具备 | Workflow 可 `to_trajectory()` |
| **证据化文档问答** | 已具备 | 引用校验 + 无依据拒答；14 篇演示语料 |
| 黄金集离线回归 | 已具备 | 34 条分层；见 `DOCS_TROUBLESHOOT_EVAL.md` |
| 公开 RAG/Agent 子集 | 已具备 | 通用能力轨，非主场景门禁 |
| HTTP `/health` + `/v1/chat` + `/v1/workflows` | 已具备 | 离线默认可不耗 Key |
| 结构化错误 + request_id | 已具备 | 统一 error envelope |
| 离线 CI | 已具备 | GitHub Actions |
| **真实资料 ingest**（Git/OpenAPI/增量索引） | 未做 | 下一阶段闭环 ① |
| **现场证据接入**（日志/Trace/配置/探测） | 未做 | 下一阶段闭环 ② |
| **结构化诊断输出** | 未做 | 下一阶段闭环 ③ |
| Docker / K8s / OAuth 网关 | 未做 | — |
| 多租户 / SLA | 本阶段不做 | — |

## 主场景入口

```bash
set REACT_AGENT_APP=docs_troubleshoot
set REACT_AGENT_RAG_MODE=keyword
python examples/demos/demo_workflow.py                  # 确定性 Workflow
python examples/demos/demo_docs_troubleshoot.py
python examples/eval/run_docs_troubleshoot_eval.py
python -m react_agent.server --port 8765
# GET  /health
# GET  /v1/workflows
# POST /v1/workflows/run  {"name":"docs_troubleshoot","query":"..."}
# POST /v1/chat  {"message":"..."}
```

Live LLM 服务模式：`REACT_AGENT_SERVER_LLM=1`（需配置 API Key）。

## 对外表述

- **当前具备**：文档 / Runbook 可引用问答、无依据拒答、34 条黄金集回归、薄 HTTP 面  
- **当前不具备**：读现场日志 / Trace、OpenAPI 自动诊断、结构化修复步骤、根因命中率评测  
- **下一阶段主线**：真实资料 + 现场证据 + 结构化诊断（见 [`EVIDENCE_DOCS_TROUBLESHOOT.md`](EVIDENCE_DOCS_TROUBLESHOOT.md)）
