"""读取随包发布的 HTTP 静态资源。"""
from __future__ import annotations

from importlib import resources


def docs_troubleshoot_ui_html() -> bytes:
    """返回文档排障页面的原始 UTF-8 HTML 字节。"""
    return (
        resources.files("react_agent.server.static")
        .joinpath("docs_troubleshoot_ui.html")
        .read_bytes()
    )


def expense_form_ui_html() -> bytes:
    """Return the standalone applicant form (no embedded business data)."""
    return resources.files("react_agent.server.static").joinpath("expense_form_ui.html").read_bytes()
