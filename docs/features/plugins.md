# 插件系统

以下模块可运行、可测试，**默认不注册进 Core 工具表**，与主场景 Workflow 路径隔离。这些是可选的插件功能，按需启用。

## 启用方式

### 方式 1: 启用所有插件（简单）
```bash
# Windows
set REACT_AGENT_PLUGINS=1

# Linux/Mac
export REACT_AGENT_PLUGINS=1
```

### 方式 2: 选择性启用（推荐）
```bash
# 只启用特定插件
set REACT_AGENT_PLUGINS=rag,mcp,orchestration

# 或使用旧的单独配置
set REACT_AGENT_RAG_MODE=keyword
set REACT_AGENT_MCP_MOCK=1
```

## 可用插件

| 插件 | 模块 | 说明 | 依赖 |
|------|------|------|------|
| **rag** | `rag.py` | 检索增强生成 | 可选 `[rag]` for semantic mode |
| **mcp** | `mcp_client.py`, `mcp_config.py` | Model Context Protocol 集成 | 无 |
| **orchestration** | `orchestrator.py`, `planner.py` | 多 Agent 编排 | 无 |
| **tot** | `tot.py` | Tree of Thought 推理 | 无 |
| **dashboard** | `dashboard/` | Web UI 可视化 | 无 |

## 插件详情

### 1. RAG 插件 (检索增强生成)

**功能**: 文档检索和语义搜索

**配置**:
```bash
# 启用 RAG
set REACT_AGENT_PLUGINS=rag

# 选择检索模式
set REACT_AGENT_RAG_MODE=keyword    # 关键词（默认，无需额外依赖）
set REACT_AGENT_RAG_MODE=semantic   # 语义（需要 pip install -e ".[rag]"）
```

**示例**:
```bash
python demos/demo_rag.py
```

**使用**:
```python
from react_agent.rag import search_docs

results = search_docs("如何处理 401 错误？", mode="keyword")
```

### 2. MCP 插件 (Model Context Protocol)

**功能**: 与外部工具通过 MCP 协议集成

**配置**:
```bash
# 启用 MCP
set REACT_AGENT_PLUGINS=mcp

# Mock 模式（测试用）
set REACT_AGENT_MCP_MOCK=1

# 禁用 MCP（评测时）
set DISABLE_MCP=1
```

**示例**:
```bash
python demos/demo_mcp_mock.py
python -m react_agent --mcp "your query"
```

**使用**:
```python
from react_agent.mcp_client import MockMCPClient

client = MockMCPClient()
client.connect()
tools = client.discover_tools()
```

### 3. Orchestration 插件 (多 Agent 编排)

**功能**: Orchestrator-Worker 模式，任务分解与并行执行

**特性**:
- ✅ 声明式工具作用域（`ToolScope`）
- ✅ 写集冲突检测（默认开启）
- ✅ 委派深度限制（默认最多 1 层）
- ✅ 并发上限控制（默认 4 个并发）
- ✅ 支持 `context: fork` 摘要式上下文

**配置**:
```bash
# 启用 Orchestration
set REACT_AGENT_PLUGINS=orchestration

# 配置选项
set REACT_AGENT_SUBAGENT_MAX_DEPTH=1           # 委派深度
set REACT_AGENT_SUBAGENT_MAX_CONCURRENCY=4    # 并发上限
set REACT_AGENT_WRITE_CONFLICT_SERIALIZE=1    # 写冲突检测
set REACT_AGENT_SCOPE_STRICT=0                # 工具作用域严格模式
set REACT_AGENT_WORKER_MEMORY_WRITE=0         # Worker 记忆回写
```

**示例**:
```bash
python -m react_agent --parallel "搜索今天的汇率，并且算一下 100 美元换成人民币"
```

**使用**:
```python
from react_agent.orchestrator import multi_agent_chain

result = multi_agent_chain(
    "搜索今天的汇率，并且算一下 100 美元换成人民币",
    parallel=True
)
```

