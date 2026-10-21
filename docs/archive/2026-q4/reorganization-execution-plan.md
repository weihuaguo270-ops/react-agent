# 文档重组执行计划

## 📋 执行概览

按照已建立的规则，重组 docs/ 目录。

---

## 🎯 Phase 1: 创建新目录结构

```bash
# ✅ 已创建
docs/
├── specs/
│   ├── harness/
│   │   └── evidence/
│   ├── expense/
│   └── redis-task/
├── architecture/
├── features/
├── operations/
├── testing/
│   ├── frameworks/
│   └── baselines/
│       ├── current/
│       └── archive/2026-q3/
└── archive/2026-q4/
```

---

## 📝 Phase 2: 移动和重命名文件

### 2.1 Specs 目录重组

#### Harness Spec
```bash
# 主规格
git mv docs/spec/HARNESS_BUILD_SPEC.md docs/specs/harness/spec.md

# 子规格（R6）
git mv docs/spec/HARNESS_R6_REDIS_DEPLOYMENT.md docs/specs/harness/r6-observability.md

# 进度文档（迁移指南）
git mv docs/spec/HARNESS_PROGRESS.md docs/specs/harness/progress.md

# 迁移指南
git mv docs/guide/HARNESS_CONTRACT_MIGRATION.md docs/specs/harness/migration-guide.md

# 验收报告
git mv docs/spec/P4_COMPLETION_REPORT.md docs/specs/harness/evidence/phase4-completion.md

# Phase 5 系列
mkdir -p docs/specs/harness/evidence/phase5-migration
git mv docs/spec/P5_EXECUTIVE_SUMMARY.md docs/specs/harness/evidence/phase5-migration/summary.md
git mv docs/spec/P5_BATCH1_REPORT.md docs/specs/harness/evidence/phase5-migration/batch1-report.md
git mv docs/spec/P5_MIGRATION_GUIDE.md docs/specs/harness/evidence/phase5-migration/guide.md
git mv docs/spec/P5_MIGRATION_INVENTORY.md docs/specs/harness/evidence/phase5-migration/inventory.md
git mv docs/spec/P5_MIGRATION_PLAN.md docs/specs/harness/evidence/phase5-migration/plan.md
git mv docs/spec/P5_STATUS_SUMMARY.md docs/specs/harness/evidence/phase5-migration/status.md

# Phase 0 基线（从 evaluation/ 移动）
git mv docs/evaluation/HARNESS_BASELINE_20261014.md docs/specs/harness/evidence/phase0-baseline.md
```

#### Expense Spec
```bash
git mv docs/spec/EXPENSE_WORKFLOW_DECISION_SPEC.md docs/specs/expense/workflow-decision-spec.md
git mv docs/spec/EXPENSE_FORM_WORKFLOW_SPEC.md docs/specs/expense/form-workflow-spec.md
git mv docs/spec/EXPENSE_HUMAN_HANDOFF_SPEC.md docs/specs/expense/human-handoff-spec.md
git mv docs/spec/EXPENSE_POLICY_BOUNDARY_SPEC.md docs/specs/expense/policy-boundary-spec.md
git mv docs/spec/EXPENSE_IMPLEMENTATION_ROADMAP_SPEC.md docs/specs/expense/roadmap-spec.md

# Expense 验收证据
mkdir -p docs/specs/expense/evidence
git mv docs/evaluation/expense/EXPENSE_COVERAGE_MATRIX_V1.md docs/specs/expense/evidence/coverage-matrix-v1.md
git mv docs/evaluation/expense/S1_BASELINE_2026-10-12.md docs/specs/expense/evidence/s1-baseline-20261012.md
```

#### Redis Task Spec
```bash
git mv docs/spec/REDIS_TASK_MVP_SPEC.md docs/specs/redis-task/mvp-spec.md
```

### 2.2 Architecture 目录
```bash
git mv docs/CORE_ARCHITECTURE.md docs/architecture/core-architecture.md
git mv docs/STRUCTURE.md docs/architecture/structure.md
git mv docs/HARNESS_ARCHITECTURE.md docs/architecture/harness-architecture.md
git mv docs/AGENT_WORKFLOW.md docs/architecture/agent-workflow.md
git mv docs/WORKFLOW_QUICKREF.md docs/architecture/workflow-quickref.md
git mv docs/plan-multi-agent.md docs/architecture/multi-agent-plan.md
```

### 2.3 Features 目录
```bash
git mv docs/PLUGINS.md docs/features/plugins.md
git mv docs/APPLICATION_DIRECTION.md docs/features/application-direction.md
git mv docs/EVIDENCE_DOCS_TROUBLESHOOT.md docs/features/evidence-docs-troubleshoot.md
git mv docs/GITHUB_DELIVERY_WORKFLOW.md docs/features/github-delivery-workflow.md
git mv docs/DEPLOY.md docs/features/deploy.md
git mv docs/SANDBOX_SECURITY.md docs/features/sandbox-security.md
git mv docs/PORTABILITY.md docs/features/portability.md
```

