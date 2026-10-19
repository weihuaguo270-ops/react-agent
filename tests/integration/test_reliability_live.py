"""Flaky inject + live reliability mock 测试"""
import os

os.environ["REACT_AGENT_SKIP_RAG"] = "1"


def test_parse_and_install_flaky():
    from react_agent.harness.flaky_inject import parse_flaky_spec, install_flaky_tools
    import react_agent.harness.flaky_inject as fi

    # reset module state for test isolation
    fi._INSTALLED = False
    fi._COUNTERS.clear()

    assert parse_flaky_spec("calculator:2,execute_python:1") == {
        "calculator": 2,
        "execute_python": 1,
    }

    def real_calc(expression: str) -> str:
        if expression == "1+1":
            return "2"
        return "err"

    reg = {"calculator": real_calc}
    plan = install_flaky_tools(reg, "calculator:2")
    assert plan == {"calculator": 2}
    try:
        reg["calculator"](expression="1+1")
        assert False, "should raise"
    except Exception as e:
        assert "injected flaky" in str(e)
    try:
        reg["calculator"](expression="1+1")
        assert False, "should raise"
    except Exception:
        pass
    assert reg["calculator"](expression="1+1") == "2"


def test_reliability_live_mock():
    from tests._load_eval_script import load_eval_script

    mod = load_eval_script("run_reliability_live")
    SCENARIOS, run_pair, aggregate = mod.SCENARIOS, mod.run_pair, mod.aggregate

    pairs = [run_pair(s, live=False) for s in SCENARIOS]
    agg = aggregate(pairs)
    assert agg["flaky_n"] == 20
    assert agg["flaky_on"]["pass_rate"] == 100.0
    assert agg["flaky_off"]["pass_rate"] == 0.0
    assert agg["on_better_count"] == 20
    assert agg["baseline_on"]["pass_rate"] == 100.0
    assert len(SCENARIOS) == 24

    pairs = [run_pair(s, live=False) for s in SCENARIOS[:1]]
    fixture = mod.SCENARIOS[:1]
    from react_agent.harness.evaluation import build_reliability_manifest, reliability_episode

    manifest = build_reliability_manifest(
        fixture,
        fixture_id="test:live-reliability",
        format_name="test-reliability/v1",
    )
    episode = reliability_episode(
        episode_id=f"{pairs[0]['id']}#on",
        query=pairs[0]["question"],
        acceptance=["expected result passes"],
        result=pairs[0]["on"],
        fixture_manifest=manifest,
        batch_id="batch-test",
        runner="reliability:live:on",
    )
    from react_agent.harness.contracts import validate_trajectory

    assert episode["artifacts"][0]["sha256"]
    assert validate_trajectory(episode["trajectory"]) == []

