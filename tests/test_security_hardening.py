"""安全修复回归测试。

覆盖以下边界的防回归断言（每条对应一次已被修复的缺陷）：

1. HTTP 鉴权与 Host 头校验（DNS rebinding / 未授权访问）
2. 控制面工具 ``toggle_sandbox`` 不可被模型触达
3. 未知工具权限默认失败关闭
4. SSRF 守卫（``net_guard``）的绕过向量
5. ``probe_service_health`` / ``read_config_snapshot`` 的输入约束
6. MCP 与沙箱子进程的环境白名单（含代理凭据）
7. ``trace_id`` 路径穿越
8. git origin 子串校验绕过
9. 轨迹落盘脱敏
"""
from __future__ import annotations

import json
import os
import socket
import sys
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

# ── HTTP 测试辅助：用原始 socket 才能自定义 Host 头 ──


def _read_response(sock: socket.socket) -> tuple[int, dict[str, str], str]:
    chunks: list[bytes] = []
    while True:
        data = sock.recv(65536)
        if not data:
            break
        chunks.append(data)
        joined = b"".join(chunks)
        header_end = joined.find(b"\r\n\r\n")
        if header_end == -1:
            continue
        head = joined[:header_end].decode("iso-8859-1")
        length = 0
        for line in head.split("\r\n")[1:]:
            if line.lower().startswith("content-length:"):
                length = int(line.split(":", 1)[1].strip())
                break
        if len(joined) - (header_end + 4) >= length:
            break
    raw = b"".join(chunks)
    header_end = raw.find(b"\r\n\r\n")
    head = raw[:header_end].decode("iso-8859-1") if header_end != -1 else ""
    body = raw[header_end + 4:].decode("utf-8", "replace") if header_end != -1 else ""
    lines = head.split("\r\n")
    status = int(lines[0].split()[1]) if lines and len(lines[0].split()) > 1 else 0
    headers: dict[str, str] = {}
    for line in lines[1:]:
        if ":" in line:
            name, value = line.split(":", 1)
            headers[name.strip().lower()] = value.strip()
    return status, headers, body


def _request(
    port: int,
    path: str,
    *,
    method: str = "GET",
    host: str | None = None,
    token: str | None = None,
    body: dict | None = None,
    content_type: str = "application/json",
) -> tuple[int, dict[str, str], str]:
    payload = b"" if body is None else json.dumps(body).encode()
    lines = [f"{method} {path} HTTP/1.1"]
    if host is not None:
        lines.append(f"Host: {host}")
    else:
        lines.append(f"Host: 127.0.0.1:{port}")
    if token:
        lines.append(f"Authorization: Bearer {token}")
    if body is not None:
        lines.append(f"Content-Type: {content_type}")
        lines.append(f"Content-Length: {len(payload)}")
    lines.append("Connection: close")
    request = ("\r\n".join(lines) + "\r\n\r\n").encode() + payload

    # 每次请求新建连接：服务器用 Connection: close，复用套接字会拿到
    # ConnectionAbortedError（WinError 10053）而不是响应。
    with socket.create_connection(("127.0.0.1", port), timeout=10) as sock:
        sock.sendall(request)
        return _read_response(sock)


class _Server:
    # 这些变量会影响校验档位，测试间必须互不污染
    _ISOLATED_ENV = (
        "REACT_AGENT_AUTH_TOKEN",
        # 历史别名：server/auth.py 仍认它，留在环境里会静默打开鉴权
        "REACT_AGENT_API_KEY",
        "REACT_AGENT_ALLOWED_HOSTS",
        "REACT_AGENT_HOST_VALIDATION",
        "REACT_AGENT_REQUIRE_HOST_ALLOWLIST",
    )

    def __init__(
        self,
        *,
        token: str | None = None,
        bind: str = "127.0.0.1",
        keep_env: tuple[str, ...] = (),
    ):
        for key in self._ISOLATED_ENV:
            if key in keep_env:
                continue
            os.environ.pop(key, None)
        if token is not None:
            os.environ["REACT_AGENT_AUTH_TOKEN"] = token
        from react_agent.server.app import AgentHandler

        self.httpd = ThreadingHTTPServer((bind, 0), AgentHandler)
        self.port = self.httpd.server_address[1]
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    def close(self) -> None:
        self.httpd.shutdown()
        self.thread.join(timeout=5)


