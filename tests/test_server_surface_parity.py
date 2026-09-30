"""两个 HTTP 服务面的共享契约对等测试。

stdlib 面（``server/app.py`` 的 ``AgentHandler``）与 FastAPI 面
（``server/fastapi_app.py`` 的 ``create_app``）对外是「两个入口点」，但鉴权、
Host 校验与探针公开性必须是同一套语义：容器默认走 ``react-agent-api``
（FastAPI），一旦它少一道防线，文档承诺的 ``REACT_AGENT_AUTH_TOKEN`` 与 Host
校验就会在默认入口上静默失效。

这里的每个用例都会在两个面上各跑一遍（``surface`` fixture 参数化），断言的是
**共享契约**，不是各自实现细节。
"""
from __future__ import annotations

import asyncio
import json
import socket
import threading

import pytest

httpx = pytest.importorskip("httpx")
pytest.importorskip("fastapi")

TOKEN = "parity-secret"
LEGACY_TOKEN = "parity-legacy-secret"

ISOLATED_ENV = (
    "REACT_AGENT_AUTH_TOKEN",
    "REACT_AGENT_API_KEY",
    "REACT_AGENT_ALLOWED_HOSTS",
    "REACT_AGENT_HOST_VALIDATION",
    "REACT_AGENT_REQUIRE_HOST_ALLOWLIST",
)


class _Response:
    def __init__(self, status: int, headers: dict, body: bytes):
        self.status = status
        self.headers = {str(k).lower(): v for k, v in (headers or {}).items()}
        self.body = body

    def json(self) -> dict:
        return json.loads(self.body.decode("utf-8") or "{}")

    def error_code(self) -> str:
        try:
            return str(self.json().get("error", {}).get("code") or "")
        except (ValueError, AttributeError):
            return ""


def _read_response(sock: socket.socket) -> _Response:
    """按 Content-Length 读完整个响应（不能只依赖 EOF，见 _StdlibSurface 说明）。"""
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
        length = 0
        for line in joined[:header_end].decode("iso-8859-1").split("\r\n")[1:]:
            if line.lower().startswith("content-length:"):
                length = int(line.split(":", 1)[1].strip())
                break
        if len(joined) - (header_end + 4) >= length:
            break

    raw = b"".join(chunks)
    header_end = raw.find(b"\r\n\r\n")
    head = raw[:header_end].decode("iso-8859-1") if header_end != -1 else ""
    body = raw[header_end + 4:] if header_end != -1 else b""
    lines = head.split("\r\n")
    status = int(lines[0].split()[1]) if lines and len(lines[0].split()) > 1 else 0
    parsed: dict[str, str] = {}
    for line in lines[1:]:
        if ":" in line:
            name, value = line.split(":", 1)
            parsed[name.strip().lower()] = value.strip()
    return _Response(status, parsed, body)


class _StdlibSurface:
    """真实 socket 上的 stdlib 服务面。

    用裸 socket 而不是 urllib：stdlib 面按 HTTP/1.0 应答后立刻关闭连接，而
    ``_reject_unauthenticated`` 在鉴权失败时**不读请求体**——POST 若用 urllib，
    未读的请求体会让 Windows 回 RST，客户端在 ``getresponse()`` 里拿到
    ``ConnectionAbortedError``（WinError 10053）而不是 401。这个 flake 取决于
    执行顺序（单跑本文件不复现、跑全量才偶发），所以这里照
    ``test_security_hardening.py`` 的做法：每次新建连接 + 显式
    ``Connection: close`` + 按 ``Content-Length`` 读完。
    """

    name = "stdlib"

    def __init__(self, bind: str = "127.0.0.1"):
        from http.server import ThreadingHTTPServer

        from react_agent.server.app import AgentHandler

        self.httpd = ThreadingHTTPServer((bind, 0), AgentHandler)
        self.port = self.httpd.server_address[1]
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    def close(self) -> None:
        self.httpd.shutdown()
        self.thread.join(timeout=5)

    def request(self, method, path, *, host=None, headers=None, json_body=None) -> _Response:
        payload = b"" if json_body is None else json.dumps(json_body).encode("utf-8")
        sent = {str(k).lower(): v for k, v in (headers or {}).items()}
        sent.setdefault("host", host or f"127.0.0.1:{self.port}")
        lines = [f"{method} {path} HTTP/1.1"]
        for name, value in sent.items():
            lines.append(f"{name}: {value}")
        if json_body is not None:
            lines.append("Content-Type: application/json")
            lines.append(f"Content-Length: {len(payload)}")
        lines.append("Connection: close")
        raw = ("\r\n".join(lines) + "\r\n\r\n").encode() + payload
        with socket.create_connection(("127.0.0.1", self.port), timeout=10) as sock:
            sock.sendall(raw)
            return _read_response(sock)


