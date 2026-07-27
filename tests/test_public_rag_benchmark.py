"""Tests for stratified public RAG/Agent benchmark."""
from __future__ import annotations

import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(ROOT, "src"))

os.environ.setdefault("REACT_AGENT_RAG_MODE", "keyword")

from react_agent.eval.public_rag_benchmark import (
    load_public_rag_benchmark,
    run_public_rag_benchmark,
)


def test_bundle_stratified():
    bundle = load_public_rag_benchmark()
    assert bundle.get("version") == "2"
    cases = bundle["cases"]
    tiers = {c.get("tier") for c in cases}
    assert tiers == {"smoke", "hard", "held_out"}
    assert sum(1 for c in cases if c["tier"] == "smoke") == 12
    assert sum(1 for c in cases if c["tier"] == "hard") == 6
    assert sum(1 for c in cases if c["tier"] == "held_out") == 4
    assert bundle.get("honesty", {}).get("reporting_rule")


def test_smoke_must_pass_rag():
    report = run_public_rag_benchmark(
        modes=["offline", "rag"],
        tiers=["smoke"],
        include_controls=False,
    )
    assert report["by_tier"]["smoke"]["passed"] == report["by_tier"]["smoke"]["total"]


def test_hard_not_trivially_perfect_and_controls_drop():
    report = run_public_rag_benchmark(
        modes=["rag"],
        tiers=["hard", "held_out"],
        include_controls=True,
    )
    hard = report["by_tier"].get("hard") or {}
    # Hard should not look like a vanity 100% smoke set
    assert hard.get("total", 0) >= 6
    assert hard.get("pass_rate", 100) < 100.0

    drop = report["dropoff_controls"]
    assert drop["hard_control_no_context"]["pass_rate"] == 0.0
    assert drop["hard_control_distractors_only"]["pass_rate"] == 0.0
    # Main hard rag should beat empty-context control when any pass exists,
    # or both low — either way empty control must not exceed main if main>0
    if drop["hard_rag"]["pass_rate"] > 0:
        assert drop["hard_rag"]["pass_rate"] >= drop["hard_control_no_context"]["pass_rate"]


def test_honesty_fields_present():
    report = run_public_rag_benchmark(modes=["rag"], tiers=["smoke"], include_controls=False)
    assert "by_tier" in report
    assert "live_reading" in (report.get("honesty") or {})
    assert "勿单独" in (report["summary"]["honesty"] or "") or "smoke" in (
        report["summary"]["honesty"] or ""
    )
