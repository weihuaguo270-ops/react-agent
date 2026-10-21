# 规格文档编写标准

## 📋 目的

定义规格文档（Spec）的**内容结构和编写标准**，确保：
1. 所有 spec 文档结构一致
2. Requirements（R 系列）有明确的描述格式
3. Phases（P 系列）有清晰的验收标准
4. 可执行、可验收、可追溯

---

## 📄 主规格文档结构（spec.md）

### 必须包含的章节

```markdown
# {Module} 规格

## 1. 文档状态

**状态：** Proposed / Approved / In Progress / Implemented / Deprecated  
**版本：** v1.0  
**最后更新：** YYYY-MM-DD  
**负责人：** [负责人或团队]

## 2. 概述

### 2.1 目标
用 1-3 句话说明这个模块要解决什么问题。

### 2.2 范围

#### 包含（In Scope）
- 明确列出做什么

#### 不包含（Out of Scope）
- 明确列出不做什么（避免范围蔓延）

### 2.3 依赖
- 依赖的其他模块
- 依赖的外部系统
- 前置条件

## 3. Requirements（功能要求）

### R1: {Requirement 名称}

**优先级：** P0 / P1 / P2  
**状态：** Proposed / In Progress / Complete  

**描述：**
清晰描述这个要求要实现什么功能。

**验收标准：**
- [ ] 可验证的标准 1
- [ ] 可验证的标准 2
- [ ] ...

**交付物：**
- 代码模块：`src/path/to/module.py`
- 测试：`tests/path/to/test.py`
- 文档：独立文档（如果复杂）或本节

**依赖：**
- 依赖 R{N}（如果有）

---

### R2: {另一个 Requirement}

（同上结构）

---

（重复 R1-RN）

## 4. Phases（实施阶段）

### Phase 0: 基线冻结

**目标：** 冻结当前状态作为起点

**交付物：**
- [ ] 基线文档：`evidence/phase0-baseline.md`
- [ ] 基线测试结果
- [ ] Git commit / tag

**验收标准：**
- [ ] 基线文档记录当前所有能力
- [ ] 所有测试通过
- [ ] 基线已提交并打 tag

**状态：** Complete / In Progress / Not Started

---

### Phase 1: {第一阶段里程碑}

**目标：** 用一句话说明这个阶段的目标

**包含的 Requirements：**
- R1: {名称}
- R2: {名称}

**交付物：**
- [ ] 实现 R1
- [ ] 实现 R2
- [ ] 集成测试通过
- [ ] 验收报告：`evidence/phase1-completion.md`

**验收标准：**
- [ ] 可执行的验收标准 1
- [ ] 可执行的验收标准 2
- [ ] 回归测试通过

**状态：** Complete / In Progress / Not Started

---

（重复 Phase 0-N）

## 5. 验收证据

### Phase 0-N 验收报告位置

- Phase 0: [`evidence/phase0-baseline.md`](evidence/phase0-baseline.md)
- Phase 1: [`evidence/phase1-completion.md`](evidence/phase1-completion.md)
- Phase 2: ...

或者，如果早期 Phase 没有独立报告：

### Phase 0-2: 隐式验收
早期 Phase 的验收证据在：
- Git commits: [commit range]
- PR: #123, #456
- Issue: #789

### Phase 3+: 显式验收
从 Phase 3 开始，每个 Phase 都有独立的验收报告。

## 6. 风险与限制（可选）

- 风险 1
- 风险 2
- 技术限制 1
- 技术限制 2

## 7. 相关文档

- [子规格 1](r1-feature.md)
- [迁移指南](migration-guide.md)
- [外部参考](https://...)
```

---

## 📋 Requirements（R 系列）编写标准

### 必须包含的内容

```markdown
### R{N}: {清晰的功能名称}

**优先级：** P0 / P1 / P2
**状态：** Proposed / In Progress / Complete / Deprecated
**负责人：** [可选]

**描述：**
用 2-5 段文字清晰描述：
1. 这个功能要解决什么问题
2. 为什么需要它
3. 如何实现（概要）

**验收标准：**
- [ ] 可执行、可验证的标准 1（例如：单元测试覆盖率 > 80%）
- [ ] 可执行、可验证的标准 2（例如：API 响应时间 < 100ms）
- [ ] ...

**交付物：**
- 代码：`src/module/feature.py`
- 测试：`tests/test_feature.py`
- 文档：[链接]（如果有独立文档）

**依赖：**
- 依赖 R{M}（如果有）
- 外部依赖（如果有）

**技术选型：**（可选）
- 技术方案
- 为什么选这个方案

**非功能需求：**（可选）
- 性能要求
- 安全要求
- 可维护性要求
```

