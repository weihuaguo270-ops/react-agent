# 实验模块

以下模块可运行、可测试，**默认不注册进 Core 工具表**，与主场景 Workflow 路径隔离。启用方式：

```bash
set REACT_AGENT_EXPERIMENTAL_TOOLS=1
```

| Module | Entry | Notes |
|--------|-------|-------|
| RAG | `rag.py`；默认本地 JSON、离线 `REACT_AGENT_RAG_MODE=keyword` | 可选 `REACT_AGENT_RAG_BACKEND=milvus` + `pip install -e ".[rag]"` 使用 Milvus；`examples/demos/demo_rag.py` |
| MCP | `mcp_client.py` / `--mcp`；`REACT_AGENT_MCP_MOCK=1` | stdio 默认；远程 `streamable_http` 可选；评测 `DISABLE_MCP=1` |
| Multi-agent | `orchestrator.py` / `planner.py` | 编排演示；`multi_agent_chain` 懒导入 |
| ToT | `tot.py` | 教学推理工具 |
| Dashboard | `dashboard/` | 本地可视化 |
| LangGraph twin | `experiments/langgraph/` | 图编排对照；无严格行为等价测试；见 `demo_checkpoint_hitl.py` |

工作流总览：[`AGENT_WORKFLOW.md`](AGENT_WORKFLOW.md)。

LangGraph 依赖：`pip install -e ".[langgraph]"`。  
无 Key 演示：`python experiments/langgraph/demo_checkpoint_hitl.py`。  
契约测试：`pytest tests/test_langgraph_harness_contract.py`（recorder → Format B；demo 需已装 langgraph）。

`import react_agent.react_loop` 不应拉起 MCP / Orchestrator / RAG（见 `tests/test_core_lazy_imports.py`）。

## MCP 传输与安全策略

本地开发和离线评测使用 stdio。远程 MCP Server 可以在 `mcp_servers.json` 中声明，
客户端会兼容普通 JSON-RPC 和 `text/event-stream` 响应：

```json
{
  "servers": [
    ["uvx", "mcp-server-time"],
    {
      "transport": "streamable_http",
      "url": "https://mcp.example.test/mcp",
      "token_env": "MCP_TOKEN",
      "max_retries": 2,
      "retry_writes": false
    }
  ]
}
```

远程客户端通过 `Authorization: Bearer <MCP_TOKEN>` 鉴权，并记录脱敏审计事件。
只读调用可以有限重试；高风险写调用默认不重试，且必须提供显式确认回调。
React Loop 仍会先经过权限闸门和沙箱边界检查。生产环境应将 MCP Server 放入独立
Worker 或受控 Broker，不允许宿主进程直接连接不受信任的远程工具。

## RAG 向量存储

RAG 支持两个后端：本地 JSON 是默认值，适合开发、离线评测和无外部服务部署；
Milvus 是显式启用的共享/生产向量存储，适合多进程、多实例和较大语料。启用方式：

```bash
set REACT_AGENT_RAG_BACKEND=milvus
set REACT_AGENT_MILVUS_URI=http://localhost:19530
pip install -e ".[rag]"
```

仓库提供独立 Compose 覆盖文件，可启动 Agent + Milvus Standalone（etcd/MinIO）：

```bash
docker compose -f docker-compose.yml -f docker-compose.milvus.yml up --build
```

默认的 `docker compose up` 仍只启动 Agent，不会拉起 Milvus；停止服务使用
`docker compose -f docker-compose.yml -f docker-compose.milvus.yml down`。

若只想在本机用文件 URI 做真实引擎联调，可额外安装 `pymilvus[milvus_lite]`；生产环境
建议连接独立 Milvus Server，不要把 Lite 文件库当作多实例共享服务。

Milvus Compose 构建会固定 CPU 版 PyTorch，避免在 CPU-only 主机下载 CUDA 运行时；若需
升级 embedding 运行时，通过 `REACT_AGENT_TORCH_VERSION` 构建参数替换为兼容的 CPU wheel。

Milvus 模式使用同一组 `ingest`、`ingest_text`、`query`、`clear`、`list_sources`
接口，并以 embedding 向量检索；业务应用无需感知后端差异。默认不会连接 Milvus，
因此离线测试仍可复现。生产部署还应为集合配置访问令牌、网络策略、备份和容量监控。

2026-09-02 已完成本机 Compose 联调：Milvus、etcd、MinIO 和 Agent 均通过健康检查，
并验证 HNSW 写入、检索、来源枚举、清理与 docs_troubleshoot `/v1/chat`。这只是
`local_integration` 证据，不表示共享集群容量、生产鉴权或 SLA 已完成。

当前向量索引明确使用 HNSW（COSINE），而不是 `AUTOINDEX`：`M=16`、
`efConstruction=200`、查询 `ef=64`，均可通过 `.env` 调整。提高 `ef` 通常增加召回率和
延迟；提高 `M` 通常增加索引内存和构建成本。已有集合若使用其他索引，需要迁移或重建，
因为集合索引参数不会由本适配器静默覆盖。

评测快照与 κ 口径见 [`EVAL_INDEX.md`](EVAL_INDEX.md)、[`P0_EVIDENCE_MAP.md`](P0_EVIDENCE_MAP.md)。
