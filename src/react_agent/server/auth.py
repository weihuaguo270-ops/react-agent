"""Shared auth / Host validation for both HTTP surfaces.

The HTTP surface is unauthenticated by default for local development.  Setting
``REACT_AGENT_AUTH_TOKEN`` turns on a shared-secret Bearer check for every
endpoint except liveness/readiness probes.

stdlib 服务面（``server/app.py``）与 FastAPI 服务面（``server/fastapi_app.py``）
共用这里的判定逻辑：两个入口点必须有同一套鉴权与 Host 校验语义，否则默认入口
（容器里的 ``react-agent-api``）会静默少一道防线。
"""
from __future__ import annotations

import hmac
import os
from http.server import BaseHTTPRequestHandler
from typing import Any

AUTH_TOKEN_ENV = "REACT_AGENT_AUTH_TOKEN"

# 历史别名：FastAPI 服务面早期读的是 ``REACT_AGENT_API_KEY``，文档从未记录过它。
# 保留兼容以免打断已有部署；两者同时设置时 ``REACT_AGENT_AUTH_TOKEN`` 优先。
LEGACY_AUTH_TOKEN_ENVS = ("REACT_AGENT_API_KEY",)

# Probes stay open so container orchestrators can health-check without a secret.
PUBLIC_PATHS = frozenset(
    {
        "/health",
        "/v1/health",
        "/ready",
        "/v1/ready",
    }
)


def auth_token() -> str:
    for name in (AUTH_TOKEN_ENV, *LEGACY_AUTH_TOKEN_ENVS):
        value = os.environ.get(name, "").strip()
        if value:
            return value
    return ""


def auth_enabled() -> bool:
    return bool(auth_token())


def _extract_bearer(header_value: str) -> str:
    value = (header_value or "").strip()
    if not value:
        return ""
    parts = value.split(None, 1)
    if len(parts) == 2 and parts[0].lower() == "bearer":
        return parts[1].strip()
    return ""


def extract_credential(headers: Any) -> str:
    """从请求头取凭据：``Authorization: Bearer <token>``，其次 ``X-Api-Key``。

    ``headers`` 只需支持大小写不敏感的 ``.get()``——``http.server`` 的
    ``self.headers``（``email.message.Message``）与 Starlette 的 ``Headers``
    都满足，因此两个服务面共用同一取值顺序。
    """
    provided = _extract_bearer(str(headers.get("Authorization") or ""))
    if provided:
        return provided
    return str(headers.get("X-Api-Key") or "").strip()


def authorized_headers(headers: Any, path: str) -> bool:
    """header 版鉴权判定，供 ASGI 侧直接调用。"""
    if path in PUBLIC_PATHS:
        return True
    token = auth_token()
    if not token:
        # No token configured: keep local-dev behaviour, but do not silently
        # accept credentials that were never provisioned.
        return True
    return hmac.compare_digest(extract_credential(headers), token)


def authorized(handler: BaseHTTPRequestHandler, path: str) -> bool:
    """Return True when the request may proceed (including the open-probe case)."""
    return authorized_headers(handler.headers, path)


def is_loopback_host(host: str) -> bool:
    normalized = (host or "").strip().strip("[]").lower()
    return normalized in {"127.0.0.1", "localhost", "::1", ""}


# ── Host 头校验（防 DNS rebinding） ──
# 浏览器会按 URL 里的主机名填 Host。攻击者用 DNS rebinding 把自己的域名重新解析到
# 本机地址，浏览器即视作同源，可读取本应只属于本机的响应。校验 Host 是唯一能挡住
# 这条链的手段（不发 CORS 头只能阻止「跨源读取」，挡不住 rebinding 的「同源读取」）。
_HOST_ALLOW_ENV = "REACT_AGENT_ALLOWED_HOSTS"
_HOST_VALIDATION_ENV = "REACT_AGENT_HOST_VALIDATION"
_HOST_REQUIRE_ALLOWLIST_ENV = "REACT_AGENT_REQUIRE_HOST_ALLOWLIST"
_LOOPBACK_HOSTNAMES = {"127.0.0.1", "localhost", "::1"}

# 三档模式
_HOST_MODE_LOOPBACK = "loopback"      # (a) 默认：只放行本地形态 + 显式白名单
_HOST_MODE_ALLOWLIST = "allowlist"    # (b) 严格：必须显式声明，否则拒绝启动
_HOST_MODE_PERMISSIVE = "permissive"  # 应急逃生口：不校验（等价于旧行为）


class HostValidationError(RuntimeError):
    """启动期 Host 校验配置非法。"""


