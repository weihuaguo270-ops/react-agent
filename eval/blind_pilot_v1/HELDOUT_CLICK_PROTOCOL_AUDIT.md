# Click held-out 协议审计（2026-09-22）

初次运行和重跑均使用冻结 v10 参数、`tool_choice: required`、仅暴露 submit：

| 运行 | 终态 | hidden | patch | tokens |
| --- | --- | --- | --- | ---: |
| `heldout-v10-click-20260922-133259` | invalid_run (`service_tool_choice_violation`) | failed | hidden_failed，756 bytes | 51525 |
| `heldout-v10-click-retry-20260922-135111` | invalid_run (`service_tool_choice_violation`) | failed | patch_empty，0 bytes | 53224 |
| Docker 恢复后最终重跑 | invalid_run (`service_tool_choice_violation`) | failed | hidden_failed，585 bytes | 51765 |

两次终态服务均返回单个 shell，主机侧校验均立即拦截，违规 shell 未执行。submit-only 独立探针曾返回合法 submit，但不足以证明任务请求稳定遵守约束。Click held-out 当前只能标记 `invalid_run`，不能解释为模型失败、通过或主动提交。

## 跨任务协议探针（2026-09-22）

兼容服务探针结果：

- 独立单轮 submit-only 探针：5/5 通过；每轮仅返回唯一 `submit`，并使用 `tool_choice: required`。
- 同一会话多轮探针：2/2 通过；连续两轮均仅返回唯一 `submit`。
- 模型：`deepseek-flash`；每轮约 342-343 tokens。

探针证明兼容服务在受控最小请求下能够保持单工具约束，但不覆盖此前 Click 任务请求的两次违规。因此 Click 仍保持 `invalid_run`，在重新运行前必须保留原始 `protocol_violation` 证据；`golden` 继续为 `0`。

## 重跑环境状态（2026-09-22）

协议探针通过后尝试启动 Click 重跑，但 Docker Engine 不可用：`com.docker.service` 处于 `Stopped`，启动服务被系统拒绝，启动 Docker Desktop 后 `docker info` 仍返回 `permission denied`（`npipe:////./pipe/docker_engine`）。本次未创建新的评测运行目录，也未生成新的模型结果；Click 继续保持 `invalid_run`。

## Docker 恢复后的最终重跑（2026-09-22）

Docker Engine 恢复后，按冻结 v10 配置仅重跑 `click-typed-flag-2930`。结果如下：

| 终态 | hidden | patch | tokens | budget |
| --- | --- | --- | ---: | --- |
| `protocol_violation` | failed | `hidden_failed`，585 bytes | 51,765 | compliant |

服务仍在终态阶段返回违规工具调用，运行器未执行违规工具并保存了本次原始结果。Click 继续标记为 `invalid_run`，不能计为有效 held-out、模型失败或主动提交；`golden` 保持 `0`。