@pytest.fixture
def open_server(monkeypatch):
    """未配置 token 的服务器（本地默认形态）。"""
    monkeypatch.delenv("REACT_AGENT_AUTH_TOKEN", raising=False)
    server = _Server()
    try:
        yield server
    finally:
        server.close()
        os.environ.pop("REACT_AGENT_AUTH_TOKEN", None)


@pytest.fixture
def token_server(monkeypatch):
    """配置了 Bearer token 的服务器。"""
    server = _Server(token="test-token-value")
    try:
        yield server
    finally:
        server.close()
        os.environ.pop("REACT_AGENT_AUTH_TOKEN", None)


# ── 1. HTTP 鉴权 ──


def test_probe_endpoints_stay_public_without_token(token_server):
    for path in ("/health", "/ready"):
        status, _, _ = _request(token_server.port, path)
        assert status == 200, path

def test_protected_endpoints_require_token(token_server):
    for path, method in (
        ("/v1/info", "GET"),
        ("/v1/chat", "POST"),
        ("/v1/chat/stream", "GET"),
        ("/v1/workflows", "GET"),
    ):
        status, headers, _ = _request(token_server.port, path, method=method, body={} if method == "POST" else None)
        assert status == 401, f"{method} {path}"
        assert headers.get("www-authenticate") == "Bearer"


def test_valid_token_is_accepted(token_server):
    status, _, body = _request(token_server.port, "/v1/info", token="test-token-value")
    assert status == 200
    assert "react-agent" in body


def test_wrong_token_is_rejected(token_server):
    status, _, _ = _request(token_server.port, "/v1/info", token="wrong-token")
    assert status == 401


def test_x_api_key_header_is_accepted(token_server):
    status, _, _ = _request_header_api_key(token_server.port, "test-token-value")
    assert status == 200


def _request_header_api_key(port: int, key: str) -> tuple[int, dict, str]:
    request = (
        f"GET /v1/info HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\n"
        f"X-Api-Key: {key}\r\nConnection: close\r\n\r\n"
    ).encode()
    with socket.create_connection(("127.0.0.1", port), timeout=10) as sock:
        sock.sendall(request)
        return _read_response(sock)


def test_no_token_keeps_local_development_open(open_server):
    status, _, _ = _request(open_server.port, "/v1/info")
    assert status == 200


# ── 2. Host 头校验（DNS rebinding） ──


@pytest.mark.parametrize(
    "host",
    [
        "127.0.0.1",
        "127.0.0.1:{port}",
        "localhost:8765",
        "[::1]:8765",
    ],
)
def test_loopback_hosts_accepted(open_server, host):
    resolved = host.format(port=open_server.port)
    status, _, _ = _request(open_server.port, "/v1/info", host=resolved)
    assert status == 200, resolved


@pytest.mark.parametrize(
    "host",
    [
        "attacker.example.com",
        "evil.tld:8765",
        "169.254.169.254",
        "metadata.google.internal",
        "127.0.0.1.nip.io",
    ],
)
def test_non_loopback_host_rejected_when_bound_to_loopback(open_server, host):
    status, _, _ = _request(open_server.port, "/v1/info", host=host)
    assert status == 421, host


def test_host_check_runs_before_auth(token_server):
    # 伪造 Host 且无凭据：必须是 421（Host 问题），不能返回 401 暴露接口存在
    status, _, _ = _request(token_server.port, "/v1/info", host="evil.tld")
    assert status == 421


def test_host_allowlist_override(monkeypatch):
    monkeypatch.setenv("REACT_AGENT_ALLOWED_HOSTS", "api.internal,app.example.com")
    server = _Server(keep_env=("REACT_AGENT_ALLOWED_HOSTS",))
    try:
        for host in ("api.internal", "app.example.com"):
            status, _, _ = _request(server.port, "/v1/info", host=host)
            assert status == 200, host
        status, _, _ = _request(server.port, "/v1/info", host="other.tld")
        assert status == 421
    finally:
        server.close()
        os.environ.pop("REACT_AGENT_AUTH_TOKEN", None)


