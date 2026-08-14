"""轻量 HTTP 服务的存活与就绪探针。"""
from __future__ import annotations

import os
from typing import Any


def package_version() -> str:
    """读取已安装包版本；源码运行时使用兼容版本号。"""
    try:
        from importlib.metadata import version

        return version("react-agent")
    except Exception:
        return "0.7.0"


def _default_app() -> str:
    """返回服务启动时实际使用的默认应用。"""
    return (
        os.environ.get("REACT_AGENT_DEFAULT_APP")
        or os.environ.get("REACT_AGENT_APP")
        or "docs_troubleshoot"
    ).strip()


def liveness_payload(*, request_id: str) -> dict[str, Any]:
    """构造不访问外部依赖的存活响应。"""
    return {
        "status": "ok",
        "version": package_version(),
        "default_app": _default_app(),
        "request_id": request_id,
    }


def readiness_check() -> tuple[bool, dict[str, Any]]:
    """检查 Sandbox 后端和默认应用的必要依赖。"""
    from react_agent.harness import SANDBOX

    app = _default_app()
    sandbox_status = SANDBOX.status()
    if SANDBOX.required:
        # required 模式必须失败关闭，不能在容器不可用时降级到宿主执行。
        ready, error = SANDBOX.verify_runtime()
        sandbox_status = SANDBOX.status()
        if not ready:
            return False, {
                "app": app,
                "reason": "sandbox_unavailable",
                "error": str(error or "")[:200],
                "sandbox": sandbox_status,
            }
    if app != "docs_troubleshoot":
        return True, {
            "app": app,
            "reason": "non_docs_app_skipped",
            "sandbox": sandbox_status,
        }

    try:
        # 文档应用只有在索引非空时才能提供有依据的回答。
        from react_agent.apps.docs_troubleshoot.index import get_index

        idx = get_index()
        n = len(getattr(idx, "chunks", []) or [])
        if n <= 0:
            return False, {
                "app": app,
                "chunks": 0,
                "reason": "empty_index",
                "sandbox": sandbox_status,
            }
        return True, {
            "app": app,
            "chunks": n,
            "rag_mode": os.environ.get("REACT_AGENT_RAG_MODE", ""),
            "sandbox": sandbox_status,
        }
    except Exception as exc:
        return False, {
            "app": app,
            "reason": "index_error",
            "error": str(exc)[:200],
            "sandbox": sandbox_status,
        }


def readiness_payload(*, request_id: str) -> tuple[int, dict[str, Any]]:
    """将就绪检查转换为 HTTP 状态码和响应体。"""
    ok, details = readiness_check()
    payload: dict[str, Any] = {
        "status": "ready" if ok else "not_ready",
        "version": package_version(),
        "request_id": request_id,
        **details,
    }
    return (200 if ok else 503), payload
