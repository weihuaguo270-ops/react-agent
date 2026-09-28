# v10 终态调用校验

复核 `runs/dev-v9-pydantic-input-v2-20260920-141916/pydantic-identity-review` 的 request/model 20、21、22：请求仅开放 submit 并设置强制 tool_choice，但响应仍返回 shell。旧运行器继续执行这些命令。这是兼容服务返回不符合工具约束的响应与本地缺少校验共同导致，不能简单归因为模型不主动提交，也不能据此证明 v9 提醒稳定有效。

v10 在执行前校验完整调用批次。终态只接受一个 submit；shell、空调用、混合调用、重复 submit 均标记 protocol_violation 并停止，不执行违规批次。普通阶段也提前拒绝未知工具。原始响应与违规详情保留，hidden 验收仍单独记录，历史结果不改写。

HTTPX 复测表明服务收到 named-function `tool_choice` 仍返回 shell。兼容层现改为终态只暴露 submit，并发送通用 `tool_choice: "required"`；主机侧批次校验继续保留。

验证：16 项离线测试及语法编译通过。新增测试覆盖历史 shell 响应、两种混合顺序、空调用、重复 submit 与未知工具。尚未进行 v10 在线运行；测试证明本地主机拒绝违规调用，不证明服务端遵守 tool_choice 或提高任务通过率。Click/Jinja held-out 保持未运行。
