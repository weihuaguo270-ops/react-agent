"""应用作用域隔离 与 自探进程内化 的回归测试。

对应两项优化：

1. app 工具不再污染全局注册表——``docs_troubleshoot`` 的工具对 Core/其它应用
   不可见、不可调用（此前 ``enable_app_tools()`` 会永久并入全局表）。
2. 健康自探不再走 TCP 回环——目标指向本服务自身时改为进程内取值，避免与
   探针鉴权 / Host 校验策略耦合；外部地址仍受 SSRF 守卫约束。
"""
from __future__ import annotations

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

DOCS_TOOLS = (
    "search_docs",
    "lookup_api",
    "verify_citations",
    "probe_service_health",
    "read_config_snapshot",
    "fetch_trace",
)


# ── 1. 应用作用域隔离 ──


@pytest.fixture(autouse=True)
def _reset_app_scope():
    from react_agent.tools import set_request_app

    set_request_app("")
    yield
    set_request_app("")


def test_core_scope_excludes_docs_tools():
    from react_agent.tools import get_registry, get_tool_definitions, set_request_app

    set_request_app("")
    registry = get_registry()
    names = {d["function"]["name"] for d in get_tool_definitions()}
    for tool in DOCS_TOOLS:
        assert tool not in registry, f"Core 作用域不应含 {tool}"
        assert tool not in names, f"Core 作用域的 tool_defs 不应含 {tool}"


def test_docs_scope_includes_docs_tools():
    from react_agent.tools import get_registry, get_tool_definitions, set_request_app

    set_request_app("docs_troubleshoot")
    registry = get_registry()
    names = {d["function"]["name"] for d in get_tool_definitions()}
    assert "search_docs" in registry
    assert "search_docs" in names


def test_scope_switch_is_isolated_between_calls():
    """同一进程内切换作用域互不影响。"""
    from react_agent.tools import get_registry, set_request_app

    set_request_app("docs_troubleshoot")
    assert "search_docs" in get_registry()
    set_request_app("")
    assert "search_docs" not in get_registry()
    set_request_app("expense")
    assert "search_docs" not in get_registry()


def test_global_registry_stays_clean():
    """关键回归：请求作用域不应把 app 工具写进全局注册表。"""
    from react_agent.tools import (
        TOOL_DEFINITIONS,
        TOOL_REGISTRY,
        get_registry,
        get_tool_definitions,
        set_request_app,
    )

    before_reg = set(TOOL_REGISTRY)
    before_defs = {d["function"]["name"] for d in TOOL_DEFINITIONS}
    set_request_app("docs_troubleshoot")
    get_registry()
    get_tool_definitions()
    assert set(TOOL_REGISTRY) == before_reg, "全局注册表被请求路径污染"
    after_defs = {d["function"]["name"] for d in TOOL_DEFINITIONS}
    assert after_defs == before_defs, "全局 TOOL_DEFINITIONS 被请求路径污染"


def test_isolation_survives_legacy_global_pollution(monkeypatch):
    """遗留调用方（如某些测试/eval）会调 enable_app_tools() 永久并入全局表；
    即使发生这种情况，Core 视图也必须保持隔离。"""
    from react_agent.tools import (
        TOOL_REGISTRY,
        get_registry,
        get_tool_definitions,
        set_request_app,
    )

    monkeypatch.setenv("REACT_AGENT_APP", "docs_troubleshoot")
    from react_agent.tools import enable_app_tools

    enable_app_tools()  # 故意污染全局表
    assert "search_docs" in TOOL_REGISTRY, "前置条件：全局表已被污染"

    set_request_app("")
    assert "search_docs" not in get_registry(), "Core 视图仍应从全局污染中隔离"
    assert "search_docs" not in {
        d["function"]["name"] for d in get_tool_definitions()
    }


def test_core_scope_cannot_dispatch_docs_tool(monkeypatch):
    """Core 作用域下模型即使点名 docs 工具也应被拒绝。"""
    from react_agent import react_loop as rl
    from react_agent.tools import set_request_app

    set_request_app("")
    called: list[str] = []

    def _boom(**kwargs):  # pragma: no cover - 不应被调用
        called.append("search_docs")
        return "should-not-run"

    import react_agent.apps.docs_troubleshoot.tools as docs_tools

    monkeypatch.setattr(docs_tools, "search_docs", _boom, raising=False)
    result = rl._execute_tool_call_raw(
        {"function": {"name": "search_docs", "arguments": json.dumps({"query": "x"})}}
    )
    assert not called, "Core 作用域不应能调用 docs 工具"
    assert "未知工具" in json.loads(result)["error"]


