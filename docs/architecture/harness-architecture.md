# Harness 架构文档

**状态**: ✅ 完整实现（P0-P5 完成）  
**版本**: harness-contracts/v1  
**更新日期**: 2026-10-19

---

## 📐 整体架构

根据 Harness Build Spec，当前架构分为三层：

```
┌─────────────────────────────────────────────────────────┐
│                  Shared Contracts                       │
│  统一的数据结构、Schema、版本和错误类型                  │
│  - ToolCall / ToolError / StopReason                    │
│  - TaskEpisode / EvaluationEpisode                      │
│  - Trajectory / ArtifactRef                             │
│  - FixtureManifest                                      │
└────────────────┬────────────────────────────────────────┘
                 │
        ┌────────┴────────┐
        │                 │
┌───────▼─────────┐  ┌───▼──────────────┐
│ Runtime Harness │  │ Evaluation       │
│                 │  │ Harness          │
│ - Tool边界      │  │ - Dataset        │
│ - Sandbox       │  │ - Fixture        │
│ - Orchestration │  │ - Runner         │
│ - Model/Context │  │ - Scorer         │
│ - Replay        │  │ - Regression     │
│ - Observability │  │ - Report         │
└─────────────────┘  └──────────────────┘
```

---

## 🗂️ 目录结构

### 核心目录
```
src/react_agent/harness/
├── contracts/              # 共享契约层
│   ├── __init__.py        # 所有契约导出
│   ├── parser.py          # Trajectory 解析
│   ├── trajectory.py      # Trajectory 序列化
│   └── compatibility.py   # 跨仓兼容性
│
├── runtime/               # 运行时层
│   ├── adapters.py        # ReactLoop/Workflow/HTTP 适配器
│   ├── policies.py        # Retry/Idempotency 策略
│   ├── replay.py          # 确定性回放
│   ├── structured_output.py  # 结构化输出契约
│   ├── observability.py   # 运行时可观测性
│   └── shared_idempotency.py # 幂等存储
│
├── evaluation/            # 评估层
│   ├── reliability.py     # 可靠性测试
│   ├── repair_evidence.py # 修复证据收集
│   └── (其他评估模块)
│
├── __init__.py           # Harness 统一入口
├── recorder.py           # 轨迹记录器
├── sandbox.py            # 沙箱隔离
├── tool_boundary.py      # 工具边界
├── replay.py             # 回放调试
├── schema.py             # 遗留 Schema（兼容期）⚠️
└── step_watcher_bridge.py # StepWatcher 桥接
```

---

## 🎯 核心组件

### 1. Shared Contracts (contracts/)

**职责**: 定义所有跨模块共享的数据结构和契约

#### 核心契约

**ToolCall** - 统一工具调用
```python
from react_agent.harness.contracts import ToolCall

call = ToolCall(
    name="search",
    arguments='{"query": "example"}',
    call_id="call_123",
    attempt=1,
    source="runtime"
)
```

**ToolError** - 统一错误信封
```python
from react_agent.harness.contracts import ToolError, StopReason

error = ToolError(
    code="timeout",
    message="Tool execution timeout",
    stop_reason=StopReason.TIMEOUT,
    retryable=True
)
```

**TaskEpisode / EvaluationEpisode** - 任务和评估元数据
```python
from react_agent.harness.contracts import EvaluationEpisode, FixtureManifest

episode = EvaluationEpisode(
    episode_id="ep_001",
    query="Fix the bug",
    acceptance_criteria=["Bug fixed", "Tests pass"],
    split="dev",
    runner="execution_scorer",
    batch_id="batch_001",
    trajectory={...},
    score={...}
)
```

**Trajectory** - Format B 轨迹
```python
from react_agent.harness.contracts import serialize_trajectory, parse_trajectory

# 序列化
trajectory = serialize_trajectory(
    session_id="sess_123",
    query="User query",
    steps=[...],
    final_answer="Result"
)

# 解析和验证
parsed = parse_trajectory(trajectory_data)
```