### 简单 R vs 复杂 R

**简单 R（< 200 行）：**
- 直接在主规格中按上述格式描述

**复杂 R（> 200 行）：**
- 在主规格中写摘要（按上述格式，但描述简短）
- 创建独立文档 `r{N}-{feature}.md`，包含详细内容
- 在主规格中添加链接：`详细说明见 [r{N}-{feature}.md](r{N}-{feature}.md)`

---

## 🎯 Phases（P 系列）编写标准

### 必须包含的内容

```markdown
### Phase {N}: {里程碑名称}

**目标：**
用 1-2 句话说明这个阶段要达成什么。

**包含的 Requirements：**
- R{N}: {名称}
- R{M}: {名称}

**时间估算：**（可选）
预计 X 周

**交付物：**
- [ ] 具体交付物 1
- [ ] 具体交付物 2
- [ ] 验收报告：`evidence/phase{N}-completion.md`

**验收标准：**
- [ ] 可执行的标准 1
- [ ] 可执行的标准 2
- [ ] 回归测试通过

**状态：** Not Started / In Progress / Complete / Partial

**完成日期：** YYYY-MM-DD（完成后填写）

**遗留问题：**（如果有）
- Issue 1
- Issue 2
```

### Phase 命名规范

- **Phase 0**: 通常是 "基线冻结" / "Baseline"
- **Phase 1-N**: 按功能里程碑命名，例如：
  - Phase 1: Shared Contracts
  - Phase 2: Runtime 收敛
  - Phase 3: Evaluation 收敛
  - Phase 4: Replay 与回归门禁
  - Phase 5: 迁移和删除重复路径

---

## ✅ 验收标准的编写原则

### SMART 原则

验收标准必须是 **SMART**：
- **S**pecific（具体的）
- **M**easurable（可度量的）
- **A**chievable（可实现的）
- **R**elevant（相关的）
- **T**ime-bound（有时限的）

### 好的验收标准示例

✅ **好：可执行、可验证**
```markdown
- [ ] 单元测试覆盖率 ≥ 80%
- [ ] API 响应时间 P95 < 100ms
- [ ] 所有 acceptance 测试通过
- [ ] 文档已更新并经过 review
- [ ] 无 P0/P1 bug
```

❌ **不好：模糊、不可验证**
```markdown
- [ ] 代码质量好
- [ ] 性能不错
- [ ] 用户体验佳
- [ ] 基本完成
```

---

## 📊 Spec 文档生命周期

### 1. Proposed（提议）
- 状态：Proposed
- 内容：完整的 spec，但尚未批准
- 验收：需要 review 和批准

### 2. Approved（批准）
- 状态：Approved
- 内容：已批准，准备实施
- 验收：可以开始实施

### 3. In Progress（实施中）
- 状态：In Progress
- 内容：正在实施，部分 Requirements/Phases 完成
- 验收：持续更新各 Phase 状态

### 4. Implemented（已实施）
- 状态：Implemented
- 内容：所有 Requirements 和 Phases 完成
- 验收：所有验收标准通过

### 5. Deprecated（废弃）
- 状态：Deprecated
- 内容：不再使用
- 验收：记录废弃原因和替代方案

---

## 🔍 Spec 审查检查清单

### 完整性检查

- [ ] 是否有明确的目标？
- [ ] 是否明确了范围（包含/不包含）？
- [ ] 是否列出了所有 Requirements（R1-RN）？
- [ ] 是否定义了所有 Phases（P0-PN）？
- [ ] 每个 Requirement 是否有验收标准？
- [ ] 每个 Phase 是否有验收标准？

### 质量检查

- [ ] 验收标准是否 SMART？
- [ ] Requirements 之间的依赖是否清晰？
- [ ] Phases 之间的逻辑是否合理？
- [ ] 是否有明确的交付物？
- [ ] 是否考虑了风险和限制？

### 可执行性检查

- [ ] 验收标准是否可以写成测试？
- [ ] 是否可以从 spec 直接开始实施？
- [ ] 是否可以明确判断"完成"？

