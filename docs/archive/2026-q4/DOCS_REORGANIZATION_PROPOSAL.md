# docs/ 目录结构分析与重组建议

## 📊 当前状况

### 统计数据
- **总计**: 104 个 markdown 文件
- **根目录**: 54 个 markdown 文件
- **子目录**: 6 个（daily_smoke, evaluation, guide, reports, snapshots, spec）

### 当前结构
```
docs/
├── [54个 .md 文件] ⚠️ 太多，难以导航
├── daily_smoke/
├── evaluation/
│   └── expense/
├── guide/
├── reports/        ✅ 已有（进度报告）
├── snapshots/      ✅ 已有（JSON快照）
└── spec/           (16个文件)
```

## 🔍 问题分析

### 主要问题

1. **根目录过于拥挤** (54个文件)
   - 核心架构文档（CORE_ARCHITECTURE.md, STRUCTURE.md）
   - 评测文档（EVAL_INDEX.md, DOCS_TROUBLESHOOT_EVAL.md）
   - 工作流文档（AGENT_WORKFLOW.md, GITHUB_DELIVERY_WORKFLOW.md）
   - 阶段报告（P3-3, P4, P5）
   - 历史快照（*_20260713.md, *_20260715.md）
   - 重构文档（PLUGIN_REFACTORING_*.md, PROJECT_REORGANIZATION_*.md）
   - 混杂在一起，难以找到需要的文档

2. **分类不清晰**
   - 历史快照文件（带日期的）与当前文档混在一起
   - 阶段完成报告散落在根目录
   - 重构文档没有归档

3. **命名不一致**
   - 有些用下划线（reliability_live_mock_20260716.md）
   - 有些用中划线（P3-3_COMPLETION_REPORT.md）
   - 日期格式不统一（20260713 vs 2026-10-19）

## ✅ 推荐的重组方案

### 建议的新结构

```
docs/
├── README.md                          # 📖 文档导航总入口
│
├── architecture/                      # 🏗️ 架构设计（核心）
│   ├── CORE_ARCHITECTURE.md
│   ├── STRUCTURE.md
│   ├── HARNESS_ARCHITECTURE.md
│   ├── HARNESS_HEALTH.md
│   ├── AGENT_WORKFLOW.md
│   └── WORKFLOW_QUICKREF.md
│
├── features/                          # ✨ 功能说明
│   ├── PLUGINS.md
│   ├── APPLICATION_DIRECTION.md
│   ├── EVIDENCE_DOCS_TROUBLESHOOT.md
│   ├── GITHUB_DELIVERY_WORKFLOW.md
│   ├── SANDBOX_SECURITY.md
│   ├── DEPLOY.md
│   └── PORTABILITY.md
│
├── evaluation/                        # 📊 评测体系（已存在，需整理）
│   ├── EVAL_INDEX.md
│   ├── DOCS_TROUBLESHOOT_EVAL.md
│   ├── SOFTWARE_TASK_DATASET.md
│   ├── SOFTWARE_TASK_RUNNER.md
│   ├── P0_EVIDENCE_MAP.md
│   ├── EVIDENCE.md
│   └── expense/
│
├── operations/                        # 🔧 运维与流程（新建）
│   ├── FAILURE_REGRESSION_PIPELINE.md
│   ├── FAILURE_REGRESSION_PITCH.md
│   ├── FAILURE_FLYWHEEL.md
│   ├── CI_IMPROVEMENTS.md
│   ├── ARTIFACT_RETENTION.md
│   └── WORKFLOW_IMPROVEMENTS.md
│
├── guides/                            # 📚 指南（已存在guide/）
│   └── [用户指南]
│
├── reports/                           # 📝 进度报告（已存在）
│   ├── README.md
│   ├── phases/                        # 阶段报告（新子目录）
│   │   ├── P3-3_COMPLETION_REPORT.md
│   │   ├── P4_COMPLETION_REPORT.md
│   │   ├── P4_IMPLEMENTATION_PLAN.md
│   │   ├── P5_CHECKLIST.md
│   │   ├── P5_COMPLETION_SUMMARY.md
│   │   ├── P5_FINAL_REPORT.md
│   │   ├── P5_SHORT_TERM_WORK_SUMMARY.md
│   │   └── WORK_SUMMARY.md
│   │
│   ├── refactoring/                   # 重构报告（新子目录）
│   │   ├── PLUGIN_REFACTORING_SUMMARY.md
│   │   ├── PLUGIN_REFACTORING_COMPLETE.md
│   │   ├── REFACTORING_EXPERIMENTAL_TO_PLUGINS.md
│   │   ├── PROJECT_REORGANIZATION_COMPLETE.md
│   │   └── TEMP_DIR_MANAGEMENT.md
│   │
│   └── sessions/                      # 会话记录（新子目录）
│       └── SESSION_SUMMARY_2026-10-19.md
│
├── snapshots/                         # 📸 历史快照（已存在，需整理）
│   ├── 2026-07/                       # 按月归档
│   │   ├── capability_newcases_20260713.md
│   │   ├── capability_snapshot_20260713.md
│   │   ├── eval_report_20260713.md
│   │   ├── execution_agent_snapshot_20260715.md
│   │   ├── execution_agent_snapshot_20260715_v2.md
│   │   ├── execution_agent_snapshot_20260716_v3.md
│   │   ├── execution_snapshot_20260715.md
│   │   ├── flywheel_closed_loop_20260716.md
│   │   ├── reliability_live_live_20260716.md
│   │   ├── reliability_live_live_20260716_v2.md
│   │   ├── reliability_live_mock_20260716.md
│   │   ├── reliability_live_mock_20260716_v2.md
│   │   ├── reliability_snapshot_20260715.md
│   │   └── step_watcher_evidence_baseline.md
│   │
│   └── README.md                      # 快照索引
│
├── spec/                              # 📋 规范文档（已存在）
│   └── [16个规范文件]
│
├── daily_smoke/                       # 🔥 每日冒烟测试
│
├── STATUS.md                          # 📌 项目状态（保持根目录）
├── ROADMAP.md                         # 🗺️ 路线图（保持根目录）
├── PRODUCTION_MATURITY.md             # 🎯 成熟度（保持根目录）
└── PROJECT_CONTEXT.md                 # 📋 项目背景（保持根目录）
```

