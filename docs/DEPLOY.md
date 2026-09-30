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
`react-agent-server --host 0.0.0.0 --port 8765`。设置 `REACT_AGENT_AUTH_TOKEN` 后，
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
| `REACT_AGENT_AUTH_TOKEN` | 未设 | 共享密钥；设置后除 `/health`、`/ready` 外**所有接口**要求 `Authorization: Bearer <token>`（或 `X-Api-Key`） |
| `REACT_AGENT_API_KEY` | 未设 | **兼容别名**：等价于 `REACT_AGENT_AUTH_TOKEN`，两者同时设置时后者优先。仅供早期 FastAPI 面部署平滑过渡，新部署请只用 `REACT_AGENT_AUTH_TOKEN` |
| `REACT_AGENT_STRICT_CONFIRM` | 未设 | `1` 时未注入 HITL 则**拒绝** `CONFIRM` 级工具（失败关闭）；注意会一并禁掉 `execute_python` |
| `REACT_AGENT_APPROVAL_MODE` | `auto_allow` | `async` 时启用**异步人工审批**：`CONFIRM` 级工具落盘待批项并阻塞，人工经 HTTP 批准后放行 |
| `REACT_AGENT_APPROVAL_DIR` | 见说明 | 待批项存放目录；默认 `data_dir()/approvals`。**必须可写**，否则闸门失败关闭（拒绝执行） |
| `REACT_AGENT_LLM_STREAM` | `1` | `1` 时 LLM 走流式（`answer_delta` 增量 + 断连即时取消）；`0` 回退一次性返回 |
| `REACT_AGENT_ALLOWED_HOSTS` | 未设 | 额外允许的 Host（逗号分隔），用于反代/自定义域名 |
| `REACT_AGENT_HOST_VALIDATION` | `loopback` | Host 校验档位：`loopback` / `allowlist` / `permissive` |
| `REACT_AGENT_REQUIRE_HOST_ALLOWLIST` | 未设 | `1` 时启用严格模式：绑定非回环且未声明 `REACT_AGENT_ALLOWED_HOSTS` 则**拒绝启动**（exit 2） |

## API 面（交付边界）

默认容器使用 FastAPI/Uvicorn，以下接口由 `react_agent.server.fastapi_app` 提供；标准库
入口保留相同的基础 Chat/Task/Workflow 路径，用于无额外依赖的兼容运行。

```
GET  /health
GET  /ready
GET  /v1/workflows
POST /v1/workflows/run   {"name":"docs_troubleshoot","query":"..."}
POST /v1/chat            {"app":"docs_troubleshoot|expense|default", "message":"...", ...}
POST /v1/chat/stream     同一请求体，返回 text/event-stream；见下方事件表
GET  /v1/chat/stream?app=default&message=...  EventSource 兼容入口（查询参数形式）
GET  /v1/info            applications + pillars
GET  /v1/approvals       列出未决的人工审批项（异步审批模式）
POST /v1/approvals/{id}  {"decision":"approve"|"deny","scope":"once"|"session"}
```

响应含 `request_id`；错误为统一 envelope：`error.code / message / request_id`。

`/v1/chat` 保持同步 JSON 返回；`/v1/chat/stream` 在请求级队列中转发 Runtime 进度，并以 `done` 作为终态。SSE 事件中的工具参数和观测结果应视为调试/产品内事件，生产接入前仍需按租户策略脱敏、鉴权和限制事件保留周期。

### `/v1/chat/stream` 事件表

| 事件 | 含义 |
|------|------|
| `started` | 请求已受理 |
| `runtime` | 运行时状态（started / completed / failed） |
| `step` | 步开始/结束（末步带 `kind: final`） |
| `tool_call` / `tool_result` | 工具调用的参数与观测 |
| `answer_delta` | **答案增量**（`delta` 字段）；仅在 LLM 流式开启时出现 |
| `answer` | 完整答案（终态答案，供客户端对账） |
| `result` / `error` | 最终载荷或错误 envelope |
| `cancelled` | 客户端断开导致中止（非错误） |
| `heartbeat` | 10s 无事件时的保活帧 |
| `done` | 终态；`cancelled: true` 表示被取消 |