### 2.4 Testing 目录
```bash
# 框架定义
git mv docs/evaluation/HARNESS_HEALTH.md docs/testing/frameworks/harness-health.md
git mv docs/evaluation/P0_EVIDENCE_MAP.md docs/testing/frameworks/evidence-map.md
git mv docs/evaluation/step_watcher_evidence_baseline.md docs/testing/frameworks/step-watcher-baseline.md
git mv docs/EVAL_INDEX.md docs/testing/frameworks/eval-index.md
git mv docs/DOCS_TROUBLESHOOT_EVAL.md docs/testing/frameworks/docs-troubleshoot-eval.md
git mv docs/SOFTWARE_TASK_DATASET.md docs/testing/frameworks/software-task-dataset.md
git mv docs/SOFTWARE_TASK_RUNNER.md docs/testing/frameworks/software-task-runner.md
git mv docs/EVIDENCE.md docs/testing/frameworks/evidence.md

# JSON 快照（当前 baselines）
mv docs/snapshots/sandbox_live_check_docker_latest.json docs/testing/baselines/current/
mv docs/snapshots/step_watcher_evidence_baseline.json docs/testing/baselines/current/

# 历史快照（归档）
mv docs/snapshots/*.json docs/testing/baselines/archive/2026-q3/ 2>/dev/null || true
```

### 2.5 Operations 目录
```bash
git mv docs/FAILURE_REGRESSION_PIPELINE.md docs/operations/failure-regression-pipeline.md
git mv docs/FAILURE_REGRESSION_PITCH.md docs/operations/failure-regression-pitch.md
git mv docs/FAILURE_FLYWHEEL.md docs/operations/failure-flywheel.md
git mv docs/CI_IMPROVEMENTS.md docs/operations/ci-improvements.md
git mv docs/ARTIFACT_RETENTION.md docs/operations/artifact-retention.md
git mv docs/WORKFLOW_IMPROVEMENTS.md docs/operations/workflow-improvements.md
```

### 2.6 Archive 目录（临时/历史文档）
```bash
# 重构文档
git mv docs/PLUGIN_REFACTORING_SUMMARY.md docs/archive/2026-q4/plugin-refactoring-summary.md
git mv docs/PLUGIN_REFACTORING_COMPLETE.md docs/archive/2026-q4/plugin-refactoring-complete.md
git mv docs/REFACTORING_EXPERIMENTAL_TO_PLUGINS.md docs/archive/2026-q4/refactoring-experimental-to-plugins.md
git mv docs/PROJECT_REORGANIZATION_COMPLETE.md docs/archive/2026-q4/project-reorganization-complete.md
git mv docs/TEMP_DIR_MANAGEMENT.md docs/archive/2026-q4/temp-dir-management.md
git mv docs/SESSION_SUMMARY_2026-10-19.md docs/archive/2026-q4/session-2026-10-19.md

# 重组分析文档（本次创建的）
git mv docs/DOCS_REORGANIZATION_PROPOSAL.md docs/archive/2026-q4/docs-reorganization-proposal.md
git mv docs/DOCS_REORGANIZATION_V2.md docs/archive/2026-q4/docs-reorganization-v2.md
git mv docs/DOCS_REORGANIZATION_FINAL_ANALYSIS.md docs/archive/2026-q4/docs-reorganization-analysis.md
```

### 2.7 删除过时的 markdown 快照
```bash
# 删除 7-9月的空快照文件（98-130字节）
rm docs/capability_newcases_20260713.md
rm docs/capability_snapshot_20260713.md
rm docs/eval_report_20260713.md
rm docs/execution_agent_snapshot_20260715.md
rm docs/execution_agent_snapshot_20260715_v2.md
rm docs/execution_agent_snapshot_20260716_v3.md
rm docs/execution_snapshot_20260715.md
rm docs/flywheel_closed_loop_20260716.md
rm docs/reliability_live_live_20260716.md
rm docs/reliability_live_live_20260716_v2.md
rm docs/reliability_live_mock_20260716.md
rm docs/reliability_live_mock_20260716_v2.md
rm docs/reliability_snapshot_20260715.md
rm docs/step_watcher_evidence_baseline.md
```

### 2.8 Reports 目录处理
```bash
# 检查 reports/ 是否还有内容
# 如果只剩 README，可以删除整个目录
```

---

## 📊 Phase 3: 更新内部链接

需要更新的文档：
- README.md（根目录）
- docs/README.md
- 各 spec 文档中的相对路径

---

## ✅ Phase 4: 验证

```bash
# 检查根目录只剩允许的文档
ls docs/*.md

# 应该只有：
# - README.md
# - CONTRIBUTING_DOCS.md
# - STATUS.md
# - ROADMAP.md
# - PRODUCTION_MATURITY.md
# - PROJECT_CONTEXT.md
# - EXPERIMENTAL.md

# 检查 spec 目录为空
ls docs/spec/ 2>/dev/null || echo "spec 目录已清空"

# 检查 evaluation 目录为空或只剩 daily_smoke
ls docs/evaluation/

# 检查 guide 目录为空
ls docs/guide/ 2>/dev/null || echo "guide 目录已清空"
```

---

## 📝 执行日志

执行开始：2026-10-20
执行者：AI Assistant

### Phase 1: ✅ 完成
### Phase 2: ⏳ 进行中
### Phase 3: ⏸️ 待执行
### Phase 4: ⏸️ 待执行
