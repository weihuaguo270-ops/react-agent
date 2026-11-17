# 个人知识库（`docs_troubleshoot` · 可演示原型）

> **仓库应用方向**见 [`APPLICATION_DIRECTION.md`](APPLICATION_DIRECTION.md)。
> 本页描述员工个人知识沉淀与取回这条线现在能做什么、成熟度边界，以及后续目标。评测命令见 [`DOCS_TROUBLESHOOT_EVAL.md`](DOCS_TROUBLESHOOT_EVAL.md)。

## 当前主路径

员工把网页链接或一段文本交给助手（投递接口为 `POST /v1/docs/personal/ingest`）；助手清理正文、按约 500 字 / 50 字重叠切分，写入该员工自己的持久化知识库。之后员工用自然语言提问，助手**只在这份个人库**里检索，给出带引用的整理答案；证据不足或库为空时明确拒答「个人库中没有足够依据」，并提示先投递资料。

**当前是个人沉淀，不是企业制度库。** 页面标题与对外说明使用「个人知识库」；代码 / 评测标识可暂时保留 `docs_troubleshoot`。

完整演示路径：

1. `python -m react_agent.server --host 127.0.0.1 --port 8765`（或 `react-agent-api`）
2. 打开 `/` 或 `/ui`，填写 `X-Actor-Id`
3. 调用 `POST /v1/docs/personal/ingest` 投递 `https` 链接（测试走本地 fixture，不依赖外网）或粘贴文本 → 列出该身份下已沉淀来源与片段数
4. 提问 → 仅个人库关键词检索（默认）→ 引用列表与检索过程可见

成熟度：**可演示原型，非生产。** 不宣称已上线企业制度问答。

### 本轮已实现的最小约束

| 能力 | 说明 |
|------|------|
| 投递 | `POST /v1/docs/personal/ingest`：`url` 或 `text` 二选一 |
| 列表 | `GET /v1/docs/personal/sources`：当前身份下来源与片段摘要 |
| 提问 | `POST /v1/chat` + `docs_sources=personal` + `X-Actor-Id` |
| 隔离 | 入库与检索按 actor 隔离；A 的收藏不能被 B 查到 |
| 抓取边界 | 仅 `http/https`；拒绝 `file://`、localhost、私网；限超时与正文大小；只存提取文本 |
| 持久化 | 落在仓库外的 runtime 目录，进程重启后仍在。个人库落盘目录默认在 runtime data 下，可用环境变量 `REACT_AGENT_PERSONAL_KB_DIR` 覆盖。 |
| 检索 | 默认关键词；`REACT_AGENT_RAG_MODE=semantic` 可切换向量，不引入 ES/OpenSearch |
| 拒答 | 库空或无命中时明确拒答，**不**回退到内置 14 篇演示语料 |

内置 14 篇语料与 `git_docs` 等评测语料继续服务既有契约评测；它们不是页面默认回答库。评测默认 `docs_sources=corpus`（或未指定）保持不变。

## 后续目标：来源范围、安全合规、权限控制

本轮**未做**，只记目标：

- 按身份控制可见来源范围（职级 / 部门矩阵）
- 企业安全合规与来源审计
- 细粒度权限矩阵与审批
- 转人工、真实邮件或 IM 通知

本轮唯一与权限相关的实现是：`X-Actor-Id`（或等价 actor）隔离个人库。

## 评测与工程证据

| 入口 | 作用 |
|------|------|
| golden / fault / production / git_docs | 既有契约与回归；默认走内置或指定语料，与个人库 UI 路径分离 |
| `tests/apps/docs_troubleshoot/test_personal_kb.py` | 入库、隔离、拒答、非法 URL（全程离线 fixture） |

跨仓发布门槛「3 个项目、30 条真实任务、10 条独立 held-out」已于 2026-11-16 放弃。现有评测入口仍是工程原型证据，不写成生产成熟度。

## 相关文档

- 应用方向：[`APPLICATION_DIRECTION.md`](APPLICATION_DIRECTION.md)
- 黄金集评测：[`DOCS_TROUBLESHOOT_EVAL.md`](DOCS_TROUBLESHOOT_EVAL.md)
- 成熟度矩阵：[`PRODUCTION_MATURITY.md`](PRODUCTION_MATURITY.md)
