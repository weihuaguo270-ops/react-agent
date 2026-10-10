import importlib.util
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "github_delivery_sample",
    Path(__file__).resolve().parent / "github_delivery_sample.py",
)
assert _spec and _spec.loader
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
VALUE = _mod.VALUE


def test_value():
    assert VALUE == 1