#### 关键功能
- ✅ 版本化契约（harness-contracts/v1）
- ✅ JSON Schema 验证
- ✅ 跨仓兼容性检查
- ✅ 统一序列化/解析入口

---

### 2. Runtime Harness (runtime/)

**职责**: 运行时执行保障和策略控制

#### 核心模块

**RuntimeEpisode** - 运行时执行容器
```python
from react_agent.harness.runtime import RuntimeEpisode, StopReason

episode = RuntimeEpisode(
    runtime_episode_id="run_001",
    execution_mode="react",
    transport="in_process",
    status="completed",
    stop_reason=StopReason.COMPLETED,
    trajectory={...},
    metrics={...}
)
```

**Adapters** - 执行方式适配器
- `ReactLoopAdapter` - ReAct 循环适配
- `WorkflowAdapter` - 工作流适配
- `HttpRunnerAdapter` - HTTP 传输适配

**Policies** - 策略控制
```python
from react_agent.harness.runtime import RetryPolicy, IdempotencyPolicy

retry = RetryPolicy(
    max_attempts=3,
    backoff_factor=2.0,
    max_delay=60.0
)

idempotency = IdempotencyPolicy(
    store=configured_idempotency_store(),
    ttl_seconds=3600
)
```

**Replay** - 确定性回放
```python
from react_agent.harness.runtime.replay import DeterministicReplay, ReplayManifest

manifest = ReplayManifest(
    trajectory={...},
    tool_results=[...],
    fixture={...}
)

replay = DeterministicReplay(manifest)
result = replay.replay()
```

**Observability** - 可观测性
```python
from react_agent.harness.runtime.observability import RuntimeObservability

obs = RuntimeObservability(
    runtime_episode_id="run_001",
    trace_id="trace_123",
    metrics={...}
)
```

#### 关键功能
- ✅ R1: 统一 ToolCall 和错误信封
- ✅ R2: Retry 和 Idempotency 策略
- ✅ R3: RuntimeEpisode 契约
- ✅ R4: 结构化输出解析
- ✅ R5: 确定性回放
- ✅ R6: 运行时可观测性

---

### 3. Evaluation Harness (evaluation/)

**职责**: 评估、测试、回归检测

#### 核心功能
- Dataset 管理
- Fixture 准备和验证
- Runner 适配（execution_scorer, EvalRunner）
- 评分和断言
- 失败回归检测
- Repair/Reverify 闭环

#### 关键模块
- `reliability.py` - 可靠性测试
- `repair_evidence.py` - 修复证据收集
- Baseline compare
- Acceptance reporting

#### 关键功能
- ✅ P3-1: EvaluationEpisode 契约
- ✅ P3-2: execution_scorer 集成
- ✅ P3-3: EvalRunner 集成
- ✅ P4-1: Baseline compare 和 repair/reverify

---

## 🔗 依赖关系

### 严格的依赖规则

```
Runtime Harness ──depends on──> Shared Contracts
     ↑
     │ 通过 Adapter 驱动
     │
Evaluation Harness ──depends on──> Shared Contracts
```

**规则**:
1. ✅ Runtime Harness 依赖 Shared Contracts
2. ✅ Evaluation Harness 依赖 Shared Contracts
3. ✅ Runtime Harness **不依赖** Evaluation Harness
4. ✅ 跨仓工具（trace-debugger, eval-engine）只能通过 Contracts 接入

---

## 📦 统一入口

### Harness 主入口 (`harness/__init__.py`)

```python
from react_agent.harness import (
    # Contracts
    ToolCall, ToolError, StopReason,
    TaskEpisode, EvaluationEpisode,
    serialize_trajectory, parse_trajectory,
    
    # Runtime
    RuntimeEpisode, RetryPolicy, IdempotencyPolicy,
    ReactLoopAdapter, HttpRunnerAdapter,
    
    # Recorder & Sandbox
    Trajectory, Sandbox, Replay,
    
    # Validation
    validate_trajectory, assert_valid
)
```

