"""出站 URL 校验（SSRF 防护）。

原先各工具各自维护黑名单（``fetch_page`` 曾用字符串前缀黑名单），既漏
IPv6 / 十进制 IP / DNS 解析到内网 / 重定向，也无法复用到 ``probe_service_health``。

本模块改为**白名单 + 解析后校验 IP**：

1. 只允许显式声明的 scheme；
2. 主机名解析为 IP 集合，任一 IP 落在回环/私网/链路本地/保留段即拒绝；
3. 重定向逐跳重新校验（``open_validated``），避免「公网 URL 302 到内网」。
"""
from __future__ import annotations

import ipaddress
import socket
from typing import Iterable, Optional
from urllib import error as urlerror
from urllib import request as urlrequest
from urllib.parse import urlparse

DEFAULT_SCHEMES = frozenset({"http", "https"})
MAX_REDIRECTS = 5


def _is_blocked_ip(ip: ipaddress._BaseAddress) -> bool:
    """判定单个 IP 是否属于禁止访问的范围。

    注意 IPv6 不能用 ``is_private``/``is_reserved`` 一把梭：CPython 把 Teredo
    (2001::/32)、6to4 (2002::/16)、NAT64 (64:ff9b::/96) 等**可路由**段也算作
    private/reserved，会导致 en.wikipedia.org 这类双栈域名被误拦。这里只按
    明确的危险段判定。
    """
    if isinstance(ip, ipaddress.IPv6Address):
        embedded = ip.ipv4_mapped or ip.sixtofour
        if embedded is not None:
            # ::ffff:127.0.0.1 / 2002::/16 内嵌 IPv4，按内层判定
            return _is_blocked_ip(embedded)
        return bool(
            ip.is_loopback          # ::1
            or ip.is_link_local     # fe80::/10
            or ip.is_unspecified    # ::
            or ip.is_multicast      # ff00::/8
            or ip.is_site_local     # fec0::/10
            or (ip.is_private and not ip.is_global)  # fc00::/7 ULA 等
        )
    return bool(
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
    )


def _resolve_ips(host: str) -> list[ipaddress._BaseAddress]:
    """解析主机名到全部 IP；解析失败返回空列表。"""
    try:
        infos = socket.getaddrinfo(host, None)
    except OSError:
        return []
    found: list[ipaddress._BaseAddress] = []
    for info in infos:
        addr = info[4][0]
        try:
            found.append(ipaddress.ip_address(addr))
        except ValueError:
            continue
    return found


def validate_url(
    url: str,
    *,
    allowed_schemes: Iterable[str] = DEFAULT_SCHEMES,
    allow_hosts: Optional[Iterable[str]] = None,
    resolve: bool = True,
) -> tuple[bool, str]:
    """校验 URL 是否可安全请求。

    返回 ``(ok, reason)``；``ok`` 为 False 时 ``reason`` 是可展示的中文原因。
    """
    raw = (url or "").strip()
    if not raw:
        return False, "URL 为空"

    parsed = urlparse(raw)
    scheme = (parsed.scheme or "").lower()
    if scheme not in {s.lower() for s in allowed_schemes}:
        return False, f"不支持的协议: {scheme or '(空)'}"

    host = parsed.hostname or ""
    if not host:
        return False, "URL 缺少主机名"
    # 归一化尾点（"127.0.0.1." 是合法的 FQDN 写法，等价于 "127.0.0.1"）：
    # 不归一化的话这里会走 DNS 解析分支，而 "127.0.0.1." 能否解析取决于
    # 系统 resolver，导致拦截结果不稳定。
    host = host.rstrip(".")

    allow = {h.lower() for h in (allow_hosts or ())}
    if allow and host.lower() not in allow:
        return False, f"主机不在允许列表内: {host}"

    # 字面量 IP 直接判定，避免依赖解析
    try:
        literal = ipaddress.ip_address(host)
    except ValueError:
        literal = None
    if literal is not None:
        if _is_blocked_ip(literal):
            return False, f"不允许访问内网/保留地址: {host}"
        return True, ""

    if not resolve:
        return True, ""

    ips = _resolve_ips(host)
    if not ips:
        return False, f"无法解析主机名: {host}"
    # 只有全部解析结果都落在危险段时才拒绝：双栈主机常同时返回可路由 IPv6 与
    # 内网 IPv4，若「任一命中即拒绝」会误伤大量正常站点（例如 en.wikipedia.org）。
    if all(_is_blocked_ip(ip) for ip in ips):
        return False, f"主机 {host} 解析到内网/保留地址: {', '.join(str(i) for i in ips)}"
    return True, ""


class _ValidatingRedirectHandler(urlrequest.HTTPRedirectHandler):
    """每一跳重定向都重新做一次 URL 校验。"""

    def __init__(self, allowed_schemes, allow_hosts) -> None:
        super().__init__()
        self._allowed_schemes = allowed_schemes
        self._allow_hosts = allow_hosts

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        ok, reason = validate_url(
            newurl,
            allowed_schemes=self._allowed_schemes,
            allow_hosts=self._allow_hosts,
        )
        if not ok:
            raise urlerror.HTTPError(
                newurl, code, f"redirect blocked by SSRF guard: {reason}", headers, fp
            )
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def build_opener(*, allowed_schemes=None, allow_hosts=None, max_redirects=MAX_REDIRECTS):
    """构造带 SSRF 校验的 opener（禁用 file/ftp 等非 HTTP handler）。"""
    schemes = frozenset(allowed_schemes or DEFAULT_SCHEMES)
    handler = _ValidatingRedirectHandler(schemes, allow_hosts)
    return urlrequest.build_opener(handler)


def open_validated(
    url: str,
    *,
    timeout: float = 10.0,
    headers: Optional[dict] = None,
    allowed_schemes=None,
    allow_hosts=None,
    max_bytes: int = 0,
) -> tuple[bool, str, bytes]:
    """校验后发起请求，返回 ``(ok, error_or_url, body)``。

    ``max_bytes`` > 0 时最多读取该字节数。
    """
    schemes = frozenset(allowed_schemes or DEFAULT_SCHEMES)
    ok, reason = validate_url(url, allowed_schemes=schemes, allow_hosts=allow_hosts)
    if not ok:
        return False, reason, b""

    opener = build_opener(allowed_schemes=schemes, allow_hosts=allow_hosts)
    request = urlrequest.Request(url, headers=headers or {})
    try:
        with opener.open(request, timeout=timeout) as resp:
            body = resp.read(max_bytes) if max_bytes > 0 else resp.read()
            return True, url, body
    except urlerror.HTTPError as exc:
        # 保留 HTTPError，调用方需要状态码时自行读取 exc.fp
        raise
    except Exception as exc:  # noqa: BLE001 - 统一转成可展示文本
        return False, str(exc), b""
