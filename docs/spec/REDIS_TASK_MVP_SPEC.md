# Redis 任务队列 MVP 规格说明

## 1. 文档状态

本文定义 `react-agent` 第一版基于 Redis 的异步任务 MVP。它是实现规格，不构成生产 SLA 或容量承诺。

MVP 包含四个运行角色：

```text
FastAPI -> Redis Streams -> Worker -> PostgreSQL
```

- FastAPI 接收任务请求并返回任务 ID。
- Redis Streams 负责消息投递和 Consumer Group 协调。
- Worker 在 API 进程之外执行 Agent 请求。
- PostgreSQL 持久化任务状态、结果和错误，是任务记录的权威来源。

现有的进程内内存模式继续保留，用于测试和本地开发。

## 2. 范围

### 2.1 MVP 包含

- 一个 Redis Stream 和一个 Consumer Group。
- 多个 Worker 进程消费同一个 Consumer Group。
- `react_agent_tasks` 表中的持久化任务记录。
- 任务提交、状态查询和取消 API。
- 至少一次投递语义（at-least-once delivery）。
- 按可见性超时回收长时间未确认的 pending 消息。
- 执行前和执行返回后的协作式取消。
- PostgreSQL、Redis、API、Worker 的 Docker Compose 服务。

### 2.2 MVP 不包含

- 优先级队列。
- 定时任务或延迟任务。
- 跨区域复制。
- 严格 exactly-once 执行。涉及外部副作用的任务必须自行保证幂等。
- 自动死信重放界面。
- 自动水平扩缩容策略。

## 3. 配置

```env
REACT_AGENT_TASK_STORE=postgresql
REACT_AGENT_DATABASE_URL=postgresql+psycopg://user:password@postgres:5432/learn
REACT_AGENT_QUEUE_BACKEND=redis
REACT_AGENT_REDIS_URL=redis://redis:6379/0
REACT_AGENT_QUEUE_NAME=react-agent:tasks
REACT_AGENT_QUEUE_GROUP=react-agent-workers
REACT_AGENT_QUEUE_VISIBILITY_MS=900000
REACT_AGENT_QUEUE_MAX_TASKS=10000
```

未设置 `REACT_AGENT_QUEUE_BACKEND` 或设置为 `memory` 时，继续使用现有的本地线程池路径。Redis 模式启动时要求 PostgreSQL 和 Redis 均可连接。

## 4. 任务生命周期

```text
queued -> running -> succeeded
                  -> failed
                  -> cancelled
```

1. API 在 PostgreSQL 中创建 `queued` 记录。
2. API 将 `{task_id, payload}` 写入 Redis Stream。
3. Worker 领取消息，将记录更新为 `running`。
4. Worker 执行请求。
5. Worker 保存结果或截断后的错误信息，并确认 Stream 消息。
6. 已取消的 queued 消息直接确认，不执行任务。

如果 Worker 在确认消息前退出，其他 Worker 可在 `REACT_AGENT_QUEUE_VISIBILITY_MS` 到期后重新领取并执行该消息。这是至少一次投递，因此任务处理逻辑必须能够承受重复投递。

## 5. API 契约

现有接口路径和响应形状保持不变：

- `POST /v1/tasks`：返回 `202`、`task_id` 和 `queued` 状态。
- `GET /v1/tasks/{task_id}`：从 PostgreSQL 读取持久化任务记录。
- `DELETE /v1/tasks/{task_id}`：在 Redis 写入取消标记，并在任务处于 queued 或 running 时持久化为 `cancelled`。

Redis 不可用时，提交接口返回 `503`，错误码为 `queue_unavailable`。达到配置的队列上限时，返回 `429`，错误码为 `queue_full`。

## 6. 数据归属

Redis 负责临时投递状态：

- Stream 消息。
- Consumer Group 的 pending 消息。
- 协作式取消标记。

PostgreSQL 负责持久化任务状态：

- `task_id` 和生命周期时间戳。
- 当前状态。
- JSON 任务结果。
- 截断后的错误文本。

Redis 不作为已完成任务历史记录的权威来源。

## 7. 运维要求

- API 和 Worker 必须使用相同的 Redis Stream 名称和 Consumer Group 名称。
- API、Worker、Redis、PostgreSQL 必须处于可互通的网络中。
- API 和 Worker 启动前必须通过 Redis healthcheck。
- API 和 Worker 启动前必须通过 PostgreSQL healthcheck。
- 密钥必须来自环境变量或密钥管理系统，不得提交到仓库。
- Worker 日志必须包含 `task_id`、状态变化、领取事件和错误类别，不能记录凭据或完整用户 payload。

### 7.1 Redis 持久化与一致性要求

#### 当前实现状态（2026-10-09）

现已使用当前 Compose 文件新建项目 Redis 容器 `react-agent-redis-1`。由于宿主机 `6379` 已被旧的 `learn-redis` 占用，项目 Redis 对外映射为 `127.0.0.1:6380`，项目网络内仍使用 `redis:6379`。旧 `learn-redis` 仍是独立实例，当前只有 RDB；它不属于本项目新建的 Redis 服务。

