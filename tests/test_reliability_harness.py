"""Reliability harness smoke test"""
import os

os.environ["REACT_AGENT_SKIP_RAG"] = "1"

from tests._load_eval_script import load_eval_script  # noqa: E402


def test_reliability_harness_all_pass():
    run_harness = load_eval_script("run_reliability_harness").run_harness
    report = run_harness()
    assert report["summary"]["total"] == 4
    assert report["summary"]["passed"] == 4, report
