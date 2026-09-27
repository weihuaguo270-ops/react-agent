import pytest

from react_agent.apps.patch_planner import PatchPlanError, parse_patch_plan


def test_structured_plan_is_converted_to_replacements():
    result = parse_patch_plan(
        {"replacements": [{"path": "src/app.py", "old": "x = 1", "new": "x = 2"}]},
        allowed_paths=["src/"],
    )
    assert result[0].path == "src/app.py"


@pytest.mark.parametrize("payload", [
    {},
    {"replacements": []},
    {"replacements": [{"path": "../secret", "old": "x", "new": "y"}]},
    {"replacements": [{"path": "tests/a.py", "old": "x", "new": "y"}]},
])
def test_invalid_or_unauthorized_plan_is_rejected(payload):
    with pytest.raises(PatchPlanError):
        parse_patch_plan(payload, allowed_paths=["src/"])