2026-10-09 已核验项目 Redis：`appendonly=yes`、`appendfsync=everysec`、`aof-use-rdb-preamble=yes`、保留 RDB `save` 规则、AOF 自动重写阈值为 `100%/64mb`，`INFO persistence` 显示 `aof_enabled:1`。重启恢复测试中写入的 key 和 Stream 数据均成功恢复；测试数据随后已清理。

Redis 使用 RDB + AOF 混合持久化，作为队列运行状态的故障恢复增强机制；它不改变 PostgreSQL 作为任务状态、结果和错误信息权威来源的定义。

- Redis 必须启用 AOF：`appendonly yes`。
- AOF 同步策略使用 `appendfsync everysec`，允许约 1 秒的极端故障数据丢失窗口；不要求使用 `always`。
- 保留 RDB 快照配置，至少覆盖默认的定期快照策略。AOF 重写应使用 RDB preamble（Redis 7 默认行为，除非项目配置明确关闭），以控制恢复时间和 AOF 文件大小。
- 启用 AOF 自动重写，并记录 `aof_rewrite` 相关配置；AOF 文件不得无限增长。
- Redis `/data` 必须挂载持久化 Docker volume。RDB/AOF 文件应有独立备份或可恢复方案，Docker volume 本身不视为灾备副本。
- 变更 RDB/AOF 配置后，必须执行一次重启恢复验证，并记录配置快照、重启前后的任务/Stream 状态和验证时间。
- 任务状态更新必须遵守本规格定义的状态机，不允许旧 Worker 用过期状态覆盖新状态；重试和重复投递必须按 `task_id` 幂等处理。
- 涉及任务状态与结果的多步写入，必须采用事务、Lua 或等价的原子/版本控制机制，避免部分更新产生不可解释状态。
- Redis 恢复后，以 PostgreSQL 任务记录为准校正任务状态；不得把 Redis 恢复出的 Stream 消息直接当作已完成任务历史。

## 8. 验收清单

- [x] `docker compose up --build` 能启动 PostgreSQL、Redis、API、Worker（本机验收使用宿主机 API 端口 `8766`，项目内部端口仍为 `8765`）。
- [x] `POST /v1/tasks` 返回 `202`，且任务不在 API 进程中执行；真实任务观察到 `queued -> running -> succeeded`。
- [x] Worker 将任务更新为 `running`，最终变为 `succeeded`；未知应用路径的失败任务也能落为 `failed`。
- [x] API 重启后，`GET /v1/tasks/{task_id}` 仍能查询任务并返回 PostgreSQL 中保存的结果。
- [x] 取消 queued 任务后，Worker 不执行该任务；验收中 `started_at` 保持为空。
- [ ] pending 消息在可见性超时后可以被其他 Worker 重新领取。
- [x] Redis 故障时返回 `503 queue_unavailable`，不能静默丢失任务。
- [x] API/Redis 故障演练后，PostgreSQL 中已保存的任务记录仍然存在。
- [x] 项目 Redis（`react-agent-redis-1`）启用 `appendonly yes`、`appendfsync everysec`，并保留 RDB `save` 规则；`redis-cli CONFIG GET` 和 `INFO persistence` 的结果已记录并符合本规格。
- [x] Redis 重启恢复验收通过：项目 Redis 的测试 key/Stream 已按预期恢复；任务查询仍以 PostgreSQL 记录为准。
- [x] AOF 自动重写配置已验证，AOF 文件可增长、重写并在重启后加载；RDB 快照文件也能生成并加载。2026-10-09 的恢复演练中，RDB 与 AOF 均恢复了 key 和 Stream。
- [x] Docker volume 之外存在可恢复的 Redis 数据备份，并完成了一次 RDB/AOF 备份恢复演练；证据目录为 `artifacts/redis-task-mvp/manual2-20261009-173227/`。
- [x] 重复投递和乱序状态更新的单元测试通过：同一 `task_id` 的终态不会被旧 Worker 覆盖；数据库故障时消息不会提前确认。
- [x] pending 消息跨真实 Redis consumer 的可见性超时回收已验证：`terminated` consumer 领取后，`replacement` consumer 在 50ms 超时后成功领取同一 message id。
- [x] 现有 memory 模式和服务回归测试继续通过；刷新 docs 语料基线后离线回归为 `579 passed, 9 deselected`。配置项目 `.env` 中的 `DEEPSEEK_API_KEY` 后，原先未执行的 9 项真实 LLM 测试已在 `REACT_AGENT_SKIP_RAG=1` 下复验通过（`9 passed`，2026-10-09）。

## 9. MVP 之后

- 增加明确的重试策略和死信存储。
- 在 PostgreSQL 中增加任务尝试次数和租约字段。
- 增加队列深度、等待时间、执行时间、重试次数和重新领取次数指标。
- 大 payload 改用独立任务表或对象存储。
- 增加任务所有权和取消权限控制。