## 📋 文件分类清单

### architecture/ (7个文件)
- CORE_ARCHITECTURE.md
- STRUCTURE.md
- HARNESS_ARCHITECTURE.md
- HARNESS_HEALTH.md
- AGENT_WORKFLOW.md
- WORKFLOW_QUICKREF.md
- plan-multi-agent.md

### features/ (7个文件)
- PLUGINS.md
- APPLICATION_DIRECTION.md
- EVIDENCE_DOCS_TROUBLESHOOT.md
- GITHUB_DELIVERY_WORKFLOW.md
- SANDBOX_SECURITY.md
- DEPLOY.md
- PORTABILITY.md

### evaluation/ (移动5个文件到此)
- EVAL_INDEX.md
- DOCS_TROUBLESHOOT_EVAL.md
- SOFTWARE_TASK_DATASET.md
- SOFTWARE_TASK_RUNNER.md
- P0_EVIDENCE_MAP.md
- EVIDENCE.md

### operations/ (6个文件)
- FAILURE_REGRESSION_PIPELINE.md
- FAILURE_REGRESSION_PITCH.md
- FAILURE_FLYWHEEL.md
- CI_IMPROVEMENTS.md
- ARTIFACT_RETENTION.md
- WORKFLOW_IMPROVEMENTS.md

### reports/phases/ (移动8个文件)
- P3-3_COMPLETION_REPORT.md
- P4_COMPLETION_REPORT.md
- P4_IMPLEMENTATION_PLAN.md
- HARNESS_BUILD_SPEC_COMPLETE.md
- HARNESS_PROGRESS_REPORT.md
- P5_COMPLETION_SUMMARY.md
- P5_FINAL_REPORT.md
- P5_SHORT_TERM_WORK_SUMMARY.md
- WORK_SUMMARY.md

