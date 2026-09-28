"""ToolScope — 委派给 Worker 时的工具面声明与解析。

设计原则（对齐 DSH subagent seam 的「fail loud, no silent degradation」）:

1. **显式声明优先**：允许哪些工具由配置/调用方声明，不由任务描述里的中文
   关键词猜测。关键词匹配在漏词时会静默给出错误工具集，且没有任何信号。
2. **未知名字必须可见**：声明里出现注册表中不存在的工具名时，strict 模式
   抛 :class:`UnknownToolScopeError`；非 strict 模式降级到声明的交集，但必须
   由调用方打印告警。绝不允许「因为不认识所以忽略」这种静默路径。
3. **空声明不等于全量**：空声明解析为空工具集。是否回退到全量由调用方显式
   决定，并且回退原因必须可见。
4. **只收窄不扩权**：:meth:`ToolScope.resolve` 只能从传入的工具定义里做子集，
   永远不新增工具——与 DSH ``toolFilter`` 的语义一致。

本模块刻意**不导入**任何项目内模块，因此不参与导入环，也便于单测。

**为什么放在顶层而不是 ``tools/`` 包内**：``react_agent.tools`` 的 ``__init__``
会挂载 app / workflow / experimental 工具（含 RAG），导入它等于触发一次较重的
模块装配。Orchestrator 需要在 core 路径上使用本模块，因此它必须能在**不导入
``react_agent.tools`` 包**的前提下被导入（由 ``tests/test_core_lazy_imports.py``
守卫）。
"""

from __future__ import annotations

import os
from typing import Iterable, Sequence

__all__ = [
    "UnknownToolScopeError",
    "ToolScope",
    "MAX_PROFILES",
    "DEFAULT_FALLBACK_PROFILES",
    "def_names",
    "profiles_from_tags",
    "scope_is_strict",
]


class UnknownToolScopeError(ValueError):
    """声明的工具名不在注册表中（strict 模式下抛出）。"""

    def __init__(self, unknown: Iterable[str]):
        self.unknown = sorted(set(unknown))
        joined = ", ".join(self.unknown)
        super().__init__(
            f"工具面声明包含注册表中不存在的工具: {joined}。"
            f"拼写错误或工具未启用时不会静默忽略；"
            f"请修正声明，或设置 REACT_AGENT_SCOPE_STRICT=0 以仅告警降级。"
        )


# ============================================================
# Profile 表：标签 → 该标签覆盖的工具名（显式清单）
# ============================================================
#
# 注意：这里是「按能力分组的显式清单」，不是关键词规则表。历史上本表放在
# orchestrator.py 并由 classify_tool_needs() 用中文关键词选取；关键词选取已
# 降级为兼容层（见 orchestrator.classify_tool_needs），匹配失败时不再静默兜底。
MAX_PROFILES: dict[str, frozenset[str]] = {
    "time": frozenset({"get_current_time", "convert_time", "get_time"}),
    "file": frozenset({
        "read_text_file", "write_file", "edit_file", "create_directory",
        "list_directory", "directory_tree", "move_file", "search_files",
        "get_file_info", "list_allowed_directories",
    }),
    "web": frozenset({"web_search", "fetch_page"}),
    "calc": frozenset({"calculator"}),
    "summary": frozenset({"summarize"}),
    "code": frozenset({"execute_python"}),
}

PROFILE_HINTS: dict[str, str] = {
    "time": "查询时间、时区转换",
    "file": "文件读写、目录管理、文件信息",
    "web": "搜索互联网、读取网页",
    "calc": "数学计算",
    "summary": "文本摘要",
    "code": "Python 代码执行、数据分析、脚本编写",
}

#: 关键词匹配失败时的历史兜底标签。默认**不再使用**（见 resolve_or_none）。
DEFAULT_FALLBACK_PROFILES: tuple[str, ...] = ("web", "calc")


def profiles_from_tags(tags: Iterable[str]) -> frozenset[str]:
    """把 profile 标签展开成工具名集合。

    未知标签本身也视为一种「未知名字」，但为保持旧的调用方行为（它们传的是
    内部标签而非工具名），这里只忽略未知标签；标签到工具名的展开结果会在
    :meth:`ToolScope.resolve` 阶段与注册表求交集并被报告。
    """
    names: set[str] = set()
    for tag in tags:
        key = (tag or "").strip().lower()
        if key in MAX_PROFILES:
            names |= MAX_PROFILES[key]
    return frozenset(names)


