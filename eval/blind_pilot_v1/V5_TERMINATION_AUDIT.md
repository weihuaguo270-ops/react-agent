# v5 终止原因审计（2026-09-20）

以原始 model 响应、conversation、patch.diff 和 result.json 交叉核查。原始运行文件保留，以下为派生更正。

| 任务 | 模型轮数 | submit 次数 | 实际终止原因 | total tokens | 64k 合规 | 补丁字节 | 隐藏验收 |
|---|---:|---:|---|---:|---|---:|---|
| httpx-activity-review | 24 | 0 | budget_exhausted | 61707 | true | 756 | passed |
| pydantic-identity-review | 28 | 0 | budget_exhausted | 61535 | true | 906 | failed |
| httpx-identity-review | 22 | 0 | budget_exhausted | 60728 | true | 0 | failed |
| werkzeug-auth-whitespace-3129 | 27 | 0 | budget_exhausted | 60568 | true | 488 | passed |

来源：`runs/dev-v5-20260919-232158`（HTTPX activity）与 `runs/dev-v5-rest-20260919-232525`（其余三条）。逐条加总 provider usage 与结果记录一致。末次模型响应均调用 shell，且对应 shell 输出存在；累计 usage 均达到 60000 的请求前停止阈值，未达到 40 轮或 900 秒限制。故根据原运行器控制流重建为预算护栏终止，而非主动提交。

四条最后仍在读取源码或测试。Pydantic 的最终补丁未通过隐藏验收，HTTPX identity 没有补丁；不能将二者统一描述为“尚无法判断补丁是否错误”。

撤回旧报告中“submit 已使正确补丁及时终止”的结论：两条 passed 是隐藏验收覆盖运行状态造成的。隐藏验收结果仍为 2/4，主动 submit 为 0/4；两者须分别报告。预算合规表示实测总量没有超过 64000，不代表固定 4000 余量能保证未来请求不越界。

运行器现分开记录 termination_reason、hidden_passed、budget_compliant，run_status 保留停止原因。文本结束记为 model_finished，显式工具提交才记为 submitted。本次仅离线审计及回归测试，没有新模型调用。
