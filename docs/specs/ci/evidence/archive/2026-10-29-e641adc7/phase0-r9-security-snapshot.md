# CI R9 安全快照

**状态：** `attention_required`（这是 Phase 0 事实快照，不是 Phase 1 R9 验收通过）
**采集提交：** `e641adc7c95907a1bf55f7185c90faaa87b78829`
**采集时间：** `2026-10-29T15:38:50.791143+00:00`

## 范围

- workflow 事件、权限、Secret 引用、外部 Action 引用和写操作。
- Dockerfile 的基础镜像引用。
- 该文件只记录静态可观察事实；fork Secret 隔离和运行时权限仍需 Phase 1 验收证据。

## 发现

- `external-actions-not-commit-pinned` (high)：`.github/workflows/daily-smoke.yml`；计划阶段：Phase 1；详情：`["actions/checkout@v4", "actions/setup-python@v5", "actions/upload-artifact@v4"]`
- `external-actions-not-commit-pinned` (high)：`.github/workflows/evaluation.yml`；计划阶段：Phase 1；详情：`["actions/checkout@v4", "actions/setup-python@v5", "actions/checkout@v4", "actions/setup-python@v5", "actions/upload-artifact@v4", "actions/checkout@v4", "actions/setup-python@v5", "actions/upload-artifact@v4"]`
- `external-actions-not-commit-pinned` (high)：`.github/workflows/harness.yml`；计划阶段：Phase 1；详情：`["actions/checkout@v4", "actions/checkout@v4", "actions/setup-python@v5"]`
- `external-actions-not-commit-pinned` (high)：`.github/workflows/test.yml`；计划阶段：Phase 1；详情：`["actions/checkout@v4", "actions/setup-python@v5", "actions/checkout@v4", "actions/setup-python@v5", "actions/checkout@v4", "actions/setup-python@v5", "actions/checkout@v4", "actions/setup-python@v5", "actions/checkout@v4", "actions/setup-python@v5", "actions/checkout@v4", "actions/setup-python@v5", "actions/checkout@v4"]`
- `workflow-permissions-not-explicit` (medium)：`.github/workflows/test.yml`；计划阶段：Phase 1；详情：`"Effective GITHUB_TOKEN permissions depend on repository defaults."`
- `docker-base-image-not-digest-pinned` (medium)：`Dockerfile`；计划阶段：Phase 1；详情：`"python:3.11-slim (line 2)"`
- `docker-base-image-not-digest-pinned` (medium)：`Dockerfile.sandbox`；计划阶段：Phase 1；详情：`"python:3.11-slim (line 1)"`
- `docker-base-image-not-digest-pinned` (medium)：`eval/blind_pilot_v1/Dockerfile`；计划阶段：Phase 1；详情：`"react-agent-sandbox:0.7.0 (line 1)"`
- `docker-base-image-not-digest-pinned` (medium)：`_clean_pr/Dockerfile`；计划阶段：Phase 1；详情：`"python:3.11-slim (line 2)"`
- `docker-base-image-not-digest-pinned` (medium)：`_clean_pr/Dockerfile.sandbox`；计划阶段：Phase 1；详情：`"python:3.11-slim (line 1)"`
- `docker-base-image-not-digest-pinned` (medium)：`_clean_pr/eval/blind_pilot_v1/Dockerfile`；计划阶段：Phase 1；详情：`"react-agent-sandbox:0.7.0 (line 1)"`
- `docker-base-image-not-digest-pinned` (medium)：`_daily_smoke_fix/Dockerfile`；计划阶段：Phase 1；详情：`"python:3.11-slim (line 2)"`
- `docker-base-image-not-digest-pinned` (medium)：`_daily_smoke_fix/Dockerfile.sandbox`；计划阶段：Phase 1；详情：`"python:3.11-slim (line 1)"`
- `docker-base-image-not-digest-pinned` (medium)：`_daily_smoke_fix/eval/blind_pilot_v1/Dockerfile`；计划阶段：Phase 1；详情：`"react-agent-sandbox:0.7.0 (line 1)"`
- `docker-base-image-not-digest-pinned` (medium)：`_phase0_branch/Dockerfile`；计划阶段：Phase 1；详情：`"python:3.11-slim (line 2)"`
- `docker-base-image-not-digest-pinned` (medium)：`_phase0_branch/Dockerfile.sandbox`；计划阶段：Phase 1；详情：`"python:3.11-slim (line 1)"`
- `docker-base-image-not-digest-pinned` (medium)：`_phase0_branch/eval/blind_pilot_v1/Dockerfile`；计划阶段：Phase 1；详情：`"react-agent-sandbox:0.7.0 (line 1)"`
- `docker-base-image-not-digest-pinned` (medium)：`_phase0_clean/Dockerfile`；计划阶段：Phase 1；详情：`"python:3.11-slim (line 2)"`
- `docker-base-image-not-digest-pinned` (medium)：`_phase0_clean/Dockerfile.sandbox`；计划阶段：Phase 1；详情：`"python:3.11-slim (line 1)"`
- `docker-base-image-not-digest-pinned` (medium)：`_phase0_clean/eval/blind_pilot_v1/Dockerfile`；计划阶段：Phase 1；详情：`"react-agent-sandbox:0.7.0 (line 1)"`
- `docker-base-image-not-digest-pinned` (medium)：`_risk_docs_rebase/Dockerfile`；计划阶段：Phase 1；详情：`"python:3.11-slim (line 2)"`
- `docker-base-image-not-digest-pinned` (medium)：`_risk_docs_rebase/Dockerfile.sandbox`；计划阶段：Phase 1；详情：`"python:3.11-slim (line 1)"`
- `docker-base-image-not-digest-pinned` (medium)：`_risk_docs_rebase/eval/blind_pilot_v1/Dockerfile`；计划阶段：Phase 1；详情：`"react-agent-sandbox:0.7.0 (line 1)"`

机器可读明细见同目录的 `phase0-r9-security-snapshot.json`。