---

## 📚 示例

### 完整的 Requirement 示例

```markdown
### R6: Runtime 可观测性

**优先级：** P1  
**状态：** Complete  
**负责人：** Platform Team

**描述：**

Runtime 可观测性让部署方能够：
1. 实时监控 Agent 执行状态
2. 在失败时快速定位问题
3. 收集性能指标用于优化

当前系统缺少统一的可观测性层，问题排查依赖人工查看日志。
本 Requirement 通过 exporter 机制将运行时事件导出到外部系统。

**验收标准：**
- [ ] 支持 Redis Streams exporter
- [ ] 导出 RuntimeEpisode 包含完整的执行上下文
- [ ] 失败事件单独写入 failure stream
- [ ] 支持可配置的告警回调
- [ ] 验收测试覆盖正常和失败场景
- [ ] 文档说明部署和告警接线

**交付物：**
- 代码：`src/react_agent/harness/runtime_observability.py`
- 配置：Docker Compose 配置示例
- 测试：`tests/harness/test_runtime_observability.py`
- 文档：[`r6-observability.md`](r6-observability.md)（详细部署说明）

**依赖：**
- R5: 确定性 Replay（需要 RuntimeEpisode 定义）

**技术选型：**
- 使用 Redis Streams：易于集成，支持 Consumer Group
- exporter 接口可扩展：未来支持其他后端（Kafka, HTTP）

**非功能需求：**
- 性能：exporter 失败不影响主任务执行
- 安全：导出数据已脱敏
```

### 完整的 Phase 示例

```markdown
### Phase 4: Replay 与回归门禁

**目标：**
实现确定性回放和失败回归门禁，防止已修复的问题再次出现。

**包含的 Requirements：**
- R5: 确定性 Replay
- 部分 R6: Runtime 可观测性（failure detection）

**时间估算：**
2 周

**交付物：**
- [ ] 实现 deterministic replay manifest
- [ ] 实现 baseline compare 机制
- [ ] 实现 repair/reverify 闭环
- [ ] CI 集成回归门禁
- [ ] 验收报告：`evidence/phase4-completion.md`

**验收标准：**
- [ ] Replay 可以逐步重现工具调用
- [ ] Baseline compare 能检测新增失败
- [ ] Repair 后必须 reverify（不能只看历史）
- [ ] 回归门禁在 CI 中运行，阻止退化合并
- [ ] 有绿路径（无回归）和红路径（有回归）的端到端测试

**状态：** Complete

**完成日期：** 2026-10-19

**遗留问题：**
- Windows fixture/ACL 环境问题（记录在 Issue #123）
```

---

## 🚫 常见错误

### 错误 1: 验收标准不可执行

❌ **错误：**
```markdown
验收标准：
- [ ] 代码质量好
- [ ] 用户满意
```

✅ **正确：**
```markdown
验收标准：
- [ ] 代码审查通过（无 P0/P1 问题）
- [ ] 用户验收测试通过（所有 acceptance test cases）
```

### 错误 2: 范围不明确

❌ **错误：**
```markdown
范围：实现任务队列
```

✅ **正确：**
```markdown
范围：
包含：
- Redis Streams 异步任务队列
- Worker 进程管理
- 任务状态持久化（PostgreSQL）

不包含：
- 定时任务
- 优先级队列
- 跨区域复制
```

### 错误 3: Requirements 和 Phases 混淆

❌ **错误：**
```markdown
R4: Phase 1 实施
```

✅ **正确：**
```markdown
R4: StructuredOutputContract（功能要求）

Phase 1: Shared Contracts（实施阶段，包含 R1-R4）
```

---

## 📝 模板

### 新 Spec 快速模板

```markdown
# {Module} 规格

## 1. 文档状态
状态：Proposed  
版本：v1.0  
最后更新：YYYY-MM-DD

## 2. 概述
### 2.1 目标
[1-3 句话]

### 2.2 范围
#### 包含
- ...

#### 不包含
- ...

## 3. Requirements
### R1: [名称]
优先级：P0  
状态：Proposed  

描述：...

验收标准：
- [ ] ...

## 4. Phases
### Phase 0: 基线冻结
...

## 5. 验收证据
...
```

---

**版本：** v1.0  
**创建：** 2026-10-20  
**维护：** 项目维护团队
