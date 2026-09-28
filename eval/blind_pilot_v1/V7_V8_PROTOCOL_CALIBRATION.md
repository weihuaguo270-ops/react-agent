# v7/v8 协议校准（2026-09-20）

本报告记录两次单任务协议校准。它们不替代 v6 development 全量成绩，也不涉及 Click/Jinja provisional held-out。

| 协议 | 任务 | 终态 | hidden | tokens | patch | 结论 |
| --- | --- | --- | --- | ---: | ---: | --- |
| v7 | httpx-identity-review | budget_exhausted | passed | 60850 | 542 bytes | 补丁通过隐藏验收，但模型没有主动调用 submit。 |
| v8 | pydantic-identity-review | terminal_submitted | failed | 53223 | 0 bytes | 控制器在最终预算阶段强制要求 submit；模型明确报告未修改代码。 |

v7 引入 `bash -o pipefail -lc`、结构化历史摘要和环境契约，修复管道掩盖 pytest 退出码及压缩后丢失命令/退出码的问题。v8 将完整历史缩减到最近两组，并在最终预算阶段只开放 `submit` 工具。`terminal_submitted` 表示控制器触发的终态提交，不能计为模型主动提交。

校准说明：v8 之后，Pydantic 的任务描述已明确为 PEP 695 named alias / `TypeAliasType` 语义，并更新输入 SHA256。后续基于新描述的运行属于新的输入版本，不能与 v6 或 v8 的旧输入结果直接比较。正式可比的全量 development 成绩仍为 v6：hidden 3/4、主动提交 1/4、预算合规 4/4。

当前重跑前置条件是恢复固定 Docker 镜像 `agent-blind-pilot:20260919`。镜像可用后，应只重跑新版 Pydantic development 单任务并单独标记输入版本；held-out 继续保持未运行。

## Pydantic 输入 v2 重跑

固定镜像恢复后，`runs/dev-v8-pydantic-input-v2-20260920-124147` 使用新输入完成单任务重跑：`terminal_submitted`、60767 tokens、预算合规、hidden failed、patch 0 bytes。提交摘要正确定位到 `pydantic/root_model.py` 的 `RootModel.__eq__`，并指出应在比较前解包 `TypeAliasType.__value__`，但明确承认没有写入补丁或运行测试。

这说明输入歧义已消除，剩余失败属于执行收敛问题：模型在定位到最小修复后仍持续调查，直至控制器强制提交。该结果仍不计为主动 submit，也不能并入旧输入的 v6 全量成绩。下一轮若继续校准，应增加基于编辑进度的阶段门禁，例如在累计用量达到阈值且尚无编辑时要求立即实现并运行单一聚焦测试；不应继续扩大 token 预算。
