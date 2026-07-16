# 失败归因飞轮（Failure → Fix → Retest）

本页由 `examples/run_failure_flywheel.py` 追加。每次扫描后记录假设动作，
并在下一周期勾选是否完成改动与复测。

---

## 2026-07-16 — `tdebug_failure_flywheel_20260716`

- **source:** `D:/agent_learning/trace-debugger/examples/failure_bundle`
- **n:** 5
- **git (react-agent):** `98817ff`
- **distribution:** `{"context_overflow": 1, "duplicate": 1, "search_empty": 1, "llm_offtrack": 1, "no_answer": 1, "tool_error": 1}`

### 观察 → 假设动作 → 下次度量

1. tool_error → 开/核验 ToolGuard 重试；对高频失败工具加超时与自修提示
2. duplicate → 加强自修文案「勿重复相同失败调用」；限制同参重试次数
3. llm_offtrack → 收紧 system prompt / 增加 must_contain 验收；扩 execution hard 题
4. no_answer → 检查 max_steps / FINAL ANSWER 引导；评测侧标记超时
5. context_overflow → 启用上下文压缩策略；降低 traj 写入冗余

### 闭环状态

- [ ] 已落地代码/提示改动
- [ ] 已重跑 execution 或 reliability 相关子集
- [ ] 下周扫描对比本分布是否下降

---