def test_bound_to_all_interfaces_still_validates_host(monkeypatch):
    """(a) 默认档：绑定 0.0.0.0 时仍拒绝非本地 Host（此前是完全放行）。"""
    monkeypatch.delenv("REACT_AGENT_ALLOWED_HOSTS", raising=False)
    monkeypatch.delenv("REACT_AGENT_HOST_VALIDATION", raising=False)
    monkeypatch.delenv("REACT_AGENT_REQUIRE_HOST_ALLOWLIST", raising=False)
    server = _Server(bind="0.0.0.0")
    try:
        # 本地形态放行
        for host in ("127.0.0.1", "localhost", "127.0.0.1:%d" % server.port):
            status, _, _ = _request(server.port, "/v1/info", host=host)
            assert status == 200, host
        # 外部域名（DNS rebinding 的 Host）被拒
        for host in ("attacker.example.com", "169.254.169.254"):
            status, _, _ = _request(server.port, "/v1/info", host=host)
            assert status == 421, host
    finally:
        server.close()
        os.environ.pop("REACT_AGENT_AUTH_TOKEN", None)


def test_allowed_bind_host_itself_is_accepted(monkeypatch):
    """绑定到具体 IP 时，直连该 IP 的 Host 应被接受。"""
    monkeypatch.delenv("REACT_AGENT_ALLOWED_HOSTS", raising=False)
    server = _Server(bind="127.0.0.1")
    try:
        status, _, _ = _request(server.port, "/v1/info", host=f"127.0.0.1:{server.port}")
        assert status == 200
    finally:
        server.close()
        os.environ.pop("REACT_AGENT_AUTH_TOKEN", None)


def test_permissive_mode_escape_hatch(monkeypatch):
    monkeypatch.setenv("REACT_AGENT_HOST_VALIDATION", "permissive")
    server = _Server(keep_env=("REACT_AGENT_HOST_VALIDATION",))
    try:
        status, _, _ = _request(server.port, "/v1/info", host="attacker.example.com")
        assert status == 200
    finally:
        server.close()
        os.environ.pop("REACT_AGENT_AUTH_TOKEN", None)


def test_invalid_validation_mode_is_rejected(monkeypatch):
    from react_agent.server.auth import HostValidationError, host_validation_mode

    monkeypatch.setenv("REACT_AGENT_HOST_VALIDATION", "nonsense")
    with pytest.raises(HostValidationError):
        host_validation_mode()


# ── (b) 严格模式：未声明允许域名则拒绝启动 ──


def test_strict_mode_rejects_startup_without_allowlist(monkeypatch):
    from react_agent.server.auth import HostValidationError, validate_host_configuration

    monkeypatch.setenv("REACT_AGENT_REQUIRE_HOST_ALLOWLIST", "1")
    monkeypatch.delenv("REACT_AGENT_ALLOWED_HOSTS", raising=False)
    with pytest.raises(HostValidationError, match="REACT_AGENT_ALLOWED_HOSTS"):
        validate_host_configuration("0.0.0.0")


def test_strict_mode_passes_once_allowlist_declared(monkeypatch):
    from react_agent.server.auth import validate_host_configuration

    monkeypatch.setenv("REACT_AGENT_REQUIRE_HOST_ALLOWLIST", "1")
    monkeypatch.setenv("REACT_AGENT_ALLOWED_HOSTS", "api.example.com")
    validate_host_configuration("0.0.0.0")  # 不抛异常即通过


def test_strict_mode_allows_loopback_bind_without_allowlist(monkeypatch):
    from react_agent.server.auth import validate_host_configuration

    monkeypatch.setenv("REACT_AGENT_REQUIRE_HOST_ALLOWLIST", "1")
    monkeypatch.delenv("REACT_AGENT_ALLOWED_HOSTS", raising=False)
    validate_host_configuration("127.0.0.1")


