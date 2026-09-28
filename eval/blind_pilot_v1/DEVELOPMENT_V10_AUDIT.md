# v10 development 结果审计（2026-09-22）

| 任务 | hidden | 补丁证据 | 终态 | 主动提交 | tokens |
| --- | --- | --- | --- | --- | ---: |
| pydantic-identity-review | passed | `verified_fix`，1415 bytes，`6d2e7734b181b2233af0202b8ec35c096657959320e5d1bd181fe198ddf16dfc` | terminal_submitted | 否 | 51140 |
| httpx-identity-review | passed | `verified_fix`，562 bytes，`163dd6a34a78526c759a2bd11a93be2fa4eadd09f8f842605cb0d552eca248d4` | terminal_submitted | 否 | 51707 |
| httpx-activity-review | passed | `verified_fix`，756 bytes，`e36b29f2bd30c9096c8b949e3925a93329e2383387747287ec2ce159e8167925` | terminal_submitted | 否 | 51248 |
| werkzeug-auth-whitespace-3129 | passed | `verified_fix`，702 bytes，`03739fc9a4462ca00f93415ffbe88f2d8f8a82eeb4fe17fbf8b2ccb7d68c7db6` | submitted | 是 | 48838 |

hidden 通过率为 4/4（100%）；补丁完整性为 4/4。主动提交为 1/4（25%），因为 `terminal_submitted` 是控制器终态，不计入主动提交。token 合计 202933，四条均 budget compliant。

Pydantic 运行早于补丁分类字段接入；现已根据原始 `patch.diff`、文件大小和 hidden 结果补写 `patch_status`、`patch_bytes`、`patch_sha256`。这些字段标记为 `patch_fields_source: posthoc_offline_verification`、`patch_fields_original_run: false`，属于后补核验，不是原始运行输出。其余三条结果直接包含门禁字段。

任务覆盖包含 Pydantic、HTTPX、Werkzeug 三个仓库，缺陷涉及类型语义、URL 编码、URL 活动/状态行为和认证头格式；但 HTTPX 有两条同仓任务，规模仍小，且 v10 曾在 HTTPX/Werkzeug 终态出现过兼容服务工具选择异常，随后重跑才恢复正常。

冻结条件已核对：v10 运行器 SHA256 `5da27d4221b4a4c0d9c8e22fae8f60f79455797179c808f1853e24bfdd49d642`，模型 `deepseek-flash`，总预算 64000，900 秒、40 轮、4000 guard，`tool_choice=required` 的 submit-only 终态和主机侧批次校验，输入哈希来自 `split_manifest.json`。四条 patch 文件大小、原始字节 SHA256、hidden 结果和终止原因一致性校验通过。

决策：development 审计收口通过，可以分别运行 Click/Jinja held-out；两条任务独立统计，golden 保持 0。