def _strip_port(host_header: str) -> str:
    value = (host_header or "").strip().lower()
    if value.startswith("["):  # [::1]:8765
        return value.split("]")[0].lstrip("[")
    return value.split(":")[0]


def allowed_hosts() -> set[str]:
    extra = os.environ.get(_HOST_ALLOW_ENV, "")
    return {h.strip().lower() for h in extra.split(",") if h.strip()}


def _env_truthy(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


def host_validation_mode() -> str:
    """当前 Host 校验档位。REQUIRE_HOST_ALLOWLIST 优先于 HOST_VALIDATION。"""
    if _env_truthy(_HOST_REQUIRE_ALLOWLIST_ENV):
        return _HOST_MODE_ALLOWLIST
    raw = os.environ.get(_HOST_VALIDATION_ENV, "").strip().lower()
    if raw in {_HOST_MODE_ALLOWLIST, _HOST_MODE_PERMISSIVE, _HOST_MODE_LOOPBACK}:
        return raw
    if raw:
        raise HostValidationError(
            f"{_HOST_VALIDATION_ENV} 取值非法: {raw!r}；"
            f"可选 {_HOST_MODE_LOOPBACK} / {_HOST_MODE_ALLOWLIST} / {_HOST_MODE_PERMISSIVE}"
        )
    return _HOST_MODE_LOOPBACK


def allowed_bind_hosts(bind_host: str) -> set[str]:
    """绑定地址本身（含常见 0.0.0.0 场景下的本机名）视为合法 Host。"""
    raw = (bind_host or "").strip().lower()
    if not raw:
        return set()
    normalized = raw.strip("[]")
    if normalized in {"0.0.0.0", "::", ""}:
        # 通配绑定：直连本机时客户端可能用 localhost / 127.0.0.1
        return set(_LOOPBACK_HOSTNAMES)
    return {_strip_port(raw) or normalized}


def validate_host_configuration(bind_host: str) -> None:
    """启动期检查。严格模式下未显式声明域名即拒绝启动（fail-closed）。"""
    mode = host_validation_mode()
    if mode != _HOST_MODE_ALLOWLIST:
        return
    if not is_loopback_host(bind_host) and not allowed_hosts():
        raise HostValidationError(
            f"{_HOST_REQUIRE_ALLOWLIST_ENV}=1 要求显式声明 {_HOST_ALLOW_ENV}："
            f"绑定到 {bind_host!r} 时无法推断合法 Host，服务拒绝启动。"
            f"请设置 {_HOST_ALLOW_ENV}=your.host.example，"
            f"或改用 {_HOST_VALIDATION_ENV}={_HOST_MODE_LOOPBACK}，"
            f"或在确认仅本机可达时绑定 127.0.0.1。"
        )


def host_header_allowed(host_header: str, bind_host: str) -> bool:
    """按当前档位校验 Host 头（header 版，供 ASGI 侧直接调用）。"""
    mode = host_validation_mode()
    if mode == _HOST_MODE_PERMISSIVE:
        return True

    if not host_header:
        # HTTP/1.0 客户端可能不带 Host，不阻断
        return True

    hostname = _strip_port(host_header)
    if not hostname:
        return False

    declared = allowed_hosts()
    if declared:
        # 显式声明过域名：以声明为准（(a) 与 (b) 在此统一）
        return hostname in declared or hostname in allowed_bind_hosts(bind_host) \
            or hostname in _LOOPBACK_HOSTNAMES

    if mode == _HOST_MODE_ALLOWLIST:
        # 严格模式在启动期已强制要求声明；到这里说明是回环绑定
        return hostname in _LOOPBACK_HOSTNAMES or hostname in allowed_bind_hosts(bind_host)

    # (a) 默认档：本地形态 + 绑定地址放行，其余一律拒绝
    if hostname in _LOOPBACK_HOSTNAMES:
        return True
    if hostname in allowed_bind_hosts(bind_host):
        return True
    return False


def host_allowed(handler: BaseHTTPRequestHandler, bind_host: str) -> bool:
    """按当前档位校验 Host 头。"""
    return host_header_allowed(handler.headers.get("Host", ""), bind_host)


def unauthenticated_exposure_warning(host: str) -> str | None:
    """Warn when the server is reachable off-host without a token configured."""
    if auth_enabled() or is_loopback_host(host):
        return None
    return (
        f"[server] WARNING: binding to {host!r} with no {AUTH_TOKEN_ENV} set; "
        "the HTTP API (including code execution) is reachable without authentication. "
        f"Set {AUTH_TOKEN_ENV} or bind to 127.0.0.1."
    )