def test_strict_mode_enforced_end_to_end(monkeypatch):
    """严格模式下只有声明的域名能通过。"""
    monkeypatch.setenv("REACT_AGENT_REQUIRE_HOST_ALLOWLIST", "1")
    monkeypatch.setenv("REACT_AGENT_ALLOWED_HOSTS", "api.example.com")
    server = _Server(
        keep_env=("REACT_AGENT_ALLOWED_HOSTS", "REACT_AGENT_REQUIRE_HOST_ALLOWLIST")
    )
    try:
        status, _, _ = _request(server.port, "/v1/info", host="api.example.com")
        assert status == 200
        status, _, _ = _request(server.port, "/v1/info", host="evil.tld")
        assert status == 421
    finally:
        server.close()
        os.environ.pop("REACT_AGENT_AUTH_TOKEN", None)


@pytest.mark.parametrize(
    "host",
    [
        "api.internal",
        "app.example.com",
    ],
)
def test_declared_allowlist_accepted_in_default_mode(monkeypatch, host):
    monkeypatch.setenv("REACT_AGENT_ALLOWED_HOSTS", "api.internal,app.example.com")
    monkeypatch.delenv("REACT_AGENT_REQUIRE_HOST_ALLOWLIST", raising=False)
    server = _Server(keep_env=("REACT_AGENT_ALLOWED_HOSTS",))
    try:
        status, _, _ = _request(server.port, "/v1/info", host=host)
        assert status == 200, host
    finally:
        server.close()
        os.environ.pop("REACT_AGENT_AUTH_TOKEN", None)


def test_auth_disabled_when_no_token_and_public_paths_always_open(open_server):
    status, _, _ = _request(open_server.port, "/health", host="attacker.example.com")
    # /health 属公开探针，但 Host 校验仍先执行
    assert status == 421


# ── 3. 控制面工具不可被模型触达 ──


def test_toggle_sandbox_is_not_model_visible():
    from react_agent.tools import TOOL_DEFINITIONS, TOOL_REGISTRY

    names = {d["function"]["name"] for d in TOOL_DEFINITIONS if "function" in d}
    assert "toggle_sandbox" not in names
    assert "toggle_sandbox" not in TOOL_REGISTRY


def test_toggle_sandbox_still_guarded_by_permission():
    from react_agent.safety.permissions import PermissionLevel, evaluate_tool_permission

    decision = evaluate_tool_permission("toggle_sandbox", {"strategy": "off"})
    assert decision.level is PermissionLevel.CONFIRM
    assert decision.outcome == "ask"


def test_model_cannot_disable_sandbox_through_registry():
    """回归：此前模型可经注册表调用 toggle_sandbox 把策略切到 off。"""
    from react_agent.harness.sandbox import SANDBOX
    from react_agent.react_loop import _execute_tool_call_raw

    before = SANDBOX.strategy
    result = _execute_tool_call_raw(
        {"function": {"name": "toggle_sandbox", "arguments": json.dumps({"strategy": "off"})}}
    )
    assert SANDBOX.strategy == before, "沙箱策略被模型改动"
    # 工具已不在注册表：派发返回未知工具错误（JSON 里中文是 \uXXXX 转义）
    assert "未知工具" in json.loads(result)["error"]


# ── 4. 权限默认失败关闭 ──


def test_unknown_tool_defaults_to_confirm():
    from react_agent.safety.permissions import (
        DEFAULT_PERMISSION,
        PermissionLevel,
        evaluate_tool_permission,
    )

    assert DEFAULT_PERMISSION is PermissionLevel.CONFIRM
    decision = evaluate_tool_permission("brand_new_unlisted_tool", {})
    assert decision.outcome == "ask"
    assert decision.source == "default_confirm"


def test_sensitive_tools_are_not_safe():
    from react_agent.safety.permissions import PermissionLevel, evaluate_tool_permission

    for tool in ("read_config_snapshot", "probe_service_health"):
        decision = evaluate_tool_permission(tool, {})
        assert decision.level is PermissionLevel.CONFIRM_READ, tool
        assert decision.outcome == "ask"
    for tool in ("fetch_trace", "clear_trajectories"):
        decision = evaluate_tool_permission(tool, {})
        assert decision.level is PermissionLevel.CONFIRM, tool
        assert decision.outcome == "ask"


