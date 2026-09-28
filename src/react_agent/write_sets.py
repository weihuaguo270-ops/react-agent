"""写集（write set）声明与冲突判定。

并行 Worker **没有工作区隔离**（同一进程、同一工作目录），因此并行的安全性
依赖「写集声明 + 冲突分层」：同层任务若可能写同一路径，就必须串行。

本模块刻意不导入 planner / orchestrator，以打破两者的导入环：
- ``planner`` 需要它做冲突分层；
- ``orchestrator`` 需要它做执行分段。

判定规则（保守优先）：

======================  ==========================================
情况                    判定
======================  ==========================================
双方都显式声明且不相交  不冲突（可并行）
任一方为 None/空        冲突（保守串行）
任一方含 ``unknown``    冲突（planner 自述无法判断）
互为路径前缀            冲突（目录 vs 文件）
======================  ==========================================

路径比较前做归一化：统一分隔符、折叠重复斜杠、去尾部斜杠、小写（Windows
下大小写不敏感）。
"""

from __future__ import annotations

import os
from typing import Sequence

__all__ = [
    "UNKNOWN_WRITE_MARKERS",
    "normalize_write_path",
    "is_write_set_declared",
    "write_sets_may_conflict",
    "write_conflict_serialize_enabled",
]

#: planner 用来表示「无法判断写哪些文件」的标记。
UNKNOWN_WRITE_MARKERS: frozenset[str] = frozenset(
    {"unknown", "?", "unset", "none", "null", "tbd", "n/a"}
)


def write_conflict_serialize_enabled() -> bool:
    """同层写冲突是否强制串行。**默认开启**（2026-09-25 决策）。"""
    return os.environ.get(
        "REACT_AGENT_WRITE_CONFLICT_SERIALIZE", "1"
    ).strip().lower() in ("1", "true", "yes", "on")


def normalize_write_path(path: str) -> str:
    """归一化路径用于前缀比较：统一分隔符、去首尾空白与尾部斜杠、小写。"""
    normalized = (path or "").strip().replace("\\", "/")
    while "//" in normalized:
        normalized = normalized.replace("//", "/")
    normalized = normalized.rstrip("/") or normalized
    return normalized.lower()


def is_write_set_declared(writes: Sequence[str] | None) -> bool:
    """是否构成一次**有效声明**（非 None、非空、且不含 unknown 标记）。"""
    if not writes:
        return False
    return all(
        normalize_write_path(w) not in UNKNOWN_WRITE_MARKERS
        for w in writes
    )


def write_sets_may_conflict(
    a: Sequence[str] | None,
    b: Sequence[str] | None,
) -> bool:
    """两个写集是否**可能**冲突。未声明一律按冲突处理。"""
    if not is_write_set_declared(a) or not is_write_set_declared(b):
        return True
    for left in a:
        lpath = normalize_write_path(left)
        for right in b:
            rpath = normalize_write_path(right)
            if not lpath or not rpath:
                return True
            # 互为前缀（含目录/文件）即视为冲突
            if (
                lpath == rpath
                or lpath.startswith(rpath + "/")
                or rpath.startswith(lpath + "/")
            ):
                return True
    return False