class _FastapiSurface:
    """ASGI 直连的 FastAPI 服务面（CI 的 ``[test]`` extra 不含 uvicorn）。"""

    name = "fastapi"

    def __init__(self):
        from react_agent.server.fastapi_app import create_app

        self.api = create_app(initialize_runtime=False)

    def close(self) -> None:
        return None

    def request(self, method, path, *, host=None, headers=None, json_body=None) -> _Response:
        sent = dict(headers or {})
        if host is not None:
            sent["Host"] = host

        async def go():
            transport = httpx.ASGITransport(app=self.api)
            async with httpx.AsyncClient(
                transport=transport, base_url="http://127.0.0.1"
            ) as client:
                return await client.request(method, path, headers=sent, json=json_body)

        resp = asyncio.run(go())
        return _Response(resp.status_code, dict(resp.headers), resp.content)


@pytest.fixture(params=[_StdlibSurface, _FastapiSurface], ids=["stdlib", "fastapi"])
def surface(request):
    """参数化到两个服务面；两边跑同一批断言。"""
    created = request.param()
    try:
        yield created
    finally:
        created.close()


@pytest.fixture(autouse=True)
def clean_security_env(monkeypatch):
    """本机 shell 里可能已设这些变量，测试间必须互不污染。"""
    for key in ISOLATED_ENV:
        monkeypatch.delenv(key, raising=False)
    # 两边都按这个绑定地址做 Host 校验，保证断言可预期
    monkeypatch.setenv("REACT_AGENT_HOST", "127.0.0.1")


def _bearer(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# ── 1. 未配置 token：本地开发默认开放 ──


def test_shared_core_endpoints_open_without_token(surface):
    assert surface.request("GET", "/health").status == 200
    # readiness 依赖文档索引状态，非就绪时是 503——这里只要求「探针本身是公开的」
    assert surface.request("GET", "/ready").status in (200, 503)
    assert surface.request("GET", "/v1/info").status == 200
    assert surface.request("GET", "/v1/workflows").status == 200


# ── 2. 配置 token：除探针外全接口要求凭据 ──


def test_probes_stay_public_when_token_configured(surface, monkeypatch):
    monkeypatch.setenv("REACT_AGENT_AUTH_TOKEN", TOKEN)
    assert surface.request("GET", "/health").status == 200
    assert surface.request("GET", "/ready").status in (200, 503)


def test_non_probe_endpoints_require_token(surface, monkeypatch):
    monkeypatch.setenv("REACT_AGENT_AUTH_TOKEN", TOKEN)
    for method, path in (
        ("GET", "/v1/info"),
        ("GET", "/v1/workflows"),
        ("POST", "/v1/chat"),
    ):
        body = {} if method == "POST" else None
        resp = surface.request(method, path, json_body=body)
        assert resp.status == 401, f"{method} {path}"
        assert resp.error_code() == "unauthorized", f"{method} {path}"
        assert resp.headers.get("www-authenticate") == "Bearer", f"{method} {path}"


def test_valid_token_is_accepted(surface, monkeypatch):
    monkeypatch.setenv("REACT_AGENT_AUTH_TOKEN", TOKEN)
    assert surface.request("GET", "/v1/info", headers=_bearer(TOKEN)).status == 200
    assert surface.request("GET", "/v1/info", headers={"X-Api-Key": TOKEN}).status == 200
    assert surface.request("GET", "/v1/info", headers=_bearer("wrong")).status == 401


def test_legacy_api_key_env_is_still_honoured(surface, monkeypatch):
    """历史名 ``REACT_AGENT_API_KEY`` 保留可用，但 AUTH_TOKEN 优先。"""
    monkeypatch.setenv("REACT_AGENT_API_KEY", LEGACY_TOKEN)
    assert surface.request("GET", "/v1/info").status == 401
    assert surface.request("GET", "/v1/info", headers=_bearer(LEGACY_TOKEN)).status == 200

    monkeypatch.setenv("REACT_AGENT_AUTH_TOKEN", TOKEN)
    assert surface.request("GET", "/v1/info", headers=_bearer(TOKEN)).status == 200
    assert surface.request("GET", "/v1/info", headers=_bearer(LEGACY_TOKEN)).status == 401


# ── 3. Host 校验（DNS rebinding） ──


def test_host_validation_applies_to_both_surfaces(surface):
    allowed = surface.request("GET", "/v1/info", host="127.0.0.1")
    assert allowed.status == 200

    for bad_host in ("attacker.example.com", "evil.tld:8765", "127.0.0.1.nip.io"):
        resp = surface.request("GET", "/v1/info", host=bad_host)
        assert resp.status == 421, bad_host
        assert resp.error_code() == "invalid_host", bad_host


def test_host_check_runs_before_auth(surface, monkeypatch):
    """伪造 Host 且无凭据：必须 421（Host 问题），不能 401 暴露接口存在。"""
    monkeypatch.setenv("REACT_AGENT_AUTH_TOKEN", TOKEN)
    resp = surface.request("GET", "/v1/info", host="evil.tld")
    assert resp.status == 421
    assert resp.error_code() == "invalid_host"
