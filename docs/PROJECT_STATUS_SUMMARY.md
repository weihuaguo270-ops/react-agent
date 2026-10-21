# 项目当前状态总结

**更新日期**: 2026-10-20

---

## 🎯 项目定位

**react-agent** 是一个面向编码执行、客服工作流和 RAG 研究场景的受控 Agent 运行时。

**对外口径**: 
- ✅ 可以表述为：可部署、可评测的 Agent 工程原型
- ❌ 不能表述为：生产 SaaS、长期线上 SLA、企业多租户权限平台

---

## 📊 核心模块状态

### 1. Harness - 构建与统一契约

**目标**: 将 Runtime Harness、Evaluation Harness 和 Shared Contracts 统一成可迁移、可验证的架构

**当前状态**: Proposed (实施中)

**阶段进度**:

| Phase | 名称 | 状态 | 说明 |
|-------|------|------|------|
| Phase 0 | 基线冻结 | ✅ Complete | 已生成 HARNESS_BASELINE_20261014 |
| Phase 1 | Shared Contracts | ✅ Complete | ToolCall, TaskEpisode, EvaluationEpisode 已统一，兼容期保留旧路径 |
| Phase 2 | Runtime 收敛 | ❓ 未明确 | - |
| Phase 3 | Evaluation 收敛 | ✅ Complete | EvaluationEpisode, FixtureManifest 已统一 |
| Phase 4 | Replay 与回归门禁 | ⚠️ Partial | baseline compare, repair/reverify 已完成；Windows fixture/ACL 环境问题待解决 |
| Phase 5 | 迁移和删除重复路径 | 🔄 In Progress | 弃用警告已激活，22 个活跃导入站点待迁移 |

**关键问题**:
- Phase 4 的 Windows 环境问题尚未解决
- Phase 5 的兼容期迁移正在进行中
- 跨仓 golden suite 环境问题待解决

**验收证据**: `docs/specs/harness/evidence/`

---

### 2. Expense - 工作流与决策模型

**目标**: 实现声明式 Workflow + 可插拔决策节点的业务编排样板

**当前状态**: Hold (等待业务确认)

**进度**:
- ✅ S1 baseline 已冻结 (2026-10-12)
- ✅ 规格已完成 (workflow-decision, form-workflow, policy-boundary)
- ⚠️ 等待政策边界第5节待确认项完成后才能继续

**关键问题**:
- 政策边界规格中有待业务确认项
- 在确认完成前，Expense 状态保持 Hold

**验收证据**: `docs/specs/expense/evidence/`

---

### 3. Redis Task Queue - 异步任务队列

**目标**: 基于 Redis Streams 的异步任务 MVP

**当前状态**: 规格定义阶段

**进度**:
- ✅ MVP 规格已编写
- ❌ 尚未开始实施

**规格**: `docs/specs/redis-task/mvp-spec.md`

---

## 🔬 测试与评测状态

### Execution (编码执行)
- ✅ 36/36 capability 测试通过

### Software Task (软件任务)
- ⚠️ 盲测准备中
- Development: 2/4 通过 (deepseek-flash v5)
- Held-out: 未运行
- Golden: 0

### Expense Business Cases
- ✅ S1 baseline: dev 2/2, golden 3/3, held-out 3/3 通过

### 失败回归门禁
- ✅ 失败检出、baseline compare、repair/reverify 闭环已建立
- ⚠️ Windows fixture/ACL 环境问题待解决

---

## ⚠️ 当前限制

### 未满足生产门槛
- held-out/golden 发布门槛仍未满足
- 不能宣称生产成熟度

### 待解决问题
1. **跨仓 golden suite**: Windows fixture/ACL 环境问题
2. **Phase 5 迁移**: 22 个活跃导入站点需迁移到新路径
3. **Software Task**: held-out 和 golden 测试未完成
4. **Expense**: 等待业务确认才能继续

---

## 📚 相关文档

- **详细状态**: [`docs/STATUS.md`](STATUS.md)
- **Harness 规格**: [`docs/specs/harness/spec.md`](specs/harness/spec.md)
- **Harness 进度**: [`docs/specs/harness/progress.md`](specs/harness/progress.md)
- **评测框架**: [`docs/testing/frameworks/`](testing/frameworks/)
- **成熟度评估**: [`docs/PRODUCTION_MATURITY.md`](PRODUCTION_MATURITY.md)

---

**总结**: 项目在 Harness 统一、评测框架、失败回归等方面已有坚实基础，但距离生产级成熟度仍有差距。当前重点是完成 Phase 4/5 的收尾工作和解决跨环境测试问题。
