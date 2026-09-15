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

## 第一阶段：冻结业务交付边界（已实现）

边界不是一句“这个 Agent 负责什么”，而是一份可以被注册和运行时检查的契约。每个
Skill 现在同时声明六类信息：

1. **交付目的**：明确输出要解决的业务结果，例如技术支持只生成有证据的诊断，软件交付只生成经过测试、等待审批的候选变更。
2. **输入和输出**：沿用 `input_schema`、`output_schema`、`required_inputs` 和 `required_outputs`。字段缺失、类型错误或输出不完整时，Workflow 不会继续。
3. **必经步骤**：把业务流程写成顺序要求，而不是交给模型自由决定。软件交付必须经过固定提交、隔离修改、测试、范围检查和审批；技术支持必须经过证据解析、检索、引用验证和诊断组织。
4. **允许工具和禁止动作**：`allowed_tools` 限制模型可见工具；`forbidden_actions` 拒绝请求中明确出现的越界动作。真正的权限、网络写入和容器限制仍由 ToolGuard、Workflow 和 Sandbox 执行。
5. **成功条件**：定义“做完”的可检查结果，例如测试通过、无越权文件、引用存在、`executed_actions` 为空。它们对应 `release_checks` 和业务 Verifier，而不是模型自报成功。
6. **人工接管条件**：列出必须停下来交给人的情况，例如生产修复、远程写入、证据不足、规则未覆盖或需要解决代码冲突。

契约实现为 `src/react_agent/skills/business_boundaries.py` 中的
`BusinessBoundary`，并挂在现有 `SkillDef.boundary` 上。注册 Skill 时会检查边界与
Skill 的场景、Workflow、风险级别、工具、输入输出是否一致；执行前会检查显式动作和
Agent 调用资格。完整契约可通过 `GET /v1/skills/{name}?level=full` 按需加载，摘要发现
不会把全部规则注入模型上下文。

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

### 目标与当前产物

本阶段的目标是让两个主业务场景都有可审计的输入、输出、步骤、工具、禁止动作和
人工接管条件，并能在执行前拒绝明显越界请求。当前已经交付四份内置边界：
`docs_troubleshoot`、`expense_claim_review`、`security_triage` 和
`github_delivery`；同时提供 `schemas/business_boundary.schema.json`、边界注册校验、
运行时拒绝检查和 `tests/test_business_boundaries.py` 契约测试。

当前产物能证明：边界字段可被发现、可校验，Skill 与 Workflow 不会静默漂移，外部写入
Skill 不能从 Agent 工具或 `/v1/skills/run` 直接启动，明确的禁止动作会失败关闭。
它还不能证明：模型一定遵守未显式写出的意图、真实企业权限配置正确、人工审批一定及时、
技术支持能够自动确认唯一根因，或软件补丁能解决真实历史 Issue。后续仍需把
`SoftwareTask` 的隐藏测试、允许修改路径和 Docker Runner 接入 GitHub 交付主流程，
并用外部历史任务做 baseline/candidate 对比。

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
