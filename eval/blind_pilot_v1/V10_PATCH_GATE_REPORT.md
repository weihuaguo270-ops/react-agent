# v10 补丁完整性门禁报告（2026-09-22）

离线校验确认：

- HTTPX identity 既有成功运行：patch 非空、hidden passed；当前所核对运行目录的 patch 为 562 bytes。
- Pydantic v10 既有成功运行：patch 非空、hidden passed；当前所核对运行目录的 patch 为 1415 bytes。

运行器已加入 `patch_status` 分类：`patch_empty`、`patch_invalid`、`hidden_failed`、`verified_fix`。结果同时写入 patch 字节数和 SHA256；`terminal_submitted` 仍只表示终态调用，不表示修复有效。

HTTPX identity 门禁重跑结果：`dev-v10-httpx-identity-patch-gate-20260922-124514`，`terminal_submitted`、`verified_fix`、hidden passed、51707 tokens、budget compliant；patch 562 bytes，SHA256 `efbebdcbe36ecdf13f8073f167e63619b1828546be97b13de9ad614b58b1b2ac`。该次没有 protocol violation。

17 项离线测试和语法检查通过。Click/Jinja held-out 未运行，golden 仍为 0。
