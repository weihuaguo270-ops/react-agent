"""Load scripts/eval/**/*.py by module filename without putting that tree on sys.path."""
from __future__ import annotations

import importlib.util
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
_EVAL_ROOT = _REPO / "scripts" / "eval"


def load_eval_script(module_name: str):
    matches = sorted(_EVAL_ROOT.rglob(f"{module_name}.py"))
    if not matches:
        raise FileNotFoundError(f"{module_name}.py under {_EVAL_ROOT}")
    if len(matches) > 1:
        raise RuntimeError(f"ambiguous eval script {module_name}: {matches}")
    path = matches[0]
    spec = importlib.util.spec_from_file_location(f"_eval_{module_name}", path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod
