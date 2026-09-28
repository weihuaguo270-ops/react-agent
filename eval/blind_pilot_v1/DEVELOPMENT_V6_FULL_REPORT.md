# v6 development 全量结果（2026-09-20）

本轮汇总单任务校准 `runs/dev-v6-20260920-105518` 和其余三条 `runs/dev-v6-rest-20260920-105712`。两批 protocol.json 的运行器 SHA256、版本、预算、轮数、时间与护栏参数一致。全部使用 deepseek-flash、64k provider total tokens、40 轮和 900 秒；未运行 held-out。

| 任务 | 停止原因 | hidden | tokens | submit 次数 | patch 字节 |
| --- | --- | --- | ---: | ---: | ---: |
| httpx-activity-review | submitted | passed | 50819 | 1 | 756 |
| pydantic-identity-review | budget_exhausted | failed | 61127 | 0 | 0 |
| httpx-identity-review | budget_exhausted | passed | 60504 | 0 | 558 |
| werkzeug-auth-whitespace-3129 | budget_exhausted | passed | 62112 | 0 | 700 |

原始模型 usage 逐条加总与结果一致，submit 次数由模型工具调用核对，hidden 结果与独立验收 exit_code 一致。合计 234562 tokens；隐藏验收 3/4，主动提交 1/4，预算合规 4/4。费用未知，保持 null；未执行完整上游回归。

这是反复校准过的 development 集成绩，不是 clean held-out 或通用解题能力结论。预算耗尽是有效的受限运行停止原因，不应一律剔除：Pydantic 本轮在限定协议内没有形成补丁，属于本轮未解出；HTTPX identity 和 Werkzeug 的最终补丁通过验收，但没有主动提交。不得将 hidden passed 覆盖到停止原因。

预算提醒只在一条上观察到主动提交，尚不能声称稳定解决收敛问题。下一步离线分析 Pydantic 的工具循环与其余两条忽略提交提示的行为，再决定是否修改协议；不自动增加预算或重复付费运行。Click/Jinja 保持 provisional held-out，golden 0。
