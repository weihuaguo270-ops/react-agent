"""Bundled static assets for the thin HTTP server (stdlib only)."""
from __future__ import annotations

from importlib import resources


def docs_troubleshoot_ui_html() -> bytes:
    return (
        resources.files("react_agent.server.static")
        .joinpath("docs_troubleshoot_ui.html")
        .read_bytes()
    )
