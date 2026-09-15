# 部署与交付（P0）

**读者：** 运维、集成方、面试 Demo 演示  
**定位：** 单实例、离线可用的「证据化文档排障」FastAPI 服务 — **不是**多租户平台。

## 最快启动（Docker Compose）

```bash
docker compose up --build
# 浏览器打开 http://127.0.0.1:8765/  — 产品 UI（引用/拒答/diagnosis 可视化）
curl -s http://127.0.0.1:8765/ready | jq .
curl -s http://127.0.0.1:8765/v1/info | jq .
curl -s http://127.0.0.1:8765/v1/chat \
  -H 'Content-Type: application/json' \
  -d '{"app":"docs_troubleshoot","message":"缺少 Authorization 返回什么？"}' | jq .
curl -s http://127.0.0.1:8765/v1/chat \
  -H 'Content-Type: application/json' \
  -d '{"app":"expense","claim":{"category":"餐饮","amount":128,"has_receipt":true}}' | jq .
```

默认容器现在启动 `react-agent-api`（FastAPI + Uvicorn）。原有标准库入口仍可用：
`react-agent-server --host 0.0.0.0 --port 8765`。设置 `REACT_AGENT_API_KEY` 后，
对话、任务、Workflow、安全案件和 Skill 执行接口要求 `Authorization: Bearer <key>`；健康检查和
服务信息接口保持公开，便于容器编排探针使用。

在本地执行 `python -m react_agent.server` 时，安装了 `react-agent[service]` 会默认使用
FastAPI；只有未安装 service 依赖时才回退到标准库 HTTP。

**可视化：** 主场景 UI 内置于 HTTP 服务（`/`、`/ui`），展示 Workflow 五步、引用来源、拒答状态、结构化 diagnosis，**不是**泛聊天窗口。实验性 ReAct 轨迹面板见 `python -m react_agent.dashboard.server`（需 Flask + 可选 LLM）。

默认 **offline** 路径，不消耗 LLM API Key。

## 镜像构建

```bash
docker build -t react-agent:local .
docker run --rm -p 8765:8765 react-agent:local
```

镜像始终安装 FastAPI 服务依赖；如需 Milvus 后端，可用
`--build-arg REACT_AGENT_INSTALL_EXTRAS=rag`，它会在 FastAPI 依赖之上再安装 RAG/Milvus
依赖。

## 健康检查

| 路径 | 用途 | 成功 |
|------|------|------|
| `GET /health` | 存活（liveness） | 200，`status: ok` |
| `GET /ready` | 就绪（readiness） | 200，`status: ready`，`chunks > 0` |

Kubernetes 建议：liveness → `/health`；readiness → `/ready`。

## 环境变量

| 变量 | 默认 | 说明 |
|------|------|------|
| `REACT_AGENT_HOST` | `127.0.0.1`（本地） / `0.0.0.0`（容器） | 监听地址 |
| `REACT_AGENT_PORT` | `8765` | 端口 |
| `REACT_AGENT_DEFAULT_APP` | `docs_troubleshoot` | 未传 `app` 时的默认应用（v0.5+） |
| `REACT_AGENT_APP` | — | 兼容旧变量；工具/workflow 挂载仍可读此值 |
| `REACT_AGENT_RAG_MODE` | `keyword` | 离线检索模式 |
| `REACT_AGENT_SERVER_LLM` | 未设 | `1` 时 `/v1/chat` 走 live ReAct（需 Key） |
| `REACT_AGENT_SERVER_OFFLINE_REACT` | 未设 | `1` 时 `app=default` 走离线 ReAct smoke（CI/deploy，无 Key） |
| `DEEPSEEK_API_KEY` | — | live 模式需要 |
| `REACT_AGENT_DOCS_INGEST_DIRS` | — | 额外语料目录（逗号分隔，可 mount） |

## API 面（交付边界）

默认容器使用 FastAPI/Uvicorn，以下接口由 `react_agent.server.fastapi_app` 提供；标准库
入口保留相同的基础 Chat/Task/Workflow 路径，用于无额外依赖的兼容运行。

```
GET  /health
GET  /ready
GET  /v1/workflows
POST /v1/workflows/run   {"name":"docs_troubleshoot","query":"..."}
POST /v1/chat            {"app":"docs_troubleshoot|expense|default", "message":"...", ...}
GET  /v1/info            applications + pillars
```

响应含 `request_id`；错误为统一 envelope：`error.code / message / request_id`。

## 挂载外部语料（演示级）

```yaml
# docker-compose.yml
volumes:
  - ./fixtures/docs_troubleshoot/production_corpus:/data/extra:ro
environment:
  REACT_AGENT_DOCS_INGEST_DIRS: /data/extra
```

重启后 `/ready` 的 `chunks` 应增加；生产盲测语料可在此验证。

## 部署后自检

```bash
python examples/eval/run_deploy_smoke.py
# 或指定 URL：
python examples/eval/run_deploy_smoke.py --url http://127.0.0.1:8765
```

## 诚实边界（交付说明）

**现在能交付：**

- 单容器、离线文档问答 + 引用/拒答 + 可选传入式现场证据
- 健康探针、固定 API、无 Key Demo

**本阶段不交付：**

- OAuth / API Key 网关、多租户、水平扩缩容方案
- 自动拉取线上日志/Trace、SLA 承诺
- 托管 SaaS

下一阶段见 [`PRODUCTION_MATURITY.md`](PRODUCTION_MATURITY.md) P1（鉴权、结构化日志、配置模板）。