def test_registry_tools_are_explicitly_classified():
    """除良性控制面外，注册表中的工具都应在权限表里被显式标注。"""
    from react_agent.tools import TOOL_REGISTRY
    from react_agent.safety.permissions import TOOL_PERMISSIONS, PermissionLevel

    control_plane = {"switch_cot_strategy", "switch_role", "switch_context_strategy"}
    unclassified = set(TOOL_REGISTRY) - set(TOOL_PERMISSIONS) - control_plane
    assert unclassified == set(), f"未显式分类: {sorted(unclassified)}"


# ── 5. SSRF 守卫 ──


BLOCKED_URLS = [
    "http://169.254.169.254/latest/meta-data/",
    "http://[::1]:8765/v1/info",
    "http://[::ffff:127.0.0.1]:8765/v1/info",
    "http://127.0.0.1:8765/health",
    "http://127.0.0.2:8765/",
    "http://127.0.0.1./",
    "http://LOCALHOST/",
    "http://2130706433:8765/",
    "http://0x7f000001:8765/",
    "http://[fd00::1]:8765/",
    "http://10.0.0.5:9200/",
    "http://192.168.1.1/",
    "file:///etc/passwd",
    "ftp://127.0.0.1/x",
    "gopher://127.0.0.1:70/_x",
    "http:///nohost",
    "",
]


@pytest.mark.parametrize("url", BLOCKED_URLS)
def test_ssrf_guard_blocks_internal_targets(url):
    from react_agent.safety.net_guard import validate_url

    ok, reason = validate_url(url)
    assert ok is False, f"未拦截: {url}"
    assert reason


@pytest.mark.parametrize("url", ["https://example.com/", "http://example.com/a/b?c=1"])
def test_ssrf_guard_allows_public_http(url):
    from react_agent.safety.net_guard import validate_url

    ok, _ = validate_url(url)
    assert ok is True, url


def test_ssrf_guard_rejects_disallowed_scheme():
    from react_agent.safety.net_guard import validate_url

    ok, reason = validate_url("https://example.com/", allowed_schemes={"http"})
    assert ok is False
    assert "协议" in reason


def test_ssrf_guard_enforces_host_allowlist():
    from react_agent.safety.net_guard import validate_url

    # 不在白名单：先被 allow_hosts 拦下（不依赖 DNS）
    ok, reason = validate_url("https://b.example.com/", allow_hosts={"a.example.com"})
    assert ok is False
    assert "允许列表" in reason
    # 在白名单：通过 allow_hosts 后仍受 IP 校验约束，回环地址照旧被拒
    ok2, reason2 = validate_url("http://127.0.0.1:8765/", allow_hosts={"127.0.0.1"})
    assert ok2 is False
    assert "内网" in reason2


def test_redirect_handler_revalidates_target():
    """重定向到内网必须被拒（防「公网 URL 302 到 127.0.0.1」）。"""
    import urllib.error

    from react_agent.safety.net_guard import build_opener

    opener = build_opener()
    handler = next(
        h for h in opener.handlers if type(h).__name__ == "_ValidatingRedirectHandler"
    )
    with pytest.raises(urllib.error.HTTPError, match="redirect blocked"):
        handler.redirect_request(
            None, None, 302, "Found", {}, "http://169.254.169.254/latest/meta-data/"
        )


# ── 6. 证据采集入口的输入约束 ──


def test_probe_service_health_blocks_internal_targets():
    from react_agent.apps.docs_troubleshoot.evidence import probe_service_health

    for url in ("http://169.254.169.254/latest/meta-data/", "file:///C:/Windows/win.ini"):
        result = probe_service_health(url)
        assert result["ok"] is False
        assert "blocked" in result["error"]


def test_read_config_snapshot_restricts_prefix_namespace():
    from react_agent.apps.docs_troubleshoot.evidence import read_config_snapshot

    result = read_config_snapshot("A")
    assert result["ok"] is False
    assert result["rejected"] == ["A"]


