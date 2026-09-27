"""git-docs 语料漂移检测的回归测试。

背景：``docs/`` 既是文档也是该评测的 RAG 语料，断言是 ``must_any`` 关键词匹配
「被检索到的文本片段」。因此结构性改写文档会让评测失败——即使语义没变。
本模块把语料状态相对基线的漂移显式报告出来，并指出受影响用例。
"""
from __future__ import annotations

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from react_agent.apps.docs_troubleshoot import eval_git_docs as eg  # noqa: E402


@pytest.fixture(autouse=True)
def _restore_loader():
    real = eg.load_corpus_baseline
    yield
    eg.load_corpus_baseline = real


def test_baseline_exists_and_covers_corpus():
    hashes = eg.current_corpus_hashes()
    baseline = eg.load_corpus_baseline()
    assert hashes, "docs/ 语料不应为空"
    assert baseline, "应存在语料基线（缺失时测试会提示需刷新）"
    assert any("CORE_ARCHITECTURE" in k for k in baseline)


def test_drift_clean_when_matching_baseline():
    drift = eg.corpus_drift()
    assert drift["status"] == "clean", drift
    assert drift["changed_files"] == []


def test_drift_detects_modified_file_and_maps_cases(monkeypatch):
    """改动被断言引用的文件时，应指出受影响用例。"""
    tampered = eg.load_corpus_baseline()
    key = next(k for k in tampered if "CORE_ARCHITECTURE" in k)
    tampered[key] = "0" * 64
    monkeypatch.setattr(eg, "load_corpus_baseline", lambda: tampered)

    drift = eg.corpus_drift()
    assert drift["status"] == "changed"
    assert "CORE_ARCHITECTURE.md" in drift["changed_files"]
    # git03 的 prefer_sources 指向 CORE_ARCHITECTURE.md
    assert "git03" in drift["affected_cases"]
    assert drift["hint"]


def test_drift_detects_added_and_removed_files(monkeypatch):
    removed = eg.load_corpus_baseline()
    key = next(iter(removed))
    removed.pop(key)
    removed["GONE_FILE.md"] = "1" * 64
    monkeypatch.setattr(eg, "load_corpus_baseline", lambda: removed)

    drift = eg.corpus_drift()
    assert drift["status"] == "changed"
    assert "GONE_FILE.md" in drift["changed_files"]
    assert drift["changed_count"] >= 2  # 删除 1 个 + 新增 1 个


def test_missing_baseline_reports_actionable_hint(monkeypatch):
    monkeypatch.setattr(eg, "load_corpus_baseline", lambda: {})
    drift = eg.corpus_drift()
    assert drift["status"] == "no_baseline"
    assert "--refresh-baseline" in drift["hint"]


def test_report_includes_corpus_status():
    report = eg.run_git_docs_eval()
    assert "corpus" in report
    assert report["corpus"]["status"] in {"clean", "changed", "no_baseline"}


def test_strict_mode_fails_on_drift(monkeypatch):
    tampered = eg.load_corpus_baseline()
    key = next(iter(tampered))
    tampered[key] = "0" * 64
    monkeypatch.setattr(eg, "load_corpus_baseline", lambda: tampered)

    with pytest.raises(AssertionError, match="语料相对基线已变化"):
        eg.run_git_docs_eval(strict_corpus=True)


def test_non_strict_mode_reports_drift_without_failing(monkeypatch):
    """默认只提示，不因为文档变更就打断评测。"""
    tampered = eg.load_corpus_baseline()
    key = next(iter(tampered))
    tampered[key] = "0" * 64
    monkeypatch.setattr(eg, "load_corpus_baseline", lambda: tampered)

    report = eg.run_git_docs_eval(strict_corpus=False)
    assert report["corpus"]["status"] == "changed"


def test_refresh_baseline_roundtrip(monkeypatch, tmp_path):
    """刷新后应与当前语料一致（写入临时路径，不动真实基线）。"""
    target = tmp_path / "baseline.json"
    monkeypatch.setattr(eg, "_BASELINE", target)
    payload = eg.refresh_corpus_baseline()
    assert target.is_file()
    assert len(payload["files"]) == len(eg.current_corpus_hashes())
    assert eg.corpus_drift()["status"] == "clean"


def test_baseline_file_is_valid_json():
    text = eg._BASELINE.read_text(encoding="utf-8")
    data = json.loads(text)
    assert "files" in data
    assert all(isinstance(v, str) and len(v) == 64 for v in data["files"].values())
