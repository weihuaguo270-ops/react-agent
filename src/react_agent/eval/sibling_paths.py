"""定位同级仓库的**源码**目录（含 ``examples/``、``fixtures/`` 的那份 checkout）。

CI 用 ``pip install -e /tmp/trace-debugger`` 安装同级仓库，所以可导入包的位置就是源码根；
本地开发常见的是与本仓并列的 ``../trace-debugger``。两种都支持，并可用环境变量覆盖。

只在目标目录确实含有 marker 子目录时才返回，避免把 site-packages 或空目录误判成源码根。
"""
from __future__ import annotations

import importlib.util
import os
from pathlib import Path
from typing import Optional, Sequence

REPO_ROOT = Path(__file__).resolve().parents[3]

TDEBUG_ROOT_ENV = "REACT_AGENT_TDEBUG_ROOT"


def installed_source_root(module: str) -> Optional[Path]:
    """按可导入包的 ``__init__.py`` 位置反推源码根；非源码安装返回 None。

    ``<source>/<module>/__init__.py`` → ``<source>``。site-packages 里
    ``parents[1]`` 不是 ``<module>``，因此会被拒绝。
    """
    try:
        spec = importlib.util.find_spec(module)
    except (ImportError, ValueError):  # 包存在但自身导入失败
        return None
    if spec is None or not spec.origin:
        return None
    origin = Path(spec.origin).resolve()
    if origin.parent.name != module:
        return None
    return origin.parents[1]


def source_root(
    module: str,
    *,
    env_var: str,
    dir_names: Sequence[str],
    marker: str = "examples",
) -> Optional[Path]:
    """返回同级仓库源码根；找不到可用 checkout 时返回 None。"""
    candidates: list[Path] = []
    override = (os.environ.get(env_var) or "").strip()
    if override:
        candidates.append(Path(override).expanduser())

    installed = installed_source_root(module)
    if installed is not None:
        candidates.append(installed)

    for name in dir_names:
        candidates.append(REPO_ROOT / name)
        candidates.append(REPO_ROOT.parent / name)

    for candidate in candidates:
        if (candidate / marker).is_dir():
            return candidate.resolve()
    return None


def trace_debugger_source_root() -> Optional[Path]:
    """trace-debugger 源码根（其 ``examples/publish_failure_snapshot.py`` 所在目录）。"""
    return source_root(
        "trace_debugger",
        env_var=TDEBUG_ROOT_ENV,
        dir_names=("trace-debugger", "trace_debugger"),
    )


__all__ = [
    "REPO_ROOT",
    "TDEBUG_ROOT_ENV",
    "installed_source_root",
    "source_root",
    "trace_debugger_source_root",
]