def test_read_config_snapshot_allows_react_agent_prefix(monkeypatch):
    from react_agent.apps.docs_troubleshoot.evidence import read_config_snapshot

    monkeypatch.setenv("REACT_AGENT_PROBE_MARKER", "visible-value")
    result = read_config_snapshot("REACT_AGENT_PROBE_MARKER")
    assert result["ok"] is True
    assert result["env"]["REACT_AGENT_PROBE_MARKER"] == "visible-value"


def test_read_config_snapshot_redacts_secret_keys(monkeypatch):
    from react_agent.apps.docs_troubleshoot.evidence import read_config_snapshot

    monkeypatch.setenv("REACT_AGENT_FAKE_API_KEY", "sk-should-not-appear")
    result = read_config_snapshot("REACT_AGENT_FAKE_API_KEY")
    assert result["env"]["REACT_AGENT_FAKE_API_KEY"] == "<redacted>"


# ── 7. 子进程环境白名单 ──


SECRET_ENV = {
    "DEEPSEEK_API_KEY": "sk-host-secret",
    "OPENAI_API_KEY": "sk-host-secret-2",
    "GITHUB_TOKEN": "ghp_host_secret",
    "MCP_TOKEN": "mcp_host_secret",
    "LLM_API_KEY": "llm_host_secret",
}


def test_mcp_child_env_excludes_secrets(monkeypatch):
    from react_agent.mcp_client import _mcp_child_env

    for key, value in SECRET_ENV.items():
        monkeypatch.setenv(key, value)
    child = _mcp_child_env()
    for key in SECRET_ENV:
        assert key not in child, key
    assert "PATH" in child


def test_mcp_child_env_excludes_proxy_credentials_by_default(monkeypatch):
    from react_agent.mcp_client import _mcp_child_env

    monkeypatch.setenv("HTTP_PROXY", "http://user:pass@proxy:8080")
    monkeypatch.delenv("REACT_AGENT_MCP_ALLOW_PROXY", raising=False)
    assert "HTTP_PROXY" not in _mcp_child_env()


def test_mcp_child_env_proxy_is_opt_in(monkeypatch):
    from react_agent.mcp_client import _mcp_child_env

    monkeypatch.setenv("HTTP_PROXY", "http://user:pass@proxy:8080")
    monkeypatch.setenv("REACT_AGENT_MCP_ALLOW_PROXY", "1")
    assert _mcp_child_env()["HTTP_PROXY"] == "http://user:pass@proxy:8080"


def test_sandbox_runner_env_excludes_secrets_and_proxy(monkeypatch):
    from react_agent.harness.sandbox import _runner_env

    for key, value in SECRET_ENV.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setenv("HTTP_PROXY", "http://user:pass@proxy:8080")
    monkeypatch.delenv("REACT_AGENT_SANDBOX_ALLOW_PROXY", raising=False)
    child = _runner_env("calculator", 65536, 1048576)
    for key in SECRET_ENV:
        assert key not in child, key
    assert "HTTP_PROXY" not in child
    assert child["REACT_AGENT_SANDBOX_ALLOWED_TOOLS"] == "calculator"


def test_sandbox_runner_env_proxy_is_opt_in(monkeypatch):
    from react_agent.harness.sandbox import _runner_env

    monkeypatch.setenv("HTTP_PROXY", "http://user:pass@proxy:8080")
    monkeypatch.setenv("REACT_AGENT_SANDBOX_ALLOW_PROXY", "1")
    assert "HTTP_PROXY" in _runner_env("calculator", 65536, 1048576)


# ── 8. trace_id 路径穿越 ──


TRAVERSAL_IDS = [
    "../secret",
    "../../secret",
    "..\\secret",
    "....//secret",
    "C:/Windows/win",
    "C:\\Windows\\win",
    "/etc/passwd",
    "valid/../../secret",
    "..",
    ".",
    "",
    "a" * 200,
]