**答案流式**默认开启（`REACT_AGENT_LLM_STREAM=0` 可回退为一次性返回）。开启时 `answer_delta` 会边生成边推送，客户端可即时渲染；`answer` 仍在结束时给出权威全文。

**断连取消**：客户端断开 SSE 连接后，服务端会置位请求级取消信号，Agent 在
**步间**与**工具执行前**检查它并立即停止——不会继续跑完剩余步数，因此不再空烧
LLM 调用。若不需要该行为可在客户端侧忽略，但服务端终止已生效。

## 网络暴露与访问控制

服务**默认不鉴权**（本地开发便利）。除 `/health`、`/ready` 探针外，所有接口都能驱动 Agent 工具（含 `execute_python`），因此一旦对外可达必须显式加固。

### 两道独立的防线

| 防线 | 挡什么 | 机制 |
|------|--------|------|
| `REACT_AGENT_AUTH_TOKEN` | 未授权调用 | 每请求校验 `Authorization: Bearer`；探针保持开放供编排探活 |
| Host 头校验 | **DNS rebinding** | 浏览器按 URL 主机名填 Host；攻击者把域名重新解析到本机后，浏览器视作同源。校验 Host 是唯一能挡住这条读取链的手段 |

> 说明：本项目不发 CORS 头，也不实现 `OPTIONS`。这能阻止跨源**读取**响应，但挡不住 binding 后的同源读取——所以 Host 校验不可省略。

### ⚠️ 第三道防线：CONFIRM 级工具当前**无人把关**

`safety/human_in_the_loop.py` 有完整的 HITL 实现（授权缓存、超时、审计日志），但**生产入口从未注入它**——`permission_gate.set_hitl()` 只在测试里被调用。因此非严格模式下 `CONFIRM` 级工具会**自动放行**：

| 工具 | 默认配置（沙箱 auto/process）下的实际行为 |
|------|--------------------------------------------|
| `execute_python` | **在宿主执行**（任意代码） |
| `clear_trajectories` | **在宿主执行**（删除轨迹） |
| `read_config_snapshot` / `probe_service_health` / `fetch_trace` | 被沙箱拦下（不在沙箱子进程注册表内），**不可达** |

也就是说：**权限表看起来有闸门，默认模式下实际没有人工审批**。启动日志会打印告警，`/ready` 的 `confirmation_gate` 字段也会暴露该状态，可用它做部署前检查：

```json
"confirmation_gate": {
  "mode": "auto_allow",
  "unenforced_confirm_tools": ["clear_trajectories", "execute_python"],
  "unreachable_confirm_tools": ["fetch_trace", "probe_service_health", "read_config_snapshot"],
  "warning": "CONFIRM 级工具当前自动放行（未注入 HITL）：…"
}
```

**处置选项**：

| 选项 | 效果 | 代价 |
|------|------|------|
| 接受现状 | 无 | `default` 应用的 `execute_python` 无人工把关 |
| `REACT_AGENT_STRICT_CONFIRM=1` | 未注入 HITL 时**拒绝** `CONFIRM`（失败关闭） | 会一并禁掉 `execute_python`，`default` 应用失去代码执行能力 |
| 注入 HITL（`set_hitl(...)`） | 真正询问 | 需要客户端交互通道；建议按"异步审批"实现（见 `CORE_ARCHITECTURE.md`） |

### 异步人工审批（推荐启用）

`safety/human_in_the_loop.py` 的交互式审批要求通道在中途来回，而 HTTP 请求无法挂着等人几分钟。因此审批被建模为**状态**而非消息——这也是**不需要 WebSocket** 的原因：

