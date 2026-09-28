"""同级仓库源码根解析（CI 装到 /tmp，本地是 ../trace-debugger）。"""
from __future__ import annotations

import importlib.util
from pathlib import Path

from react_agent.eval import sibling_paths
from react_agent.eval.sibling_paths import (
    installed_source_root,
    source_root,
    trace_debugger_source_root,
)


class _Spec:
    def __init__(self, origin: str | None) -> None:
        self.origin = origin


def test_env_override_wins(tmp_path, monkeypatch):
    root = tmp_path / "td"
    (root / "examples").mkdir(parents=True)
    monkeypatch.setenv("REACT_AGENT_TDEBUG_ROOT", str(root))
    assert trace_debugger_source_root() == root.resolve()


def test_override_without_marker_is_ignored(tmp_path, monkeypatch):
    """覆盖路径必须像源码 checkout（含 examples/），否则继续找下一个候选。"""
    empty = tmp_path / "not-a-checkout"
    empty.mkdir()
    monkeypatch.setenv("REACT_AGENT_TDEBUG_ROOT", str(empty))
    monkeypatch.setattr(sibling_paths, "REPO_ROOT", tmp_path / "repo")
    monkeypatch.setattr(sibling_paths, "installed_source_root", lambda _module: None)
    assert trace_debugger_source_root() is None


def test_sibling_directory_is_used_when_no_install(tmp_path, monkeypatch):
    repo = tmp_path / "react-agent"
    sibling = tmp_path / "trace-debugger"
    (sibling / "examples").mkdir(parents=True)
    monkeypatch.delenv("REACT_AGENT_TDEBUG_ROOT", raising=False)
    monkeypatch.setattr(sibling_paths, "REPO_ROOT", repo)
    monkeypatch.setattr(sibling_paths, "installed_source_root", lambda _module: None)
    assert trace_debugger_source_root() == sibling.resolve()


def test_repo_local_directory_is_used_before_parent(tmp_path, monkeypatch):
    repo = tmp_path / "react-agent"
    (repo / "trace-debugger" / "examples").mkdir(parents=True)
    monkeypatch.delenv("REACT_AGENT_TDEBUG_ROOT", raising=False)
    monkeypatch.setattr(sibling_paths, "REPO_ROOT", repo)
    monkeypatch.setattr(sibling_paths, "installed_source_root", lambda _module: None)
    assert trace_debugger_source_root() == (repo / "trace-debugger").resolve()


def test_installed_source_root_accepts_editable_layout(tmp_path, monkeypatch):
    source = tmp_path / "trace-debugger"
    package = source / "trace_debugger"
    package.mkdir(parents=True)
    init = package / "__init__.py"
    init.write_text("", encoding="utf-8")
    monkeypatch.setattr(importlib.util, "find_spec", lambda _name: _Spec(str(init)))
    assert installed_source_root("trace_debugger") == source


def test_editable_install_with_examples_is_the_source_root(tmp_path, monkeypatch):
    """CI: pip install -e /tmp/trace-debugger → 可导入包旁边就有 examples/。"""
    source = tmp_path / "trace-debugger"
    package = source / "trace_debugger"
    package.mkdir(parents=True)
    init = package / "__init__.py"
    init.write_text("", encoding="utf-8")
    (source / "examples").mkdir()
    monkeypatch.delenv("REACT_AGENT_TDEBUG_ROOT", raising=False)
    monkeypatch.setattr(importlib.util, "find_spec", lambda _name: _Spec(str(init)))
    monkeypatch.setattr(sibling_paths, "REPO_ROOT", tmp_path / "react-agent")
    assert trace_debugger_source_root() == source.resolve()


def test_site_packages_install_is_not_a_source_root(tmp_path, monkeypatch):
    """普通安装（site-packages）没有 examples/，不能当成源码 checkout。"""
    site_packages = tmp_path / "site-packages"
    package = site_packages / "trace_debugger"
    package.mkdir(parents=True)
    init = package / "__init__.py"
    init.write_text("", encoding="utf-8")
    monkeypatch.delenv("REACT_AGENT_TDEBUG_ROOT", raising=False)
    monkeypatch.setattr(importlib.util, "find_spec", lambda _name: _Spec(str(init)))
    monkeypatch.setattr(sibling_paths, "REPO_ROOT", tmp_path / "react-agent")
    assert trace_debugger_source_root() is None


def test_installed_source_root_handles_unknown_module(monkeypatch):
    monkeypatch.setattr(importlib.util, "find_spec", lambda _name: None)
    assert installed_source_root("trace_debugger") is None


def test_source_root_ignores_empty_candidate(tmp_path, monkeypatch):
    monkeypatch.delenv("REACT_AGENT_TDEBUG_ROOT", raising=False)
    monkeypatch.setattr(sibling_paths, "REPO_ROOT", Path(tmp_path))
    monkeypatch.setattr(sibling_paths, "installed_source_root", lambda _module: None)
    assert source_root(
        "trace_debugger", env_var="REACT_AGENT_TDEBUG_ROOT", dir_names=("trace-debugger",)
    ) is None
