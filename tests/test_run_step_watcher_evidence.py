from __future__ import annotations

from tests._load_eval_script import load_eval_script


runner = load_eval_script("run_step_watcher_evidence")


def test_main_fails_when_cross_repo_golden_suite_fails(monkeypatch, capsys):
    monkeypatch.setattr(
        runner,
        "run_all_scenarios",
        lambda: {
            "n_scenarios": 6,
            "n_passed": 6,
            "pass_rate": 1.0,
            "golden_suite_pass_rate": 0.0,
            "golden_suite_exit_code": 1,
        },
    )
    monkeypatch.setattr("sys.argv", ["run_step_watcher_evidence.py"])

    assert runner.main() == 1
    assert '"golden_suite_exit_code": 1' in capsys.readouterr().out


def test_main_fails_when_cross_repo_golden_suite_is_unavailable(monkeypatch):
    monkeypatch.setattr(
        runner,
        "run_all_scenarios",
        lambda: {
            "n_scenarios": 6,
            "n_passed": 6,
            "pass_rate": 1.0,
            "golden_suite_pass_rate": None,
            "golden_suite_exit_code": None,
        },
    )
    monkeypatch.setattr("sys.argv", ["run_step_watcher_evidence.py"])

    assert runner.main() == 1
