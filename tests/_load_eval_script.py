"""Load examples/eval/*.py scripts without adding examples/eval to sys.path."""
from __future__ import annotations

import importlib.util
from pathlib import Path

_EVAL_DIR = Path(__file__).resolve().parents[1] / "examples" / "eval"


def load_eval_script(module_name: str):
    path = _EVAL_DIR / f"{module_name}.py"
    if not path.is_file():
        raise FileNotFoundError(path)
    spec = importlib.util.spec_from_file_location(f"_eval_{module_name}", path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod
