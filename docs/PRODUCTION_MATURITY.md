# 生产成熟度

本页记录主场景 **docs_troubleshoot** 和通用运行时各块做到哪一步。学习向原型，**不是**平台 SLA 清单。

主场景说明：[`EVIDENCE_DOCS_TROUBLESHOOT.md`](EVIDENCE_DOCS_TROUBLESHOOT.md)。  
**非目标**：多租户平台、自动根因定位、完整鉴权网关。

## 成熟度矩阵

| 能力 | 状态 | 说明 |
|------|------|------|
| ReAct 控制流 + Tool Calling | 已具备 | Core `react_loop`（探索路径） |
| 声明式 Workflow v5 | 已具备 | 证据 → 检索 → synthesize → policy → diagnosis |
| 权限闸门 deny→ask→allow | 已具备 | 非 OS ACL；fix_steps 可进 `pending_fix_steps` |
| ToolGuard 超时/重试 | 已具备 | 非容器隔离 |
| Format B 轨迹 | 已具备 | Workflow 可 `to_trajectory()` |
| **证据化文档问答** | 已具备 | 引用校验 + 无依据拒答；14 篇演示语料 |
| 黄金集 + 扩展 eval | 已具备 | golden 34 + fault 12 + production 5 + git 5；见 `DOCS_TROUBLESHOOT_EVAL.md` |
| 公开 RAG/Agent 子集 | 已具备 | 通用能力轨，非主场景门禁 |
| HTTP `/health` + `/v1/chat` + `/v1/workflows` | 已具备 | 离线默认可不耗 Key |
| 结构化错误 + request_id | 已具备 | 统一 error envelope |
| 离线 CI | 已具备 | GitHub Actions |
| **资料 ingest**（Git / 递归目录 / OpenAPI） | 部分 | v0.3：`ingest.py` + Git `ls-files`；OpenAPI 需显式开关 |
| **现场证据**（error / log / trace / config / health） | 部分 | 调用方传入或 mock/MCP Trace；不自动抓线上流量 |
| **结构化 diagnosis** | 部分 | `cause_rules` + schema；规则为主，非 LLM 多轮推理 |
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

## 对外怎么说

- **现在有**：文档 / Runbook 可引用问答、无依据拒答、四套离线 eval、薄 HTTP 面、传入式现场证据、结构化 diagnosis（规则驱动）  
- **还没有**：自动读线上日志 / Trace、OpenAPI 全自动诊断、历史工单盲测、根因命中率运营指标  
- **接着做**：扩真实语料 eval、加强 diagnosis 泛化、工单回放（需单独治理）