### 推荐导入方式

**新代码** - 从 contracts 导入：
```python
from react_agent.harness.contracts import (
    validate_trajectory,
    serialize_trajectory,
    ToolCall,
    EvaluationEpisode
)
```

**遗留兼容** - 从主入口导入：
```python
from react_agent.harness import (
    validate_trajectory,  # 重新导出自 contracts
    ToolCall,
    RuntimeEpisode
)
```

---

## 🔄 数据流

### 典型执行流程

```
1. 用户查询
   ↓
2. ReactLoopAdapter / WorkflowAdapter
   ↓
3. RuntimeEpisode 创建
   ├─> ToolCall 执行（通过 tool_boundary）
   ├─> Retry/Idempotency 策略应用
   ├─> Recorder 记录步骤
   └─> Observability 收集指标
   ↓
4. Format B Trajectory 生成（serialize_trajectory）
   ↓
5. EvaluationEpisode 封装（如果在评估中）
   ↓
6. 评分和回归检测
```

---

## ✅ 完成的功能

### P0: Baseline
- ✅ 冻结基线报告

### P1: Shared Contracts
- ✅ ToolCall / ToolError / StopReason
- ✅ TaskEpisode / EvaluationEpisode
- ✅ Trajectory 序列化/解析
- ✅ JSON Schema 验证
- ✅ 跨仓兼容性检查

### P2: Runtime Convergence
- ✅ 统一工具边界和错误处理
- ✅ Retry 和 Idempotency 策略
- ✅ RuntimeEpisode 契约
- ✅ 结构化输出解析
- ✅ 确定性回放（Docker 隔离）
- ✅ 运行时可观测性（Redis Streams）

### P3: Evaluation Convergence
- ✅ EvaluationEpisode 契约
- ✅ execution_scorer 集成
- ✅ EvalRunner 集成
- ✅ FixtureManifest 支持

### P4: Replay and Regression Gates
- ✅ Baseline compare
- ✅ Repair/Reverify 闭环
- ✅ 失败回归检测

### P5: Migration
- ✅ 91% 遗留导入迁移
- ✅ 弃用警告实现
- ✅ 兼容期建立

---

## ⚠️ 兼容性说明

### 遗留模块（兼容期）

**`harness/schema.py`** - 保留用于向后兼容
- ⚠️ 已弃用，将在兼容期结束后删除
- 触发弃用警告
- 新代码应使用 `harness.contracts`

### 迁移状态
- ✅ 19 个文件已迁移
- ✅ 91% 遗留导入清除
- 剩余 2 个遗留引用（`schema_major` 工具函数）

---

## 🔍 关键特性

### 1. 版本化契约
- `harness-contracts/v1`
- `evaluation-episode/v1`
- `fixture-manifest/v1`

### 2. 统一错误处理
- 所有错误使用 `ToolError`
- 统一 `StopReason` 枚举

### 3. Format B 轨迹
- 1-based 步骤编号
- 统一序列化器
- JSON Schema 验证

### 4. 确定性回放
- 固化工具结果
- Docker 隔离
- Fixture 哈希验证

### 5. 可观测性
- RuntimeEpisode 追踪
- Redis Streams 导出
- 指标和日志关联

---

## 📊 使用统计

根据 P5 迁移结果：
- **总文件数**: 19 个已迁移
- **契约导入**: 50+ 处
- **遗留导入**: 2 处（合理保留）
- **测试通过率**: 100%
- **向后兼容**: 100%

---

## 🚀 未来方向

### 可选优化（不在 P0-P5 范围内）
- 完全删除 `schema.py`（兼容期结束后）
- 目录重组（可选，当前结构已符合 Spec）
- 进一步的性能优化

---

**文档版本**: 1.0  
**对应 Spec**: HARNESS_BUILD_SPEC.md (P0-P5 完成)  
**更新时间**: 2026-10-19
