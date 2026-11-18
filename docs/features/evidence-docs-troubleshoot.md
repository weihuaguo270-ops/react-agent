# 个人知识库（`docs_troubleshoot` · 可演示原型）

> **仓库应用方向**见 [`APPLICATION_DIRECTION.md`](APPLICATION_DIRECTION.md)。
> 本页描述员工个人知识沉淀与取回这条线现在能做什么、成熟度边界，以及后续目标。评测命令见 [`DOCS_TROUBLESHOOT_EVAL.md`](DOCS_TROUBLESHOOT_EVAL.md)。

## 当前主路径

本地文件加入调用 `POST /v1/docs/personal/ingest`；页面对话调用 `POST /v1/docs/personal/chat`（默认走与 Agent 底座相同的 `llm_config` / `LLM_PROVIDER` + `react_loop`，不另开开关）。

页面确认身份后进入三分区工作区：左栏文档库（仅本地文件加入）、中间正文（未选中留空但不隐藏）、右侧对话（链接/粘贴/要求/联网生成）。未接入模型时明确提示，不会用离线脚本冒充 Agent；仍可在左侧加入本地文件。

基本单位是**文档**（原文、摘要，或 Agent 生成的文稿）。Agent 可寒暄、整理、按链接或正文入库、改写摘要、就个人库提问，也可检索网上信息并生成文档；用户确认保存后写入个人库（不保存到用户本机路径）。提问有依据应带引用，证据不足拒答「个人库中没有足够依据」，不回退内置 14 篇语料。

当前是个人沉淀，不是企业制度库。代码 / 评测标识可暂时保留 `docs_troubleshoot`。界面设计见 [`personal-kb-ui-design.md`](../personal-kb-ui-design.md)。

完整演示路径：

1. `python -m react_agent.server --host 127.0.0.1 --port 8765`（或 `react-agent-api`）
2. 打开 `/` 或 `/ui`：确认 `X-Actor-Id` 后进入三分区工作区
3. 左栏加入本地文件；右栏对话（模型已配置即可）；打开文档后对话携带当前文档上下文
4. Agent 对话：`POST /v1/docs/personal/chat`；工具含写入/更新/列表/检索个人文档，以及受控联网检索与保存生成文稿
5. 本地文件：`POST /v1/docs/personal/ingest`；列表/正文：`GET/POST /v1/docs/personal/documents`
6. 评测/兼容提问仍可用 `POST /v1/chat` + `docs_sources=personal`

成熟度：**可演示原型，非生产。** 无可用模型时仍可加入本地文档，但不假装灵活对话。CI 离线测试显式 `REACT_AGENT_SERVER_LLM=0`。

### 本轮已实现的最小约束

| 能力 | 说明 |
|------|------|
| 加入资料 | 左栏本地文件 `/ingest`；链接/粘贴/生成在右栏 Agent（`/chat` + 共享 LLM） |
| 文档 | 每条含 title / body / summary / url 或 filename |
| 编辑 | `POST`/`PATCH /v1/docs/personal/documents/{id}`：字段保存，或按要求重写摘要 |
| 合并 | 同一 URL 再次处理合并到原文档 |
| 联网生成 | Agent 检索并生成文稿，确认后写入个人库（不做本机路径保存） |
| 提问 | 只查个人库；`document_id` 可聚焦当前阅读文档 |
| 隔离 | 按 actor 隔离 |
| 抓取边界 | 仅 `http/https`；拒绝 `file://`、localhost、私网 |
| 持久化 | 仓库外 runtime（`REACT_AGENT_PERSONAL_KB_DIR`） |
| 检索 | 标题 / 摘要 / 正文 / URL / 文件名；无 ES/OpenSearch |
| 拒答 | 库空或无命中时明确拒答，**不**回退内置 14 篇语料 |

内置 14 篇语料与 `git_docs` 等评测语料继续服务既有契约评测；它们不是页面默认回答库。评测默认 `docs_sources=corpus`（或未指定）保持不变。

## 后续目标：来源范围、安全合规、权限控制

本轮**未做**，只记目标：

- 按身份控制可见来源范围（职级 / 部门矩阵）
- 企业安全合规与来源审计
- 细粒度权限矩阵与审批、团队共享
- 转人工、真实邮件或 IM 通知
- 保存到用户指定的本地文件系统路径

本轮唯一与权限相关的实现是：`X-Actor-Id`（或等价 actor）隔离个人库。

## 评测与工程证据

| 入口 | 作用 |
|------|------|
| golden / fault / production / git_docs | 既有契约与回归；默认走内置或指定语料，与个人库 UI 路径分离 |
| `tests/apps/docs_troubleshoot/test_personal_kb.py` | 文档生成、编辑、同 URL/关键词合并、PDF/文件入库、检索、隔离、拒答、非法 URL（离线） |

跨仓发布门槛「3 个项目、30 条真实任务、10 条独立 held-out」已于 2026-11-16 放弃。现有评测入口仍是工程原型证据，不写成生产成熟度。

## 相关文档

- 应用方向：[`APPLICATION_DIRECTION.md`](APPLICATION_DIRECTION.md)
- 黄金集评测：[`DOCS_TROUBLESHOOT_EVAL.md`](DOCS_TROUBLESHOOT_EVAL.md)
- 成熟度矩阵：[`PRODUCTION_MATURITY.md`](PRODUCTION_MATURITY.md)
