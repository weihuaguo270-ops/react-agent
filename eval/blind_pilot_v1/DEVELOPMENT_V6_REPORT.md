# v6 单任务协议校准（2026-09-20）

基于 v5 终止原因审计，新增每轮剩余 token 与轮数提示；剩余护栏额度不超过 12000 tokens 或仅剩 3 轮时，要求提交当前补丁并如实说明未完成检查。没有向模型提供隐藏验收反馈。预算仍为 64000 provider total tokens，固定 4000 余量不构成严格防超限保证。

仅重跑 development 中的 `httpx-activity-review`，其余任务与 held-out 未运行。结果：主动 `submitted`，hidden acceptance 通过，50819 tokens，32.31 秒，预算合规。原始请求、响应和 submission.json 保存在本次 dev-v6 运行目录。

6 项本地回归测试通过，覆盖预算提示、轮数提示、验收与停止原因分离及预算违规不被通过结果覆盖。未执行完整上游回归；费用未知，保持 null。

这是重复使用 development 任务的协议校准，不是新一轮四任务成绩，也不与 v5 合并计算通过率。下一步按同一 v6 协议运行其余三条 development，并分别报告主动提交、隐藏验收、预算合规。held-out 在完成协议审查前保持不动。
