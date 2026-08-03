# 生产成熟度

本页记录主场景 **docs_troubleshoot** 和通用运行时各块做到哪一步。学习向原型，**不是**平台 SLA 清单。

主场景说明：[`EVIDENCE_DOCS_TROUBLESHOOT.md`](EVIDENCE_DOCS_TROUBLESHOOT.md)。  
**评判基准**：主流 **ReAct + 工具 + HTTP 服务** 形态（非 LangGraph / 图编排）。  
**非目标**：多租户平台、自动根因定位、Checkpoint 中断恢复、复杂图编排。

## 主流对齐 vs 细节优化

| 类型 | 说明 |
|------|------|
| **主流对齐** | LLM ReAct、领域工具、RAG、HTTP API、health/ready、Docker、基础轨迹、离线回归 |
| **细节优化** | 循环内 duplicate 拦截、收尾步强制作答、ToolGuard、verify_citations 工具步、fix_steps 权限闸门、StepWatcher + failure flywheel |
| **待补齐（主流交付）** | Bearer API Key、结构化 JSON 日志、verify_actions 由 Agent 执行（非仅输出字符串） |
| **本阶段不做** | OAuth 网关、多租户 SLA、Helm 规模化、自动拉线上 Trace |

## 成熟度矩阵

| 能力 | 状态 | 说明 |
|------|------|------|
| **离线 Agent 循环**（默认） | 已具备 | `agent_runner`：观测选工具 + verify + 轨迹 |
| ReAct + Tool Calling（Live） | 已具备 | `react_loop`；`REACT_AGENT_SERVER_LLM=1` |
| 声明式 Workflow v5（legacy） | 已具备 | `REACT_AGENT_DOCS_ENGINE=workflow` |
| 权限闸门 deny→ask→allow | 已具备 | 非 OS ACL；fix_steps 可进 `pending_fix_steps` |
| ToolGuard 超时/重试/熔断 | 已具备 | 非容器隔离 |
| 循环内 guardrails | 已具备 | duplicate 拦截、reserve_final、Harness 自修 |
| Format B 轨迹 + StepWatcher | 已具备 | 可选 failure tag；flywheel 回灌 |
| **证据化文档问答** | 已具备 | 引用校验 + 无依据拒答；14 篇演示语料 |
| 黄金集 + 扩展 eval | 已具备 | golden 34 + fault 12 + production 5 + git 5（**验收**） |
| HTTP `/health` `/ready` + `/v1/chat` | 已具备 | 离线默认可不耗 Key |
| 结构化错误 + request_id | 已具备 | 统一 error envelope |
| 产品 UI（证据链 + Agent 步） | 已具备 | `GET /` |
| Docker 单实例交付 | 已具备 | `docs/DEPLOY.md` |
| **资料 ingest** | 部分 | Git / 目录；OpenAPI 需显式开关 |
| **现场证据** | 部分 | 调用方传入；不自动抓线上流量 |
| **结构化 diagnosis** | 部分 | 规则为主；verify_actions 尚未接工具执行 |
| Bearer API Key / JSON 日志 | 未做 | P1 |
| 轨迹级 eval 门禁 | 未做 | 规划：must_call 工具步序 |
| 多租户 / SLA | 本阶段不做 | — |

## 主场景入口

```bash
set REACT_AGENT_APP=docs_troubleshoot
set REACT_AGENT_RAG_MODE=keyword
python examples/eval/run_docs_troubleshoot_eval.py      # 默认 agent 路径
python -m react_agent.server --port 8765                 # 浏览器 http://127.0.0.1:8765/
# GET  /health  /ready  /v1/info
# POST /v1/chat  {"message":"..."}   # 离线 Agent 或 REACT_AGENT_SERVER_LLM=1
# POST /v1/workflows/run             # legacy DAG（可选）
```

Live LLM：`REACT_AGENT_SERVER_LLM=1`（需 API Key）。Legacy Workflow：`REACT_AGENT_DOCS_ENGINE=workflow`。

## 对外怎么说

- **整体**：与常见 **Runbook / 文档 Copilot Agent** 同构 — ReAct + 领域工具 + HTTP 交付  
- **细节**：循环内治理（verify 工具步、duplicate 拦截、fix 权限、轨迹飞轮）— 优化 **可跑、可审计、可回灌**，不是换图编排框架  
- **现在有**：Agent 默认路径、Docker、探针、传入式现场 evidence、结构化 diagnosis（规则）  
- **还没有**：API Key 网关、结构化 JSON 日志、verify_actions 真执行、历史工单盲测  
- **P1**：Bearer 鉴权、JSON 日志、verify_actions 接 `react_loop`、轨迹级 eval
