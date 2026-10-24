from pathlib import Path

from scripts.ci.harness_stage_gate import PHASE_TESTS, missing_phase_tests
from scripts.eval.smoke.build_p2_acceptance_report import EVIDENCE, WORKING_TREE_PATHS


def test_p2_gate_points_to_current_test_paths():
    expected = {
        "tests/harness/test_harness_r2.py",
        "tests/plugins/test_mcp_mock.py",
        "tests/harness/test_deterministic_replay.py",
        "tests/harness/test_runtime_observability.py",
    }
    assert expected.issubset(PHASE_TESTS["P2"])
    assert missing_phase_tests("P2") == []
    assert "tests/plugins/test_mcp_mock.py" in WORKING_TREE_PATHS
    assert "tests/harness/test_runtime_observability.py" in WORKING_TREE_PATHS
    assert "docs/specs/harness/r6-observability.md" in WORKING_TREE_PATHS
    assert EVIDENCE["r5_docker_replay"] == ".evidence_tmp/docker-replay-evidence-r5.json"


def test_missing_phase_tests_are_reported():
    missing_root = Path("nonexistent-p2-test-root")
    assert missing_phase_tests("P2", missing_root) == PHASE_TESTS["P2"]