def test_docs_scope_can_dispatch_docs_tool():
    """docs 作用域下同名工具可正常派发（证明隔离不是一刀切禁用）。"""
    from react_agent.tools import set_request_app

    set_request_app("docs_troubleshoot")
    from react_agent.harness.tool_boundary import execute_registered_tool
    from react_agent.tools import get_registry

    out = execute_registered_tool("search_docs", {"query": "鉴权 401"}, get_registry())
    assert isinstance(out, (str, dict))


def test_answer_offline_sets_app_scope():
    """docs 请求路径应设置作用域，而不是改全局环境变量。"""
    from react_agent.tools import active_tools_app

    from react_agent.apps.docs_troubleshoot.offline_answer import answer_offline

    env_before = os.environ.get("REACT_AGENT_APP")
    answer_offline("缺少 Authorization 返回什么？")
    assert active_tools_app() == "docs_troubleshoot"
    # 不应再把 REACT_AGENT_APP 当作请求副作用写入进程环境
    assert os.environ.get("REACT_AGENT_APP") == env_before


# ── 2. 自探进程内化 ──


@pytest.mark.parametrize(
    ("url", "kind"),
    [
        ("http://127.0.0.1:8765/health", "liveness"),
        ("http://localhost:8765/health", "liveness"),
        ("http://127.0.0.1:8765/v1/health", "liveness"),
        ("http://127.0.0.1:8765/ready", "readiness"),
        ("http://127.0.0.1:8765/v1/ready", "readiness"),
    ],
)
def test_self_health_target_recognized(url, kind):
    from react_agent.apps.docs_troubleshoot.evidence import _self_health_target

    assert _self_health_target(url) == kind


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1:9999/health",     # 端口不是本服务
        "http://169.254.169.254/health",    # 非回环
        "http://127.0.0.1:8765/v1/info",    # 非健康端点
        "ftp://127.0.0.1:8765/health",      # 非 http(s)
    ],
)
def test_non_self_targets_not_treated_as_self_probe(url):
    from react_agent.apps.docs_troubleshoot.evidence import _self_health_target

    assert _self_health_target(url) is None


def test_default_probe_is_in_process():
    """无参探活默认指向自身 → 必须走进程内，不产生回环 HTTP。"""
    from react_agent.apps.docs_troubleshoot.evidence import probe_service_health

    result = probe_service_health()
    assert result["ok"] is True
    assert result.get("in_process") is True
    assert result.get("probe_kind") == "liveness"
    assert result["status_code"] == 200
    payload = json.loads(result["body_preview"])
    assert payload["status"] == "ok"


def test_ready_probe_is_in_process_readiness():
    from react_agent.apps.docs_troubleshoot.evidence import probe_service_health

    result = probe_service_health("http://127.0.0.1:8765/ready")
    assert result.get("in_process") is True
    assert result.get("probe_kind") == "readiness"
    assert result["status_code"] in (200, 503)


def test_external_target_still_uses_http_and_ssrf_guard():
    """外部/内网目标仍受 SSRF 守卫约束（不能因自探优化而放宽）。"""
    from react_agent.apps.docs_troubleshoot.evidence import probe_service_health

    result = probe_service_health("http://169.254.169.254/latest/meta-data/")
    assert result["ok"] is False
    assert "blocked" in result["error"]
    assert result.get("in_process") is None


def test_self_probe_does_not_depend_on_http_layer(monkeypatch):
    """自探不依赖 urlopen：把它换成会报错的实现，自探仍应成功。"""
    import urllib.request

    from react_agent.apps.docs_troubleshoot import evidence

    def _explode(*args, **kwargs):  # pragma: no cover
        raise AssertionError("自探不应该发起 HTTP 请求")

    monkeypatch.setattr(urllib.request, "urlopen", _explode)
    result = evidence.probe_service_health()
    assert result["ok"] is True
    assert result.get("in_process") is True
