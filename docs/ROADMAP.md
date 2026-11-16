# 路线图

- P0（已完成）：一键生成执行、失败分析、过程评测和发布判断报告 —— 入口 `scripts/eval/acceptance/run_portfolio_acceptance.py`（输出 `artifacts/portfolio_acceptance_v1.json`）。
- 当前项（2026-11-16）：已放弃发布门槛「3 个项目、30 条真实任务、10 条独立 held-out」。现有离线验收保留为工程原型证据；不再规划为 llm-eval-engine 与 trace-debugger 补齐该门槛。
- 放弃范围：不再把补齐跨仓账本 golden、补齐 held-out，或把这条门槛写成当前 P0 或下一阶段必做事。跨仓账本 golden 仍为 0、Click/Jinja held-out 等历史记录保留原样。这条门槛会把工作卷进独立质量仓 llm-eval-engine 与 trace-debugger；本仓简历材料仍只写工作助手，库存预占留在另仓，不把两个评测仓改写成简历上的第三项。
- 成熟度：工作助手对外仍是可部署、可评测的工程原型（规范咨询 + 报销办理）。S0–S8 报销原型验收已收口。放弃该门槛不把现有离线评测写成生产成熟度。
- 保留的验收规模（历史事实，非待补目标）：跨仓账本 6 条 verified 任务（`eval/cross_repo_task_candidates.json`）；软件交付最小验收集 5 条（`scripts/eval/acceptance/build_acceptance_report.py`）。
- 真实业务责任人、长期运行、多租户与生产 SLA 等缺口仍见 `docs/PROJECT_STATUS_SUMMARY.md`，与这条已放弃的门槛分开记录。
