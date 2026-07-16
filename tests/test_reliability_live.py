"""Flaky inject + live reliability mock 测试"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

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
    from examples.run_reliability_live import SCENARIOS, run_pair, aggregate

    pairs = [run_pair(s, live=False) for s in SCENARIOS]
    agg = aggregate(pairs)
    assert agg["flaky_n"] == 20
    assert agg["flaky_on"]["pass_rate"] == 100.0
    assert agg["flaky_off"]["pass_rate"] == 0.0
    assert agg["on_better_count"] == 20
    assert agg["baseline_on"]["pass_rate"] == 100.0
    assert len(SCENARIOS) == 24
