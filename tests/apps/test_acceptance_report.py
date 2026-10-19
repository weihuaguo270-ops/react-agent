from tests._load_eval_script import load_eval_script
from react_agent.harness.contracts import validate_trajectory


module = load_eval_script("build_acceptance_report")


def test_acceptance_inventory_is_shared_evidence_but_not_execution():
    report = module.build_acceptance_report()
    assert report["size"] == 5
    assert report["fixture_manifest"]["data_sha256"]
    assert report["batch_id"]
    assert len(report["evaluation_episodes"]) == report["size"]
    assert all(episode["fixture_manifest"] == report["fixture_manifest"] for episode in report["evaluation_episodes"])
    assert all(episode["batch_id"] == report["batch_id"] for episode in report["evaluation_episodes"])
    assert all(validate_trajectory(episode["trajectory"]) == [] for episode in report["evaluation_episodes"])
    assert all(episode["score"]["status"] == "not_run" for episode in report["evaluation_episodes"])
    assert all(episode["score"]["passed"] is None for episode in report["evaluation_episodes"])
