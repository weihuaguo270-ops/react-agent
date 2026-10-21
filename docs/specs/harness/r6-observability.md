# R6 Redis Streams 部署说明

本文定义 Runtime Harness 可观测性 exporter 在项目 Compose 环境中的部署边界和
failure Stream 消费方案。它补充 R6 的验收证据，不把本地 Redis 验收提升为外部
告警服务或生产 SLA。

## 拓扑和配置

应用容器通过 Compose 网络访问项目 Redis：`redis://redis:6379/0`。宿主机验收使用
`127.0.0.1:6380`。可观测性使用独立 Stream，不复用 Redis 任务队列：

- 主 Stream：`REACT_AGENT_OBSERVABILITY_STREAM`，保存脱敏的 RuntimeEpisode artifact；
- failure Stream：`REACT_AGENT_OBSERVABILITY_FAILURE_STREAM`，保存 exporter 失败事件；
- 两个 Stream 都使用各自的 bounded `MAXLEN`，避免观测数据无限增长；
- PostgreSQL 仍是任务和幂等记录的权威存储，Redis Stream 丢失不会改变任务结果。

Compose 启用 exporter 时，在 API/Worker 服务设置：

```dotenv
REACT_AGENT_OBSERVABILITY_EXPORTER=redis
REACT_AGENT_OBSERVABILITY_REDIS_URL=redis://redis:6379/0
REACT_AGENT_OBSERVABILITY_STREAM=react-agent:observability
REACT_AGENT_OBSERVABILITY_FAILURE_STREAM=react-agent:observability:failures
REACT_AGENT_OBSERVABILITY_FAILURE_POLICY=ignore
```

`REACT_AGENT_OBSERVABILITY_FAILURE_POLICY=ignore` 保证观测系统故障不阻断 Agent
业务请求；需要在测试或强一致采集场景阻断请求时才使用 `raise`。重试次数和退避
由 `REACT_AGENT_OBSERVABILITY_RETRY_*` 控制。

## Failure Stream 消费者

部署一个独立的 failure-consumer 进程，使用专用消费组（例如
`harness-observability-alerts`）读取 failure Stream。消费者处理流程如下：

1. `XGROUP CREATE <failure-stream> harness-observability-alerts $ MKSTREAM`（幂等执行，
   已存在时忽略 BUSYGROUP）。
2. `XREADGROUP GROUP harness-observability-alerts <consumer> COUNT 100 BLOCK 5000` 读取
   新事件；事件中的 `artifact.links.runtime_episode_id` 是关联原始运行的主键。
3. 将事件发送到告警系统或持久化的 failure queue。发送成功后执行 `XACK`；发送失败
   时不 ACK，保留 pending 状态。
4. 定时使用 `XAUTOCLAIM` 回收超过 lease 的 pending 事件，并限制重试次数。超过上限
   后写入部署侧 dead-letter queue，同时触发人工告警。

failure-consumer 必须按 `event_id` 或 `runtime_episode_id + attempts` 去重，因为 Redis
Streams 是至少一次投递。告警系统的去重、抑制、保留期和通知渠道属于部署侧责任。

## 告警接线

代码层提供 `RuntimeObservability(exporter_alert=...)` 回调注入点。部署适配器应将
回调转换成结构化事件并发送到 failure-consumer 或现有告警 SDK，至少包含：

- `event_type=observability_export_failed`；
- `runtime_episode_id`、`trace_id`、`run_id`；
- `attempts`、错误摘要和 failure Stream 名称；
- 首次发生时间、最后重试时间和部署环境标识。

当前仓库没有绑定 PagerDuty、邮件、Webhook 或其他外部通知服务。R6 验收报告中的
`deployment_callback_required` 表示 Redis failure Stream 已验证，但外部通知仍需由
部署配置提供。

## 运维检查

```powershell
docker compose ps postgres redis
docker compose exec redis redis-cli XINFO STREAM react-agent:observability
docker compose exec redis redis-cli XINFO STREAM react-agent:observability:failures
```

验收脚本 `scripts/eval/smoke/run_p2_r6_redis_exporter_evidence.py` 使用项目的
`react-agent-redis-1`，验证主 Stream 写入、关联 ID、瞬时故障重试和持续故障进入
failure Stream；脚本结束会删除唯一测试 Stream。它不验证第三方告警服务的可用性。