### reports/refactoring/ (5个文件)
- PLUGIN_REFACTORING_SUMMARY.md
- PLUGIN_REFACTORING_COMPLETE.md
- REFACTORING_EXPERIMENTAL_TO_PLUGINS.md
- PROJECT_REORGANIZATION_COMPLETE.md
- TEMP_DIR_MANAGEMENT.md

### reports/sessions/ (1个文件)
- SESSION_SUMMARY_2026-10-19.md

### snapshots/2026-07/ (14个文件)
- capability_newcases_20260713.md
- capability_snapshot_20260713.md
- eval_report_20260713.md
- execution_agent_snapshot_20260715.md
- execution_agent_snapshot_20260715_v2.md
- execution_agent_snapshot_20260716_v3.md
- execution_snapshot_20260715.md
- flywheel_closed_loop_20260716.md
- reliability_live_live_20260716.md
- reliability_live_live_20260716_v2.md
- reliability_live_mock_20260716.md
- reliability_live_mock_20260716_v2.md
- reliability_snapshot_20260715.md
- step_watcher_evidence_baseline.md

### 保持根目录 (4个文件)
- STATUS.md
- ROADMAP.md
- PRODUCTION_MATURITY.md
- PROJECT_CONTEXT.md

## 🎯 重组优势

### 1. 清晰的导航
- **架构设计** → `architecture/`
- **功能说明** → `features/`
- **评测体系** → `evaluation/`
- **运维流程** → `operations/`
- **进度报告** → `reports/`
- **历史快照** → `snapshots/`

### 2. 易于维护
- 新文档知道放在哪里
- 历史文档按月归档
- 重构文档集中管理

### 3. 改善可读性
- 根目录只保留最重要的4个文档
- 每个类别都有清晰的职责
- 历史快照与当前文档分离

## 📝 实施计划

### Phase 1: 创建新目录结构
```bash
mkdir -p docs/architecture
mkdir -p docs/features
mkdir -p docs/operations
mkdir -p docs/reports/phases
mkdir -p docs/reports/refactoring
mkdir -p docs/reports/sessions
mkdir -p docs/snapshots/2026-07
```

### Phase 2: 移动文件（保留 git 历史）
```bash
# 架构文档
git mv docs/CORE_ARCHITECTURE.md docs/architecture/
git mv docs/STRUCTURE.md docs/architecture/
# ... (其他文件)

# 历史快照
git mv docs/*_20260713.md docs/snapshots/2026-07/
git mv docs/*_20260715.md docs/snapshots/2026-07/
git mv docs/*_20260716.md docs/snapshots/2026-07/
```

### Phase 3: 创建索引文档
- `docs/README.md` - 总导航
- `docs/architecture/README.md`
- `docs/features/README.md`
- `docs/evaluation/README.md`
- `docs/operations/README.md`
- `docs/snapshots/README.md`

### Phase 4: 更新引用
- 更新其他文档中的相对路径引用
- 更新 README.md 中的文档链接
- 验证所有链接有效

## ⚠️ 注意事项

1. **Git 历史保留** - 使用 `git mv` 而非普通 `mv`
2. **链接更新** - 移动后需要更新文档间的相对路径
3. **CI 影响** - 检查 CI 是否有硬编码的文档路径
4. **分阶段实施** - 可以先做一部分，测试后再继续

## 💡 建议

### 立即可做（高优先级）
1. ✅ 创建 `docs/architecture/` - 整合核心架构文档
2. ✅ 创建 `docs/features/` - 整合功能说明文档
3. ✅ 整理 `docs/reports/` - 添加子目录分类
4. ✅ 整理 `docs/snapshots/` - 按月归档历史快照

### 可选（低优先级）
- 创建 `docs/operations/` - 运维相关文档
- 统一文件命名规范
- 创建详细的 README 导航

## ✅ 结论

**是的，`docs/` 目录需要重组！**

当前 54 个文件堆在根目录，分类不清，导航困难。建议按照上述方案重组，将文档分为：
- `architecture/` - 架构设计
- `features/` - 功能说明  
- `evaluation/` - 评测体系
- `operations/` - 运维流程
- `reports/` - 进度报告（分phases/refactoring/sessions）
- `snapshots/` - 历史快照（按月归档）

这样可以大大提升文档的可维护性和可读性。
