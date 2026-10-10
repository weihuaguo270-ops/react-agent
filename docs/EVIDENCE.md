# 证据摘要

- FastAPI task runner 与 SoftwareTask failure-regression
- Docker sandbox 权限、资源、断网和清理验证
- Format B 轨迹、Harness、StepWatcher 与跨仓闭环
- 语义检索依赖（`[rag]`）本机 Compose 联调；**Milvus 后端未随 main 发布**（实现只在侧分支 `codex/daily-smoke-pr`）

- 闭环已验证 pass/review/hold 三种决策报告
- 软件交付最小验收集：5 条任务，覆盖 pass、repair、hold、approval_denied、tool_timeout
- `pass_existing_fix` 仅作为最终成功基线，不证明修复前后闭环。
- `repair_then_pass` 已按 `before/`、`repair/`、`after/` 保存本轮 Docker 实际执行的 Runner 结果、原始 stdout/stderr 和实际应用的补丁。修复前隐藏测试 3 项失败，修复后 3 项通过，公开测试两阶段均通过。
- 历史证据采集入口：`python scripts/eval/failure/collect_repair_evidence.py`。阶段 `trajectory.json` 是原始 Runner 结果，不是 Format B 或模型推理轨迹；根目录旧压缩记录已被阶段文件取代，不参与验收。
- 本轮 Docker 29.7.2 双阶段复验完成：`verified/pass`、`reverified: true`。入口为 `python scripts/eval/failure/reverify_repair_evidence.py`；独立运行记录位于 `artifacts/software-delivery/repair_then_pass/runs/c3f38283d1484b24b551179d0ac54486`。这是已有 Agent 补丁的重放验证，不是本轮模型重新生成补丁的证据。
- 独立失败 fixture 已运行并触发 `hold`：`tests_still_fail` -> `tool_error`、`tool_timeout` -> `search_timeout`、`approval_denied` -> `approval_denied`
- 上述三条属于 Trace Debugger 黄金 fixture 驱动的适配验证，不等同于生产任务执行、真实审批系统调用或线上 SLA 证明
