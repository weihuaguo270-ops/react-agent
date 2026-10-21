# 根目录 README.md 需要更新的路径

## 🔴 过时的路径引用

### 需要更新的文档链接

| 旧路径 | 新路径 | 位置 |
|--------|--------|------|
| `docs/STRUCTURE.md` | `docs/architecture/structure.md` | 多处 |
| `docs/CORE_ARCHITECTURE.md` | `docs/architecture/core-architecture.md` | 多处 |
| `docs/EVAL_INDEX.md` | `docs/testing/frameworks/eval-index.md` | 多处 |
| `docs/FAILURE_REGRESSION_PIPELINE.md` | `docs/operations/failure-regression-pipeline.md` | 行39 |
| `docs/P0_EVIDENCE_MAP.md` | `docs/testing/frameworks/p0-evidence-map.md` | 行135, 346 |
| `docs/HARNESS_HEALTH.md` | `docs/testing/frameworks/harness-health.md` | 行135, 300 |
| `docs/PORTABILITY.md` | `docs/features/portability.md` | 行31 |
| `docs/GITHUB_DELIVERY_WORKFLOW.md` | `docs/features/github-delivery-workflow.md` | 行33 |
| `docs/APPLICATION_DIRECTION.md` | `docs/features/application-direction.md` | 行35, 37, 322 |
| `docs/EVIDENCE_DOCS_TROUBLESHOOT.md` | `docs/features/evidence-docs-troubleshoot.md` | 行74, 121 |
| `docs/DOCS_TROUBLESHOOT_EVAL.md` | `docs/testing/frameworks/docs-troubleshoot-eval.md` | 行121, 346 |
| `docs/EXPERIMENTAL.md` | 保持不变（根目录） | 行164, 322 |
| `docs/PRODUCTION_MATURITY.md` | 保持不变（根目录） | 行39, 164 |
| `docs/SANDBOX_SECURITY.md` | `docs/features/sandbox-security.md` | 行236 |
| `docs/DEPLOY.md` | `docs/features/deploy.md` | 行284 |
| `docs/PLUGINS.md` | `docs/features/plugins.md` | 行294 |
| `docs/AGENT_WORKFLOW.md` | `docs/architecture/agent-workflow.md` | 行322 |
| `docs/spec/REDIS_TASK_MVP_SPEC.md` | `docs/specs/redis-task/mvp-spec.md` | 行70 |
| `docs/snapshots/github_portfolio_dataset_20260813.json` | `docs/testing/baselines/archive/2026-q3/github_portfolio_dataset_20260813.json` | 行118 |

### 需要更新的行数

- 行31: PORTABILITY.md
- 行33: GITHUB_DELIVERY_WORKFLOW.md
- 行35, 37: APPLICATION_DIRECTION.md
- 行39: STRUCTURE, CORE_ARCHITECTURE, EVAL_INDEX, FAILURE_REGRESSION_PIPELINE, PRODUCTION_MATURITY
- 行70: REDIS_TASK_MVP_SPEC.md
- 行74, 121: EVIDENCE_DOCS_TROUBLESHOOT, DOCS_TROUBLESHOOT_EVAL
- 行118: snapshots JSON
- 行135: P0_EVIDENCE_MAP, HARNESS_HEALTH
- 行164: EXPERIMENTAL, PRODUCTION_MATURITY
- 行168: STRUCTURE
- 行180: 注释中的 STRUCTURE · CORE · EVAL_INDEX
- 行236: SANDBOX_SECURITY
- 行254: CORE_ARCHITECTURE
- 行284: DEPLOY
- 行294: PLUGINS
- 行300: HARNESS_HEALTH
- 行322: APPLICATION_DIRECTION, AGENT_WORKFLOW, EXPERIMENTAL
- 行346: DOCS_TROUBLESHOOT_EVAL, EVAL_INDEX, P0_EVIDENCE_MAP

## ✅ 建议操作

批量替换以下路径：
```bash
# Architecture
docs/STRUCTURE.md → docs/architecture/structure.md
docs/CORE_ARCHITECTURE.md → docs/architecture/core-architecture.md
docs/AGENT_WORKFLOW.md → docs/architecture/agent-workflow.md

# Features
docs/APPLICATION_DIRECTION.md → docs/features/application-direction.md
docs/EVIDENCE_DOCS_TROUBLESHOOT.md → docs/features/evidence-docs-troubleshoot.md
docs/GITHUB_DELIVERY_WORKFLOW.md → docs/features/github-delivery-workflow.md
docs/PORTABILITY.md → docs/features/portability.md
docs/SANDBOX_SECURITY.md → docs/features/sandbox-security.md
docs/DEPLOY.md → docs/features/deploy.md
docs/PLUGINS.md → docs/features/plugins.md

# Testing
docs/EVAL_INDEX.md → docs/testing/frameworks/eval-index.md
docs/DOCS_TROUBLESHOOT_EVAL.md → docs/testing/frameworks/docs-troubleshoot-eval.md
docs/P0_EVIDENCE_MAP.md → docs/testing/frameworks/p0-evidence-map.md
docs/HARNESS_HEALTH.md → docs/testing/frameworks/harness-health.md

# Operations
docs/FAILURE_REGRESSION_PIPELINE.md → docs/operations/failure-regression-pipeline.md

# Specs
docs/spec/REDIS_TASK_MVP_SPEC.md → docs/specs/redis-task/mvp-spec.md

# Snapshots
docs/snapshots/*.json → docs/testing/baselines/archive/2026-q3/*.json
```