@pytest.mark.parametrize("trace_id", TRAVERSAL_IDS)
def test_trace_id_traversal_rejected(trace_id):
    from react_agent.apps.docs_troubleshoot.trace_backend import fetch_trace_bundle

    result = fetch_trace_bundle(trace_id)
    assert result["ok"] is False
    # 必须由白名单明确拒绝，而不是「文件不存在」这类偶然通过
    assert result.get("error") == "invalid_trace_id", f"{trace_id!r} -> {result}"


def test_trace_id_whitelist_rejects_path_characters():
    """白名单层单独生效：路径分隔符与盘符即使能落在 traces 目录内也必须拒绝。"""
    from react_agent.apps.docs_troubleshoot.trace_backend import _safe_trace_id

    for bad in ("a/b", "a\\b", "C:", "../x", "a..b/../c", "-leading", ".hidden"):
        assert _safe_trace_id(bad) is None, bad


def test_trace_id_cannot_escape_fixture_directory():
    """在 traces 目录外放诱饵，确认读不到内容（包含校验层）。"""
    from react_agent.apps.docs_troubleshoot import trace_backend

    decoy = Path(trace_backend._TRACES).parent / "_regression_decoy.json"
    decoy.write_text(json.dumps({"secret": "TOP_SECRET_REGRESSION"}), encoding="utf-8")
    try:
        result = trace_backend.fetch_trace_bundle("../_regression_decoy")
        dumped = json.dumps(result)
        assert "TOP_SECRET_REGRESSION" not in dumped
        assert result["ok"] is False
    finally:
        decoy.unlink(missing_ok=True)


def test_trace_id_containment_check_blocks_dot_segments(monkeypatch):
    """即使白名单被放松，解析后的目录包含校验仍必须拦截穿越。"""
    from react_agent.apps.docs_troubleshoot import trace_backend

    monkeypatch.setattr(trace_backend, "_TRACE_ID_RE", __import__("re").compile(r"^.{0,256}$"))
    assert trace_backend._safe_trace_id("../secret") is None
    assert trace_backend._safe_trace_id("a/../../secret") is None
    # 正常 id 在放松的白名单下仍可用
    assert trace_backend._safe_trace_id("valid_id") == "valid_id"


def test_valid_trace_id_still_resolves():
    from react_agent.apps.docs_troubleshoot.trace_backend import _safe_trace_id

    assert _safe_trace_id("trace_abc-123.4") == "trace_abc-123.4"


# ── 9. git origin 校验 ──


MALICIOUS_ORIGINS = [
    "https://github.com@127.0.0.1:8765/x.git",
    "https://github.com@attacker.tld/x.git",
    "https://github.com.attacker.tld/x.git",
    "ssh://git@github.com.attacker.tld/x.git",
    "git://evil.tld/x.git",
    "http://github.com/x.git",
    "file:///etc/passwd",
    "ext::sh -c whoami",
    "",
]


@pytest.mark.parametrize("origin", MALICIOUS_ORIGINS)
def test_non_github_origin_rejected(origin):
    from react_agent.apps.github_delivery import _require_github_origin

    with pytest.raises(ValueError):
        _require_github_origin(origin)


@pytest.mark.parametrize(
    "origin",
    [
        "https://github.com/owner/repo.git",
        "https://www.github.com/owner/repo.git",
        "git@github.com:owner/repo.git",
        "ssh://git@github.com/owner/repo.git",
    ],
)
def test_legit_github_origin_accepted(origin):
    from react_agent.apps.github_delivery import _require_github_origin

    assert _require_github_origin(origin) in {"github.com", "www.github.com"}


# ── 10. 脱敏 ──


def test_redact_arguments_masks_sensitive_keys():
    from react_agent.safety.redaction import redact_arguments

    out = redact_arguments(
        json.dumps({"api_key": "sk-abcdefghijklmnop1234", "query": "hello"})
    )
    assert "sk-abcdefghijklmnop1234" not in out
    assert "hello" in out
    assert "<redacted>" in out


