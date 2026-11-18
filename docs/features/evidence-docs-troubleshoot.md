# 个人知识库（`docs_troubleshoot` · 可演示原型）

> **仓库应用方向**见 [`APPLICATION_DIRECTION.md`](APPLICATION_DIRECTION.md)。
> 本页描述员工个人知识沉淀与取回这条线现在能做什么、成熟度边界，以及后续目标。评测命令见 [`DOCS_TROUBLESHOOT_EVAL.md`](DOCS_TROUBLESHOOT_EVAL.md)。

## 当前主路径

投递资料调用 `POST /v1/docs/personal/ingest`（直接入库）；页面对话调用 `POST /v1/docs/personal/chat`（需 `REACT_AGENT_SERVER_LLM=1`）。

页面确认身份后进入「收藏库 + Agent」工作区：左侧浏览/编辑收藏与可选快速投递；右侧对话接入通用 `react_loop` + LLM 与个人库工具。未开模型时明确提示无法灵活对话，不会用离线脚本冒充 Agent。

Agent 可寒暄、讨论整理、写入/合并收藏、按要求改写，并就个人库提问；有依据应展示标题/关键词/摘要或引用，证据不足拒答「个人库中没有足够依据」，不回退内置 14 篇语料。

**主体验是收藏条目，不是切段列表。** 当前是个人沉淀，不是企业制度库。代码 / 评测标识可暂时保留 `docs_troubleshoot`。

完整演示路径：

1. `python -m react_agent.server --host 127.0.0.1 --port 8765`（或 `react-agent-api`）
2. 打开 `/` 或 `/ui`：先在「身份」视图填写并确认 `X-Actor-Id`（未确认不能进功能）
3. 进入工作区：左侧「我的收藏」+ 右侧知识库助手对话（非三入口硬门禁）
4. Agent 对话：`POST /v1/docs/personal/chat`（`REACT_AGENT_SERVER_LLM=1`）；工具含写入/更新/列表/检索个人收藏
5. 快速投递后备：`POST /v1/docs/personal/ingest`；列表编辑：`GET/POST /v1/docs/personal/bookmarks`
6. 评测/兼容提问仍可用 `POST /v1/chat` + `docs_sources=personal`

成熟度：**可演示原型，非生产。** 无可用模型时仍给出可编辑草稿（标题候选 + 首段摘要），不静默丢内容。

### 本轮已实现的最小约束

| 能力 | 说明 |
|------|------|
| 投递 | 工作区 Agent（`/v1/docs/personal/chat` + LLM）或直接 `/ingest`（无 url/text 时拒绝空入库） |
| 收藏 | 每条含 title / summary / keywords / url；无模型时用离线草稿生成器 |
| 编辑 | `POST`/`PATCH /v1/docs/personal/bookmarks/{id}`：字段保存，或 `requirement`/`message` 按要求重写当前条 |
| 合并 | 同一 URL 再次投递合并到原条目；关键词 Jaccard≥0.5 且交集≥2 时合并（无复杂聚类） |
| 提问 | `POST /v1/chat` + `docs_sources=personal` + `X-Actor-Id` |
| 隔离 | 入库与检索按 actor 隔离；A 的收藏不能被 B 查到 |
| 抓取边界 | 仅 `http/https`；拒绝 `file://`、localhost、私网；限超时与正文大小 |
| 持久化 | 仓库外 runtime（可用 `REACT_AGENT_PERSONAL_KB_DIR`）；重启后仍在 |
| 检索 | 优先关键词 / URL / 标题 / 摘要；不引入 ES/OpenSearch |
| 拒答 | 库空或无命中时明确拒答，**不**回退内置 14 篇语料 |

内置 14 篇语料与 `git_docs` 等评测语料继续服务既有契约评测；它们不是页面默认回答库。评测默认 `docs_sources=corpus`（或未指定）保持不变。

## 后续目标：来源范围、安全合规、权限控制

本轮**未做**，只记目标：

- 按身份控制可见来源范围（职级 / 部门矩阵）
- 企业安全合规与来源审计
- 细粒度权限矩阵与审批、团队共享
- 转人工、真实邮件或 IM 通知

本轮唯一与权限相关的实现是：`X-Actor-Id`（或等价 actor）隔离个人库。

## 评测与工程证据

| 入口 | 作用 |
|------|------|
| golden / fault / production / git_docs | 既有契约与回归；默认走内置或指定语料，与个人库 UI 路径分离 |
| `tests/apps/docs_troubleshoot/test_personal_kb.py` | 收藏生成、编辑、同 URL/关键词合并、检索、隔离、拒答、非法 URL（离线） |

跨仓发布门槛「3 个项目、30 条真实任务、10 条独立 held-out」已于 2026-11-16 放弃。现有评测入口仍是工程原型证据，不写成生产成熟度。

## 相关文档

- 应用方向：[`APPLICATION_DIRECTION.md`](APPLICATION_DIRECTION.md)
- 黄金集评测：[`DOCS_TROUBLESHOOT_EVAL.md`](DOCS_TROUBLESHOOT_EVAL.md)
- 成熟度矩阵：[`PRODUCTION_MATURITY.md`](PRODUCTION_MATURITY.md)
