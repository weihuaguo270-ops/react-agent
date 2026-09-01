# 业务 Skill 与 Workflow 边界

## 目标

业务 Skill 用于缩小模型和运行时的决策空间；Workflow、Policy 和 Verifier
继续负责必须确定执行的步骤。当前实现不是把 Workflow 改写成一段 Prompt，而是：

```text
业务请求
  -> 确定性 Skill 路由
  -> 场景 instructions + allowed_tools
  -> 现有 Workflow / 规则引擎 / 受控交付器
  -> required_outputs + release_checks
  -> 返回、拒答、等待审批或失败关闭
```

实现位于 `src/react_agent/skills/`。

Skill 上下文采用 progressive disclosure：`GET /v1/skills` 或 `list_business_skills`
只返回摘要；模型明确请求 `get_business_skill_context`，或调用
`GET /v1/skills/{name}?level=instructions|full` 后，才展开指令、工具白名单和 Schema。
这样不会把所有业务规则一次性塞入上下文，减少无关指令和工具选择噪声。

## 场景拆分

| Skill | 场景 | 执行底座 | 风险 | Agent 可直接调用 |
|---|---|---|---|---|
| `docs_troubleshoot` | 技术支持/工单排障 | `docs_troubleshoot@5` Workflow | 只读 | 是 |
| `expense_claim_review` | 报销规则裁决 | `expense_rule_engine@1` | 只读 | 是 |
| `github_delivery` | 软件工程交付 | `GitHubDeliveryWorkflow` | 外部写入 | 否 |

### 文档排障

Skill 约束证据解析、文档/API 检索、诊断组织和拒答条件；固定 Workflow
继续强制 `policy`、引用验证、结构化 diagnosis 和 final。模型不能通过声称“已经验证”
绕过 `enforce_answer_policy`。

### 报销审批

Skill 负责声明输入和输出契约，最终决策仍来自确定性 `decide()` 规则。
当前 Agent 可调用的是只读 review，不直接写入 `ExpenseLedger`；需要持久化时仍必须使用
带幂等键的 `decide_claim()`。

输入和输出会经过依赖零的 JSON Schema 子集校验：递归检查 object/array/string/number/boolean
类型、required、enum、长度、范围、数组元素和额外字段。Schema 失败会返回
`input_schema` 或 `output_schema` 检查失败，而不是继续执行后续 Workflow。

### GitHub 交付

Skill 封装现有隔离克隆、精确修改、allowlist 测试、计划哈希审批、候选提交和 Draft PR
流程。它标记为 `external_write` 且 `agent_callable=False`，因此不会进入模型可调用工具面。
显式调用仍受 `shadow/guarded` 和 `Approval` 校验约束。

## 调用示例

确定性路由只返回场景，不调用 LLM：

```python
from react_agent.skills import route_skill

skill = route_skill("API 401 怎么排障")
assert skill.name == "docs_troubleshoot"
```

执行只读 Skill：

```python
from react_agent.skills import run_skill

result = run_skill(
    "expense_claim_review",
    {
        "claim": {
            "category": "交通",
            "amount": 80,
            "has_receipt": False,
        }
    },
)
assert result.ok
assert result.output["decision"] == "reject_no_receipt"
```

显式执行 GitHub shadow Skill：

```python
result = run_skill(
    "github_delivery",
    {
        "task_id": "issue-17",
        "repository": "/path/to/repo",
        "issue_url": "local://issues/17",
        "split": "dev",
        "replacements": [
            {"path": "service.py", "old": "VALUE = 1", "new": "VALUE = 2"}
        ],
        "test_command": ["python", "-m", "pytest", "-q"],
        "acceptance_criteria": ["tests pass"],
        "artifact_dir": "/path/to/artifacts",
        "idempotency_key": "issue-17-shadow",
        "mode": "shadow",
    },
)
```

## 确定性边界

Skill 提高的是场景选择、工具集合、操作顺序和输出形状的一致性。以下能力仍不能由
Skill 文本保证：

- 工具是否实际执行；
- 引用是否真实存在；
- 写操作是否获得授权；
- 同一任务是否重复提交；
- 最终业务状态是否满足验收条件。

这些约束分别由 WorkflowRunner、Policy、ToolGuard、幂等台账、审批哈希和业务 Verifier
执行。任何 release check 失败时，`SkillResult.ok` 为 `False`，并保留具体检查结果。

## Skill 组合与 API

`run_skill_pipeline([...], payload)` 支持已验证 Skill 的顺序组合。前一 Skill 的输出会进入
下一 Skill 的输入，任一步失败立即停止并记录 `failed_at`；组合不会绕过单个 Skill 的
Schema、Policy 或 Verifier。

标准库服务和 FastAPI 服务都提供：

```text
GET  /v1/skills                         # 摘要发现
GET  /v1/skills/{name}?level=full       # 按需加载契约
POST /v1/skills/route                   # 返回 skill、分数、置信度和候选
POST /v1/skills/run                     # 只执行 read_only Skill
```

`/v1/skills/run` 会拒绝 `business_write` 和 `external_write` Skill。GitHub 交付必须由
显式受控调用方启动，不能因为暴露了统一 API 而跳过审批和外部写入边界。

## 生命周期

每个 Skill 带 `version`、`status`、`owner` 和可选 `supersedes` 字段。当前状态只有
`active`、`experimental`、`deprecated`；弃用 Skill 必须声明替代项。这个轻量生命周期
适合当前单仓、少量业务 Skill 的规模，尚未引入独立 Skill 注册中心、租户发布和灰度平台。
