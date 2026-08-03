"""Shared HTTP helpers for the thin server."""
from __future__ import annotations


def error_response(code: str, message: str, request_id: str, http_status: int = 400) -> tuple[int, dict]:
    return http_status, {
        "error": {"code": code, "message": message, "request_id": request_id}
    }