def test_redact_arguments_preserves_structure():
    from react_agent.safety.redaction import redact_arguments

    out = json.loads(redact_arguments('{"a": {"b": [{"token": "x"}]}, "keep": "v"}'))
    assert out["keep"] == "v"
    assert out["a"]["b"][0]["token"] == "<redacted>"


@pytest.mark.parametrize(
    "text",
    [
        "sk-abcdefghijklmnop1234",
        "ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789",
        "AKIAIOSFODNN7EXAMPLE",
        "Bearer abcdefghijklmnopqrstuvwxyz",
    ],
)
def test_redact_text_masks_value_patterns(text):
    from react_agent.safety.redaction import redact_text

    out = redact_text(f"leaked {text} here")
    assert text not in out


def test_redact_text_masks_url_credentials_keeps_user():
    from react_agent.safety.redaction import redact_text

    out = redact_text("proxy http://bob:pw123456@proxy:8080")
    assert "pw123456" not in out
    assert "bob" in out


def test_redact_text_leaves_plain_text_untouched():
    from react_agent.safety.redaction import redact_text

    text = "no secrets in this line"
    assert redact_text(text) == text


def test_recorder_persists_redacted_arguments():
    from react_agent.harness.recorder import Trajectory

    traj = Trajectory("probe query", model="probe")
    traj.start_step(1)
    traj.add_tool_call(
        1,
        "fetch_page",
        json.dumps({"url": "https://x", "api_key": "sk-secretsecret12345"}),
        "Authorization: Bearer abcdefghijklmnopqrstuvwxyz",
    )
    blob = json.dumps(traj.steps, ensure_ascii=False)
    assert "sk-secretsecret12345" not in blob
    assert "abcdefghijklmnopqrstuvwxyz" not in blob


def test_recorder_redacts_final_answer():
    from react_agent.harness.recorder import Trajectory

    traj = Trajectory("q")
    traj.set_final_answer("token is sk-abcdefghijklmnop1234")
    assert "sk-abcdefghijklmnop1234" not in traj.final_answer


# ── 11. app 工具路径也过权限闸门 ──


def test_execute_registered_tool_enforces_permission_gate(monkeypatch):
    """非 required 模式下副作用 CONFIRM 工具也必须过闸门。"""
    monkeypatch.setenv("REACT_AGENT_APPROVAL_MODE", "auto_allow")
    monkeypatch.setenv("REACT_AGENT_STRICT_CONFIRM", "1")
    import react_agent.harness.tool_boundary as boundary
    from react_agent.harness.sandbox import Sandbox

    quiet = Sandbox(strategy="off", backend="process", prewarm=False)
    monkeypatch.setattr(boundary, "SANDBOX", quiet)

    calls: list = []

    def _fake(**kwargs):
        calls.append(kwargs)
        return "executed"

    with pytest.raises(PermissionError):
        boundary.execute_registered_tool(
            "clear_trajectories", {}, {"clear_trajectories": _fake}
        )
    assert calls == []


def test_execute_registered_tool_allows_confirm_read(monkeypatch):
    """CONFIRM_READ 在 STRICT 下仍可执行。"""
    monkeypatch.setenv("REACT_AGENT_APPROVAL_MODE", "auto_allow")
    monkeypatch.setenv("REACT_AGENT_STRICT_CONFIRM", "1")
    import react_agent.harness.tool_boundary as boundary
    from react_agent.harness.sandbox import Sandbox

    quiet = Sandbox(strategy="off", backend="process", prewarm=False)
    monkeypatch.setattr(boundary, "SANDBOX", quiet)

    result = boundary.execute_registered_tool(
        "probe_service_health",
        {"url": "x"},
        {"probe_service_health": lambda **_: "ok"},
    )
    assert result == "ok"


def test_execute_registered_tool_allows_safe_tool(monkeypatch):
    import react_agent.harness.tool_boundary as boundary
    from react_agent.harness.sandbox import Sandbox

    monkeypatch.setattr(
        boundary, "SANDBOX", Sandbox(strategy="off", backend="process", prewarm=False)
    )
    result = boundary.execute_registered_tool(
        "calculator", {"expression": "1+1"}, {"calculator": lambda **k: "2"}
    )
    assert result == "2"
