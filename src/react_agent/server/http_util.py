"""轻量 HTTP 服务共享的响应辅助函数。"""
from __future__ import annotations

from typing import Any


def error_response(
    code: str,
    message: str,
    request_id: str,
    http_status: int = 400,
) -> tuple[int, dict[str, Any]]:
    """构造统一错误信封，保留跨日志关联所需的 request id。"""
    return http_status, {
        "error": {"code": code, "message": message, "request_id": request_id}
    }
