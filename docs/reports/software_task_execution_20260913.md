# FastAPI 软件任务执行报告（2026-09-13 / 09-14 修订）

## 严格验收结论

```text
Agent 修复成功率 = 3 / 3 = 100%
（仅统计具备独立 *-agent.json 且公开+隐藏均通过、unauthorized_paths=[] 的任务）
```

此前“三条任务均达到公开 + 隐藏通过”的表述过宽：当时 15764 仅有参考补丁、15974 缺独立 Agent JSON。本修订已补齐独立 Agent 产物后，才计算成功率。

## 范围

| # | task_id | Issue | allowed_paths |
|---|---------|-------|---------------|
| 1 | `fastapi-15764-apiroute-tags` | [#15764](https://github.com/fastapi/fastapi/issues/15764) | `fastapi/routing.py` |
| 2 | `fastapi-15974-router-cache-race` | [#15974](https://github.com/fastapi/fastapi/issues/15974) | `fastapi/routing.py` |
| 3 | `fastapi-16253-docs-template-xss` | [#16253](https://github.com/fastapi/fastapi/issues/16253) | `fastapi/openapi/docs.py` |

清单状态：`active`，任务数 **3**（见 `eval/software_task_dataset_manifest.json` 与 `docs/SOFTWARE_TASK_DATASET.md`）。

## Agent 结果 vs 参考补丁结果（必须分开读）

| 任务 | baseline | Agent 补丁 | 参考补丁 | Agent 公开 / 隐藏 | 越权 | Agent JSON |
|------|----------|------------|----------|-------------------|------|------------|
| 15764 | 公开过、隐藏失败 | **succeeded** | succeeded（#15765 / `b78c8226`） | 3 / 1 | `[]` | `runs/fastapi-15764-agent.json` |
| 15974 | 公开过、隐藏 3 失败 | **succeeded** | succeeded（锁+本地列表发布） | 3 / 3 | `[]` | `runs/fastapi-15974-agent.json` |
| 16253 | 公开 1 失败（短路） | **succeeded** | succeeded（#16255 / `48b642ea`） | 4 / 4 | `[]` | `runs/fastapi-16253-agent.json` |

参考补丁 JSON：`fastapi-*-reference.json`（15764 旧文件 `fastapi-15764-candidate.json` 为早期参考评测别名，不再当作 Agent 证据）。

## 任务明细

### 1. fastapi-15764-apiroute-tags

- **Agent 补丁**：仅在 `APIRoute` 上增加 `tags: list[str | Enum]`（issue 范围最小修复），与上游完整属性注解参考补丁不同。
- **参考补丁**：上游 #15765，为 `APIRoute` 补齐一整组类属性注解。
- **重试**：Agent 单轮通过，无 Docker 重试。
- **产物**：`patches/fastapi-15764/{agent,reference}.patch`；`runs/fastapi-15764-{baseline,agent,reference,summary}.json`。

### 2. fastapi-15974-router-cache-race

- **Agent 补丁**：为 `_IncludedRouter` 增加 `_rebuild_lock`，双重检查后构建本地列表再原子发布（与参考语义相同，独立落盘）。
- **参考补丁**：同逻辑的验收/上游修复版本。
- **重试**：Agent 单轮通过；此前缺 JSON 的问题已用本轮 Runner 重跑补齐。
- **产物**：`patches/fastapi-15974/{agent,reference}.patch`；`runs/fastapi-15974-{baseline,agent,reference,summary}.json`。

### 3. fastapi-16253-docs-template-xss

- **Agent 补丁**：`html.escape` + `_html_safe_js_string`；第 1 轮漏掉 ReDoc `title`，修正后第 2 轮通过。
- **参考补丁**：PR #16255。
- **产物**：`patches/fastapi-16253/`；`runs/fastapi-16253-{baseline,agent,reference,summary,attempts}.json`。

## Agent 成功率计算

```text
成功定义：存在独立 *-agent.json，且
  status == succeeded
  && public_test.status == passed
  && hidden_test.status == passed
  && unauthorized_paths == []
  && changed_paths ⊆ allowed_paths

成功任务：15764, 15974, 16253
Agent 修复成功率 = 3 / 3 = 100%
```

证据索引：`artifacts/software-tasks/runs/agent_success_rate_20260914.json`。

## 环境与 Runner 配置

1. **已修**：`task_manifest` 公开测试资产路径按 `fastapi-XXXX` 短目录解析（此前用完整 `task_id` 导致 16253 XSS 公开用例未挂载）。
2. **仍在**：本地 `review/` 部分浅克隆不可再 clone；评测改用 GitHub 浅拉 `base_commit`。
3. **短路**：公开失败不跑隐藏（16253 baseline 已验证）。
4. **Docker**：镜像 `react-agent-review-fastapi-15764:20260912e`，`network=none`。

## 验收对照（修订后）

| 验收项 | 结论 |
|--------|------|
| 清单含 base_commit / 测试 / 隐藏资产 / 允许路径 | 通过 |
| Docker 隔离执行 | 通过 |
| 公开与隐藏均通过（Agent） | 通过（3/3） |
| Agent 与参考补丁分离 | 通过 |
| 公开失败不跑隐藏 | 通过 |
| 修改路径受限且有 `unauthorized_paths` | 通过（三条 Agent JSON 均为 `[]`） |
| 每次执行有可审计 JSON | 通过（含 15974） |
| 真实 Agent 成功率可计算 | 通过（3/3） |
| 文档与现状一致 | 通过（`SOFTWARE_TASK_DATASET.md` 已改为 active / 3 任务） |
