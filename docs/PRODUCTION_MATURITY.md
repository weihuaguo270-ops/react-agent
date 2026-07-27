# 生产成熟度（Production Maturity）

定位：**生产向 Agent 运行时原型** — 可服务化、可回归、可观测；**不是**多租户 Agent 平台。

## 成熟度矩阵

| 能力 | 状态 | 说明 |
|------|------|------|
| ReAct 控制流 + Tool Calling | 已具备 | Core `react_loop` |
| **声明式 Workflow** | 已具备 | `react_agent.workflow`（docs_troubleshoot 内置） |
| 权限闸门 deny→ask→allow | 已具备 | 非 OS ACL |
| ToolGuard 超时/重试 | 已具备 | 非容器隔离 |
| Format B 轨迹 | 已具备 | 跨仓契约；Workflow 可 `to_trajectory()` |
| 主场景：文档/API 排障 | 已具备 | `REACT_AGENT_APP=docs_troubleshoot` |
| 黄金集离线回归 | 已具备 | **Workflow 主路径**；无泄漏；core/hard/refuse；`run_docs_troubleshoot_eval.py` |
| 公开 RAG/Agent 子集 | 已具备 | **分层** smoke/hard/held_out + drop-off；勿单独引 smoke |
| HTTP `/health` + `/v1/chat` + `/v1/workflows` | 已具备 | `python -m react_agent.server` |
| 结构化错误 + request_id | 已具备 | 统一 error envelope |
| 引用校验 / 无依据拒答 | 已具备 | `verify_citations` + policy |
| 离线 CI（Ubuntu/Windows） | 已具备 | 见 GitHub Actions |
| Live LLM 冒烟 | 已具备 | 需 Secret |
| Docker / K8s 部署 | 未做 | 可后续 |
| OAuth / API Key 网关 | 未做 | 服务面暂信任本机 |
| 多租户 / 配额 / SLA | 明确不做（本阶段） | — |
| OS/seccomp 强隔离 | 明确不做（本阶段） | 沙箱仅为进程超时 |

## 主场景入口

```bash
set REACT_AGENT_APP=docs_troubleshoot
set REACT_AGENT_RAG_MODE=keyword
python examples/demo_workflow.py                  # 推荐：确定性 Workflow
python examples/demo_docs_troubleshoot.py
python examples/run_docs_troubleshoot_eval.py
python -m react_agent.server --port 8765
# GET  /health
# GET  /v1/workflows
# POST /v1/workflows/run  {"name":"docs_troubleshoot","query":"..."}
# POST /v1/chat  {"message":"..."}
```

Live LLM 服务模式：`REACT_AGENT_SERVER_LLM=1`（需配置 API Key）。

## 叙事口径

- **是**：可复现运行时 + 垂直场景后端 + 可回归评测 + 薄 HTTP 面  
- **不是**：已上线生产平台 / 替代 OpenHands 级沙箱产品
