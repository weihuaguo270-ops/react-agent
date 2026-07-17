"""Tests for frozen public Agent benchmark subset (GSM8K×10 + HotpotQA×10)."""
from __future__ import annotations

import json
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(ROOT, "src"))

from react_agent.eval.public_benchmark import (
    extract_gsm8k_number,
    load_public_benchmark,
    match_gold,
    run_public_benchmark,
)


def test_subset_has_ten_each():
    bundle = load_public_benchmark()
    cases = bundle["cases"]
    assert len(cases) == 20
    gsm = [c for c in cases if c["benchmark"] == "gsm8k"]
    hp = [c for c in cases if c["benchmark"] == "hotpotqa"]
    assert len(gsm) == 10
    assert len(hp) == 10
    for c in cases:
        assert c.get("question")
        assert c.get("gold_answer")
        assert c.get("id")


def test_gsm8k_number_extraction():
    assert extract_gsm8k_number("#### 18") == "18"
    assert extract_gsm8k_number("FINAL ANSWER: 72") == "72"
    assert extract_gsm8k_number("steps...\nanswer is 3.\nFINAL ANSWER: 3") == "3"


def test_match_gold_gsm8k_and_hotpot():
    ok, _ = match_gold("FINAL ANSWER: 18", "18", "gsm8k")
    assert ok
    ok, _ = match_gold("wrong 19", "18", "gsm8k")
    assert not ok
    ok, _ = match_gold("The series is Animorphs.", "Animorphs", "hotpotqa")
    assert ok
    ok, _ = match_gold("something else", "Animorphs", "hotpotqa")
    assert not ok


def test_offline_suite_all_pass():
    report = run_public_benchmark(modes=["offline"])
    assert report["summary"]["total"] == 20
    assert report["summary"]["passed"] == 20
    assert report["summary"]["pass_rate"] == 100.0
    assert report["by_benchmark"]["gsm8k"]["total"] == 10
    assert report["by_benchmark"]["hotpotqa"]["total"] == 10


def test_offline_agent_mock_runner():
    bundle = load_public_benchmark()
    gold_by_id = {c["id"]: c["gold_answer"] for c in bundle["cases"]}

    def mock_runner(question, timeout=90, max_steps=None):
        # recover id via gold embedded in offline-style — use question tail match
        for c in bundle["cases"]:
            if c["question"] in question:
                gold = gold_by_id[c["id"]]
                stdout = f"FINAL ANSWER: {gold}"
                traj = {
                    "session_id": "mock",
                    "query": question,
                    "steps": [{"step": 1, "thought": "t"}],
                    "final_answer": str(gold),
                }
                return stdout, traj, 0, 0.1
        return "FINAL ANSWER: ???", {"final_answer": "???"}, 0, 0.1

    report = run_public_benchmark(
        modes=["agent"],
        agent_runner=mock_runner,
        limit=4,
    )
    assert report["summary"]["total"] == 4
    assert report["summary"]["passed"] == 4
