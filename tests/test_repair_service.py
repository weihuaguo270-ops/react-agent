from react_agent.apps.patch_planner import Replacement
from react_agent.eval.repair_service import build_repair_loop


def test_service_runs_public_then_hidden():
    seen = []
    def planner(ctx):
        assert "hidden" not in str(ctx)
        return {"replacements": [{"path": "src/x.py", "old": "a", "new": "b"}]}
    def apply_patch(repls):
        seen.append("patch")
        return {"applied": True}
    def run_tests(hidden):
        seen.append("hidden" if hidden else "public")
        return {"passed": True}
    result = build_repair_loop(planner=planner, apply_patch=apply_patch,
                               run_tests=run_tests, allowed_paths=("src/",)).run({"task": "x"})
    assert result["status"] == "succeeded"
    assert seen == ["patch", "public", "patch", "hidden"]