def scope_is_strict() -> bool:
    """是否对未知工具名抛错。``REACT_AGENT_SCOPE_STRICT`` 默认关闭（仅告警）。

    默认关闭是为了不打断现有调用方；一个发布周期后再考虑翻转默认值。
    """
    return os.environ.get("REACT_AGENT_SCOPE_STRICT", "").strip().lower() in (
        "1", "true", "yes", "on",
    )


class ToolScope:
    """一次委派的工具面声明。

    >>> ToolScope.from_profiles(["calc"]).resolve(defs, registry_names)
    ([<calculator def>], [], ['calculator'])
    """

    __slots__ = ("names", "source")

    def __init__(self, names: Iterable[str], source: str = "explicit"):
        self.names: frozenset[str] = frozenset(
            (n or "").strip() for n in names if (n or "").strip()
        )
        #: 声明来源，仅用于日志/轨迹（"explicit" / "planner" / "profiles:calc"）
        self.source = source

    # ----- 构造 -----

    @classmethod
    def from_profiles(cls, tags: Iterable[str], source: str | None = None) -> "ToolScope":
        tags = list(tags)
        return cls(
            profiles_from_tags(tags),
            source=source or f"profiles:{','.join(sorted(tags)) or '(empty)'}",
        )

    @classmethod
    def full(cls, all_defs: Sequence[dict]) -> "ToolScope":
        """全量工具面。仅应由调用方在**显式决定**回退到全量时使用。"""
        return cls(def_names(all_defs), source="full")

    @classmethod
    def empty(cls) -> "ToolScope":
        return cls((), source="empty")

    # ----- 查询 -----

    def __bool__(self) -> bool:
        return bool(self.names)

    def __repr__(self) -> str:  # pragma: no cover - 诊断用
        return f"<ToolScope {self.source} n={len(self.names)}>"

    # ----- 解析 -----

    def split(
        self,
        all_defs: Sequence[dict],
        registry_names: Iterable[str] | None = None,
    ) -> tuple[list[dict], list[str], list[str]]:
        """解析为 (保留的定义, 未知名字, 被本 scope 排除的已注册工具名)。

        未知名字 = 声明里不在注册表中的项；
        被排除的 = 注册表里有、但声明没要的项。
        两者都返回，便于调用方给出「暴露 N/M，未知 K」这类可诊断输出。
        """
        available = {_def_name(d) for d in all_defs if _def_name(d)}
        registered = set(registry_names) if registry_names is not None else set(available)

        unknown = sorted(n for n in self.names if n not in registered)
        kept = [d for d in all_defs if _def_name(d) in self.names]
        excluded = sorted(n for n in registered if n not in self.names)
        return kept, unknown, excluded

    def resolve(
        self,
        all_defs: Sequence[dict],
        registry_names: Iterable[str] | None = None,
        *,
        strict: bool | None = None,
    ) -> tuple[list[dict], list[str]]:
        """解析为 (工具定义列表, 未知名字)。

        strict 为真（或环境变量开启）且存在未知名字时抛
        :class:`UnknownToolScopeError`。
        """
        kept, unknown, _ = self.split(all_defs, registry_names)
        if unknown and (scope_is_strict() if strict is None else strict):
            raise UnknownToolScopeError(unknown)
        return kept, unknown

    def describe(self, total: int | None = None, unknown: Sequence[str] = ()) -> str:
        """人类可读的一行摘要，供日志与轨迹使用。"""
        parts = [f"工具面({self.source}): {len(self.names)} 个声明"]
        if total is not None:
            parts.append(f"解析后暴露 / 可用 {total}")
        if unknown:
            parts.append(f"未知 {len(unknown)}: {', '.join(unknown)}")
        return "，".join(parts)


def def_names(all_defs: Iterable[dict]) -> set[str]:
    """从工具定义列表里取出全部工具名（无成本，不触发任何导入）。"""
    names: set[str] = set()
    for definition in all_defs or ():
        name = _def_name(definition)
        if name:
            names.add(name)
    return names


def _def_name(definition: dict) -> str:
    """从工具定义里取名字；结构异常时返回空串而不是抛错。"""
    try:
        return (definition.get("function") or {}).get("name") or ""
    except AttributeError:
        return ""
