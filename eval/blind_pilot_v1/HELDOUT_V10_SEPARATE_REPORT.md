# v10 held-out 分项结果（2026-09-22）

两条 held-out 使用显式 `BLIND_SPLIT=held_out_provisional`，分别运行、分别保存，不与 development 合并。

| 任务 | 终态 | hidden | patch | tokens |
| --- | --- | --- | --- | ---: |
| click-typed-flag-2930（初次） | invalid_run (`service_tool_choice_violation`) | failed | hidden_failed，756 bytes | 51525 |
| click-typed-flag-2930（重跑） | invalid_run (`service_tool_choice_violation`) | failed | patch_empty，0 bytes | 53224 |
| click-typed-flag-2930（Docker 恢复后最终重跑） | invalid_run (`service_tool_choice_violation`) | failed | hidden_failed，585 bytes | 51765 |
| jinja-async-unique-1782 | terminal_submitted | passed | verified_fix，976 bytes | 52670 |

Click 三次终态请求均使用 `tool_choice: required` 且仅暴露 submit，但服务返回单个 shell；运行器拦截且未执行。三次原始证据均保留，统一标记为 `invalid_run`，原因 `service_tool_choice_violation`；Click 不纳入 held-out 通过率、主动提交率或 golden。Jinja 是唯一有效 held-out 结果：协议正常、hidden 通过、`verified_fix`，但为控制器终态 `terminal_submitted`，不计主动提交。两条任务均预算合规，golden 保持 0。当前数据集与 v10 协议冻结，不再为凑数量重复运行 Click；后续若继续评测，应更换稳定支持强制工具选择的模型或兼容服务并建立新批次，不能覆盖 v6-v10 历史记录。held-out 结果只反映独立运行，不能与 development 结果合并为通用能力结论。
