# 路线图

- P0（已完成）：一键生成执行、失败分析、过程评测和发布判断报告 —— 入口 `scripts/eval/acceptance/run_portfolio_acceptance.py`（输出 `artifacts/portfolio_acceptance_v1.json`）。
- P0（当前）：补齐 held-out / golden 发布门槛（跨仓账本 golden 仍为 0）。
- P1：补充 held-out 外部业务任务与长期稳定性证据
- 当前验收规模：跨仓账本 6 条 verified 任务、无待补名额（`eval/cross_repo_task_candidates.json`）；软件交付最小验收集 5 条（`scripts/eval/acceptance/build_acceptance_report.py`）。扩展前需先完成每条任务的真实轨迹、测试输出和复验记录。
