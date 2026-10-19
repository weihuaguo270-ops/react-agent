from __future__ import annotations

from react_agent.eval.public_rag_benchmark import run_public_rag_benchmark
from react_agent.harness.contracts import validate_trajectory


def test_public_rag_results_include_shared_episode_evidence():
    report = run_public_rag_benchmark(
        modes=["offline"],
        tiers=["smoke"],
        limit=1,
        include_controls=False,
    )

    assert report["fixture_manifest"]["data_sha256"]
    assert report["batch_id"].startswith("eval-batch-")
    result = report["results"][0]
    assert result["evaluation_episode"]["runner"] == "public-rag:offline"
    assert result["evaluation_episode"]["artifacts"][0]["sha256"]
    assert validate_trajectory(result["trajectory"]) == []
