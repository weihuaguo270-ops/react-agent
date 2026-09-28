# v10 HTTPX identity required-tool 重测（2026-09-22）

named-function `tool_choice` 曾在终态被兼容服务忽略，导致 `protocol_violation`。兼容层改为终态只暴露 `submit` 并发送 `tool_choice: "required"` 后，`httpx-identity-review` 重测成功：`terminal_submitted`、hidden passed、53473 tokens、budget compliant。请求 `request-18.json` 明确记录 `tool_choice: required`；模型调用为 21 次 shell、1 次 submit；未生成 protocol-violation.json。patch、conversation、submission、原始请求/响应和 hidden 结果完整。