```
Agent 命中 CONFIRM
  → 待批项落盘 + 本次 run 返回 status=awaiting_approval（含 approval_id）
  ↓（人可以几分钟后再来）
客户端独立 HTTP 请求决定 → 带 approval_id 重试 → 放行
```

启用：`REACT_AGENT_APPROVAL_MODE=async`

| 接口 | 说明 |
|------|------|
| `GET /v1/approvals` | 列出未决待批项（含 tool / arguments / expires_at） |
| `POST /v1/approvals/{approval_id}` | `{"decision":"approve"\|"deny", "scope":"once"\|"session"}` |

响应中 `status: awaiting_approval` 与 `approval_id` 是待审批的显式信号；SSE 通道还会发 `approval_required` 事件。

**授权范围**：`once` 用一次即作废（防重放）；`session` 在有效期内对同类工具可重复使用。

**失败关闭**：待批项写不下（目录不可写）时，闸门返回 `approval_store_unavailable` 并**拒绝执行**，绝不会退化为放行。

三种闸门模式对比（`/ready` 的 `confirmation_gate.mode`）：

| 模式 | 触发 | `CONFIRM` 行为 |
|------|------|----------------|
| `async` | `REACT_AGENT_APPROVAL_MODE=async` | **落盘待批 + 阻塞**，人工批准后放行 |
| `hitl` | 代码注入 `set_hitl(...)` | 交互式询问（需真人在同一通道） |
| `strict_deny` | `REACT_AGENT_STRICT_CONFIRM=1` | **直接拒绝** |
| `auto_allow` | 默认 | **自动放行**（无人把关，会打印告警） |

### Host 校验三档

**`loopback`（默认，推荐）** — 只放行本地形态（`127.0.0.1`、`localhost`、`::1`）与绑定地址；同时接受 `REACT_AGENT_ALLOWED_HOSTS` 中显式声明的域名。绑定 `0.0.0.0` 时同样生效，直连 IP 可用、外部域名一律 `421`。

```bash
# 反代/自定义域名：只声明真实访问用的主机名
REACT_AGENT_ALLOWED_HOSTS=agent.example.com \
REACT_AGENT_AUTH_TOKEN=$(openssl rand -hex 32) \
react-agent-server --host 0.0.0.0 --port 8765
```

**`allowlist`（严格）** — 开启后未声明 `REACT_AGENT_ALLOWED_HOSTS` 即**拒绝启动**（`exit 2`），与 `REACT_AGENT_SANDBOX_REQUIRED=1` 的失败语义一致。适合 CI/生产清单强制校验，避免「以为配了其实没配」。

```bash
REACT_AGENT_REQUIRE_HOST_ALLOWLIST=1 \
REACT_AGENT_ALLOWED_HOSTS=agent.example.com \
react-agent-server --host 0.0.0.0
# 未声明 ALLOWED_HOSTS 时输出: [server] FATAL: ... 并以 exit code 2 退出
```

**`permissive`（应急逃生口）** — `REACT_AGENT_HOST_VALIDATION=permissive` 关闭 Host 校验。仅在确认网络层已隔离时临时使用。

### 生产检查清单

- [ ] `REACT_AGENT_AUTH_TOKEN` 已设置（32 字节以上随机值），并由上游网关注入
- [ ] 绑定非回环时 `REACT_AGENT_ALLOWED_HOSTS` 已声明真实主机名
- [ ] 建议同时开启 `REACT_AGENT_REQUIRE_HOST_ALLOWLIST=1`，让漏配在启动期就失败
- [ ] 容器端口映射限制到 `127.0.0.1:8765:8765`，对外只经反代
- [ ] 如需强隔离工具执行：另行设置 `REACT_AGENT_SANDBOX_REQUIRED=1` + `REACT_AGENT_SANDBOX_BACKEND=container`（见 `SANDBOX_SECURITY.md`）

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