**⚠️ 重要限制**:
- **无工作区隔离**: 并行 Worker 共享同一进程与工作目录
- **写冲突**: 同时修改同一文件仍会互相覆盖
- **安全依赖**: 当前通过「写集声明 + 冲突分层」调度约定保证安全，不是隔离机制
- **适用场景**: 读密集任务（检索、审查、日志分析）；写密集任务必须声明写集

### 4. ToT 插件 (Tree of Thought)

**功能**: 树状思考推理工具（教学用途）

**配置**:
```bash
set REACT_AGENT_PLUGINS=tot
```

**使用**: 探索性推理路径

### 5. Dashboard 插件 (可视化面板)

**功能**: 本地 Web UI 可视化界面

**配置**:
```bash
set REACT_AGENT_PLUGINS=dashboard
```

**启动**:
```bash
python -m react_agent.dashboard.server
```

## 插件设计原则

### 为什么设计为插件？

1. **按需加载** - 保持核心运行时轻量，`import react_agent.react_loop` 不会拉起插件（懒加载）
2. **可选依赖** - RAG 语义模式需要额外的机器学习库，不强制所有用户安装
3. **性能优化** - 减少启动时间（实测：懒加载后从 2.46s 降到 1.32s）
4. **隔离演进** - 插件可以独立演进，不影响核心功能
5. **清晰边界** - 明确区分核心路径和扩展能力

### 插件与核心的区别

| 维度 | 核心功能 | 插件功能 |
|------|----------|----------|
| **加载** | 自动注册 | 按需启用 |
| **依赖** | 标准库 + LLM API | 可能需要额外依赖 |
| **稳定性** | 生产就绪 | 持续演进 |
| **测试** | 始终执行 | 可独立测试 |
| **评测** | 纳入主评测 | 可选评测 |

### 技术细节

- `tool_scope.py` / `write_sets.py` 放在包顶层（而非 `tools/` 内）是刻意的：它们是核心路径模块，导入时不得触发 `tools` 包的 app/workflow/plugin 装配
- `import react_agent.react_loop` 不应拉起 MCP / Orchestrator / RAG（见 `tests/test_core_lazy_imports.py`）
- RAG 现已改为按需导入，避免模块级装配

## 向后兼容

旧的环境变量仍然有效（过渡期保留 6-12 个月）：

```bash
# 旧名称（已弃用，但仍然有效）
REACT_AGENT_EXPERIMENTAL_TOOLS=1

# 新名称（推荐）
REACT_AGENT_PLUGINS=1
```

代码会在检测到旧变量时输出 deprecation 警告。

## 相关文档

- **工作流**: [`AGENT_WORKFLOW.md`](AGENT_WORKFLOW.md)
- **核心架构**: [`CORE_ARCHITECTURE.md`](CORE_ARCHITECTURE.md) - Multi-Agent 能力边界
- **评测**: [`EVAL_INDEX.md`](EVAL_INDEX.md)
- **证据地图**: [`P0_EVIDENCE_MAP.md`](P0_EVIDENCE_MAP.md)

## 插件开发指南

如果你想开发新插件，请遵循以下原则：

1. **懒加载**: 不要在模块级执行重量级初始化
2. **可选依赖**: 将特殊依赖放入 `pyproject.toml` 的 optional-dependencies
3. **独立测试**: 在 `tests/plugins/` 下创建测试
4. **文档完善**: 在本文档添加插件说明
5. **开关控制**: 通过 `REACT_AGENT_PLUGINS` 控制启用

## 常见问题

### Q: 插件功能稳定吗？可以用于生产环境吗？

A: 大部分插件（如 RAG、Orchestration）已经相当成熟，可以用于生产。"插件"只是表示它们是可选的，不是核心必需的，并不意味着不稳定。具体稳定性请参考各插件的说明。

### Q: 为什么不把所有功能都放入核心？

A: 保持核心轻量、快速启动，让用户只加载需要的功能。这遵循"最小核心 + 按需扩展"的设计原则。

### Q: 可以同时启用多个插件吗？

A: 可以。使用 `REACT_AGENT_PLUGINS=rag,mcp,orchestration` 或直接设置 `REACT_AGENT_PLUGINS=1` 启用所有插件。

### Q: 插件之间会冲突吗？

A: 不会。插件设计为相互独立，可以同时使用。
