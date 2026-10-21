# 文档导航

欢迎来到 react-agent 项目文档。

---

## 🚀 快速开始

- **我想使用这个项目** → 从根目录 [`README.md`](../README.md) 开始
- **我想了解架构** → [`architecture/`](architecture/)
- **我想查看功能** → [`features/`](features/)
- **我想贡献文档** → [`CONTRIBUTING_DOCS.md`](CONTRIBUTING_DOCS.md) ⚠️ **贡献前必读**

---

## 📂 目录结构

```
docs/
├── architecture/     🏗️ 架构设计（系统如何设计）
├── features/         ✨ 功能说明（有什么功能）
├── specs/            📋 规格定义（功能规格和验收）
├── testing/          🧪 测试评测（评测框架和基线）
├── operations/       🔧 运维流程（CI、发布、回归）
├── archive/          📦 历史归档（过时文档）
└── daily_smoke/      🔥 每日冒烟测试
```

---

## 📖 按角色导航

### 我是新用户

1. [`../README.md`](../README.md) - 项目介绍和快速开始
2. [`guides/`](guides/) - 使用指南（待完善）
3. [`features/`](features/) - 功能列表

### 我是开发者

1. [`architecture/`](architecture/) - 架构设计
   - [`core-architecture.md`](architecture/core-architecture.md) - 核心架构
   - [`structure.md`](architecture/structure.md) - 代码结构
2. [`specs/`](specs/) - 各模块规格
3. [`operations/`](operations/) - CI 和发布流程

### 我是测试/QA

1. [`testing/frameworks/`](testing/frameworks/) - 评测框架
2. [`testing/baselines/`](testing/baselines/) - 评测基线
3. [`specs/{module}/evidence/`](specs/) - 验收证据

### 我想贡献

1. [`CONTRIBUTING_DOCS.md`](CONTRIBUTING_DOCS.md) - 文档贡献指南 ⚠️ **必读**
2. [`../CONTRIBUTING.md`](../CONTRIBUTING.md) - 代码贡献指南

---

## 📋 按主题导航

### 架构与设计

- [核心架构](architecture/core-architecture.md) - 整体架构设计
- [仓库结构](architecture/structure.md) - 代码和文档组织
- [Agent 工作流](architecture/agent-workflow.md) - Agent 执行流程

### 功能说明

- [插件系统](features/plugins.md) - 可选插件功能
- [应用方向](features/application-direction.md) - 三大应用场景
- [文档排障](features/evidence-docs-troubleshoot.md) - 文档排障应用
- [GitHub 交付](features/github-delivery-workflow.md) - GitHub 工作流集成
- [部署指南](features/deploy.md) - 部署和配置
- [沙箱安全](features/sandbox-security.md) - 沙箱隔离机制
- [可移植性](features/portability.md) - 跨平台支持

### 规格与验收

- [Harness 规格](specs/harness/) - Harness 构建规格和验收
- [Expense 规格](specs/expense/) - Expense 工作流规格
- [Redis Task 规格](specs/redis-task/) - Redis 任务队列规格

### 测试与评测

- [评测框架](testing/frameworks/) - 评测标准和框架定义
- [评测基线](testing/baselines/) - 当前评测基线

### 运维与流程

- [失败回归](operations/failure-regression.md) - 失败回归门禁
- [CI 改进](operations/ci-improvements.md) - CI 流程改进
- [制品保留](operations/artifact-retention.md) - 制品保留策略

---

## 📌 重要文档

位于根目录的顶级文档：

- [`STATUS.md`](STATUS.md) - 项目当前状态（详细进度和限制）
- [`PROJECT_STATUS_SUMMARY.md`](PROJECT_STATUS_SUMMARY.md) - 项目状态总结（快速概览）
- [`ROADMAP.md`](ROADMAP.md) - 项目路线图
- [`PRODUCTION_MATURITY.md`](PRODUCTION_MATURITY.md) - 生产成熟度评估
- [`PROJECT_CONTEXT.md`](PROJECT_CONTEXT.md) - 项目背景

**当前项目状态快照**：
- ✅ Harness Phase 0-1, 3: Complete
- ⚠️ Harness Phase 4: Partial (Windows 环境问题待解决)
- 🔄 Harness Phase 5: In Progress (兼容期迁移中，22个导入站点待迁移)
- ⚠️ Expense: Hold (等待业务确认)
- ⏸️ Redis Task: 规格定义阶段
- ⚠️ 生产门槛: held-out/golden 测试未满足，不能宣称生产成熟度

---

## 🔍 搜索提示

### 按文件名搜索
```bash
find docs -name "*plugin*"
find docs -name "*harness*"
```

### 按内容搜索
```bash
grep -r "插件系统" docs/
grep -r "评测框架" docs/
```

---

## ⚠️ 贡献文档前必读

**在创建、修改或移动文档之前，请务必阅读：**

📜 **[文档贡献指南](CONTRIBUTING_DOCS.md)**

了解：
- 文档应该放在哪里
- 文件命名规则
- 禁止的做法
- 常见场景处理

**不遵守规则的 PR 可能被要求修改。**

---

## 📅 文档维护

- **负责人：** 项目维护团队
- **更新频率：** 按需更新
- **反馈渠道：** GitHub Issues

---

**版本：** v1.0  
**最后更新：** 2026-10-20
