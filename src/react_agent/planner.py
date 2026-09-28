"""
任务规划器（Planner）— LLM 驱动的任务分解 + 依赖分析

让 LLM 自动将用户请求分解为子任务，并分析任务间的依赖关系。
通过拓扑排序确定执行顺序：无依赖的先执行（可并行），有依赖的等前置完成。

用法:
    from react_agent.planner import PLANNER
    tasks = PLANNER.plan("查今天和明天的天气，对比温差")
    # → [Task(id='1', desc='搜索今天天气', depends_on=[]),
    #     Task(id='2', desc='搜索明天天气', depends_on=[]),
    #     Task(id='3', desc='对比温差', depends_on=['1', '2'])]
"""

from typing import Optional


# ============================================================
# 1. Task 数据类
# ============================================================
class Task:
    """一个可调度的任务单元

    属性:
        id:         任务编号（"1", "2", ...）
        description: 任务描述
        depends_on:  依赖的任务 ID 列表，这些任务必须完成才能执行本任务
        writes:      该任务**可能写入**的路径列表；None 表示未声明。
                     ``["unknown"]`` 表示 planner 明确表示无法判断。未声明与
                     unknown 在调度时都按「可能冲突」保守处理（见
                     orchestrator._write_sets_may_conflict）。
        context_mode: 该 Worker 的上下文策略（"spawn" 全新 / "fork" 摘要式续接）
        result:      执行结果（执行前为 None）
    """
    def __init__(
        self,
        id: str,
        description: str,
        depends_on: list[str] = None,
        writes: list[str] | None = None,
        context_mode: str = "spawn",
    ):
        self.id = id
        self.description = description
        self.depends_on = depends_on or []
        self.writes = writes
        self.context_mode = context_mode
        self.result = None

    def ready(self, completed_ids: set[str]) -> bool:
        """检查当前任务是否已经满足依赖（可以执行了）"""
        return all(dep in completed_ids for dep in self.depends_on)

    def __repr__(self):
        deps = f", 依赖: {self.depends_on}" if self.depends_on else ""
        writes = f", 写: {self.writes}" if self.writes else ""
        return f"<Task #{self.id}: {self.description[:40]}{deps}{writes}>"


# ============================================================
# 2. Planner 核心类
# ============================================================

_PLAN_PROMPT = """你是一个专业的任务分解专家。将用户的请求拆成可执行的子任务，并分析任务之间的依赖关系。

要求：
- 每个子任务只做一件事
- 用 task_N: 描述 的格式
- 如果某个任务依赖其他任务先完成，在后面加 | depends_on: N, M
- 如果某个任务会**写入文件**，必须加 | writes: 路径1, 路径2（写目录就写目录）
- 无法判断会写哪些文件时，写 | writes: unknown —— 不要猜，也不要省略
- 只有当该子任务**必须基于前面的对话结论才能做**时，才加 | context: fork
  （fork 只会拿到父会话的答案摘要，不是完整历史，因此不要滥用）
- 没有依赖且写集不相交的任务才会被并行执行
- 不要解释，直接输出任务列表

例子1（搜索+对比）:
请求: 搜索今天和明天的天气，对比温差
输出:
task_1: 搜索今天北京天气
task_2: 搜索明天北京天气
task_3: 对比今天和明天的温差 | depends_on: 1, 2

例子2（计算）:
请求: 帮我查一下计算器的历史，然后算一下123*456
输出:
task_1: 搜索计算器的历史
task_2: 计算123乘以456

例子3（搜索+总结+写作）:
请求: 搜索最新的AI新闻，用中文总结，然后写一个Twitter帖子
输出:
task_1: 搜索最新AI新闻
task_2: 用中文总结搜索到的AI新闻 | depends_on: 1
task_3: 写一个关于AI新闻的Twitter帖子 | depends_on: 2

例子4（代码生成+计算）:
请求: 用Python生成10个随机数，并计算它们的平均值和标准差
输出:
task_1: 用Python生成10个随机数
task_2: 计算平均值和标准差 | depends_on: 1

例子5（代码+多步分析）:
请求: 同时生成一个3x3随机矩阵，并计算每行每列的和
输出:
task_1: 用Python生成3x3随机矩阵
task_2: 计算每行每列的和 | depends_on: 1

例子6（分文件写入，写集不相交可并行）:
请求: 给前端页面加错误提示，给后端接口加校验，各自补测试
输出:
task_1: 修改前端页面的错误提示 | writes: src/pages/login.tsx
task_2: 给后端接口加参数校验 | writes: src/api/validate.py
task_3: 补前端测试 | writes: tests/test_login.py | depends_on: 1
task_4: 补后端测试 | writes: tests/test_validate.py | depends_on: 2

现在处理以下请求：
请求: {query}
输出:"""


# ============================================================
# 指令段解析辅助（模块级，便于单测）
# ============================================================

def _normalize_directive_name(name: str) -> str:
    """把指令名归一化：去掉 ``_``/``-``/空格并转小写。

    LLM 常见变体（``depends-on`` / ``dependsOn`` / ``DEPENDS ON``）因此都能命中，
    避免"因为写法不同所以整条指令丢失"。
    """
    return "".join(
        ch for ch in (name or "").strip().lower() if ch.isalnum()
    )


def _split_directive(segment: str) -> tuple[str, str]:
    """把 ``"depends_on: 1, 2"`` 拆成 ``("dependson", "1, 2")``。

    无冒号时按「首个空白」拆名与值（``"writes src/a.py"``），
    这样模型偶尔漏掉冒号也不会把整条指令当成未知指令。
    """
    if ":" in segment:
        name, _, value = segment.partition(":")
        return _normalize_directive_name(name), value.strip()
    parts = segment.split(None, 1)
    if not parts:
        return "", ""
    return _normalize_directive_name(parts[0]), (parts[1].strip() if len(parts) > 1 else "")


def _looks_like_write_path(candidate: str) -> bool:
    """判断一个 ``writes`` 值是否像**真实路径**。

    这是安全性判断（宁可误杀不可放过）：一个"看起来像声明、实际是垃圾"的值会让
    调度器误以为该任务写集已知且不相交，从而放行并行写——这比保守串行危险得多。
    因此只接受严格形态：带引号、无空白的单 token，或裸的窄字符集 token（允许空格
    是因为 Windows 上确有带空格的文件名）。
    """
    token = candidate.strip()
    if len(token) >= 2 and token[0] == token[-1] and token[0] in "\"'":
        inner = token[1:-1].strip()
        return bool(inner) and not any(ch in inner for ch in "\"';|*?<>")
    if not token or len(token) > 260:
        return False
    if any(ch in token for ch in "()[]{}`;|*?<>\"'"):
        return False
    if any(ord(ch) < 32 for ch in token):
        return False
    # 允许空格，但禁止"说明性文字"的典型形态
    bad_words = ("新建", "修改", "新增", "以及", "和", "等等", "待定", "todo")
    if any(word in token.lower() for word in bad_words):
        return False
    return True


def _parse_writes_value(value: str) -> tuple[list[str] | None, list[str]]:
    """解析 ``writes`` 的值，返回 ``(写集或 None, 被判为非路径的值)``。

    只要有**任何一个**值不像路径，整条声明就降级为 ``None``（未声明 → 调度器按
    可能冲突保守串行），并把可疑值返回给调用方打印告警。不做部分采纳——部分采纳
    会制造「以为声明完整、其实漏了一个路径」的假安全。
    """
    if not value.strip():
        return None, []
    raw = [
        item.strip()
        for item in value.replace("，", ",").split(",")
        if item.strip()
    ]
    if not raw:
        return None, []
    suspicious = [item for item in raw if not _looks_like_write_path(item)]
    if suspicious:
        return None, suspicious
    unknown_markers = {"unknown", "?", "unset", "none", "null", "tbd", "n/a"}
    if all(item.strip().lower() in unknown_markers for item in raw):
        return raw, []
    return raw, []


class Planner:
    """任务规划器

    用法:
        planner = Planner()

        def my_llm(messages):
            return call_llm(messages)

        tasks = planner.plan("搜索今天天气并对比明天", llm_call=my_llm)
        order = planner.schedule(tasks)
        # order = [[task1, task2], [task3]]  # 同层可并行
    """

    # 模板匹配列表（优先于 LLM 分解，零成本、稳定）
    # 每项: (正则, 构建函数) — 正则匹配则直接用函数构建任务列表
    _TEMPLATES = [
        # 搜索+对比类: "搜索今天和明天的天气" "查A和B"
        (r"(?:搜索|查|查找|搜一下)(.+?)(?:和|与|跟|、)(.+)",
         lambda m: [
             Task("1", f"搜索{m.group(1).strip()}"),
             Task("2", f"搜索{m.group(2).strip()}"),
             Task("3", "对比分析", depends_on=["1", "2"]),
         ]),
        # 代码生成+计算类: "生成10个随机数，计算平均值" "用Python生成..."
        (r"(?:用Python|使用Python|通过Python)?(?:生成|创建|构造)(.+?)(?:，|,)(?:并)?(?:计算|统计|分析)(.+)",
         lambda m: [
             Task("1", f"用Python生成{m.group(1).strip()}"),
             Task("2", f"计算{m.group(2).strip()}", depends_on=["1"]),
         ]),
        # 计算类: "计算123*456" "算一下..."
        (r"(?:计算|算一下|算)(.+)",
         lambda m: [
             Task("1", f"计算{m.group(1).strip()}"),
         ]),
        # 搜索单个: "搜索XXX" "查XXX"
        (r"(?:搜索|查|查找|搜一下)(.+)",
         lambda m: [
             Task("1", f"搜索{m.group(1).strip()}"),
         ]),
    ]

    def __init__(self):
        self._last_query = ""

    def plan(self, query: str, llm_call: callable = None) -> list[Task]:
        """分解任务为子任务

        优先匹配模板（零 LLM 调用），未命中则走 LLM 自动分解。
        """
        self._last_query = query

        # 第1关：模板匹配（模型无关、零成本、稳定）
        import re
        for pattern, builder in self._TEMPLATES:
            m = re.search(pattern, query)
            if m:
                tasks = builder(m)
                if tasks:
                    return tasks

        # 第2关：兜底走 LLM 自动分解
        if llm_call is None:
            return []
        prompt = _PLAN_PROMPT.format(query=query)
        msg = llm_call([
            {"role": "system", "content": "你是一个专业的任务分解助手，严格按格式输出。"},
            {"role": "user", "content": prompt},
        ])
        content = (msg.get("content", "") or "").strip()
        return self._parse_tasks(content)

    @staticmethod
    def _parse_tasks(text: str) -> list[Task]:
        """解析 LLM 输出为 Task 列表

        解析格式:
            task_1: 描述文字
            task_2: 描述文字 | depends_on: 1
            task_3: 描述文字 | writes: src/a.py, tests/a_test.py
            task_4: 描述文字 | writes: unknown

        多个指令可以并列出现（``| depends_on: 1 | writes: a.py | context: fork``）。

        鲁棒性约定（对齐 Phase 1 的「未知即可见」原则）：
        - 指令名归一化后（去掉 ``_``/``-``/空格、转小写）前缀匹配，因此
          ``writes`` / ``Writes`` / ``WRITES`` / ``writes_on`` 均可识别；
        - **不再用宽泛的 ``in`` 匹配指令名**——那会让 ``writes: depends_on_x.py``
          被误判成依赖指令，产生一个永远无法满足的垃圾依赖；
        - 不认识的指令、以及解析不出值的指令，**直接丢弃并打印告警**，绝不静默；
        - ``writes`` 的值若不像路径（含 ``;``、说明性文字、反引号等），整条声明按
          ``unknown`` 处理——**宁可保守串行，也不接受一个假的"安全声明"**。
        """
        tasks = []
        for line in text.split("\n"):
            line = line.strip()
            if not line:
                continue

            # 匹配 task_N: 开头
            if not line.startswith("task_"):
                continue

            # 去掉 task_N: 前缀
            rest = line.split(":", 1)[1].strip() if ":" in line else ""

            # 分离描述与指令段（描述里出现 | 会截断，这是格式契约的一部分）
            segments = [seg.strip() for seg in rest.split("|")]
            description = segments[0].strip() if segments else ""
            depends_on: list[str] = []
            writes: list[str] | None = None
            context_mode = "spawn"

            for seg in segments[1:]:
                if not seg:
                    continue
                name, value = _split_directive(seg)
                if name == "dependson":
                    depends_on = [
                        d.strip() for d in value.replace("，", ",").split(",") if d.strip()
                    ]
                elif name == "writes":
                    writes, rejected = _parse_writes_value(value)
                    if rejected:
                        print(
                            f"[Planner] writes 值不像路径，按 unknown 处理（保守串行）: "
                            f"{', '.join(rejected)}"
                        )
                elif name == "context":
                    # 只有显式写 fork 才启用；不猜测、不默认继承父会话
                    context_mode = "fork" if value.strip().lower() == "fork" else "spawn"
                else:
                    print(
                        f"[Planner] 忽略无法识别的指令 {seg!r}"
                        f"（已支持 depends_on / writes / context）"
                    )

            if description:
                tasks.append(Task(
                    id=str(len(tasks) + 1),
                    description=description,
                    depends_on=depends_on,
                    writes=writes,
                    context_mode=context_mode,
                ))

        return tasks

    @staticmethod
    def schedule(tasks: list[Task]) -> list[list[Task]]:
        """拓扑排序：确定任务的执行层级

        返回:
            [[level0_tasks], [level1_tasks], ...]
            同层可以并行执行，不同层必须按顺序
        """
        remaining = {t.id: t for t in tasks}
        levels = []

        while remaining:
            current_level = []
            for tid in list(remaining.keys()):
                t = remaining[tid]
                # 检查所有依赖是否已在之前的层级中完成
                if all(dep not in remaining for dep in t.depends_on):
                    current_level.append(t)

            if not current_level:
                # 死锁检测：还有任务但无法推进（可能有循环依赖）
                break

            for t in current_level:
                del remaining[t.id]

            # 按 ID 排序保持稳定顺序
            current_level.sort(key=lambda x: int(x.id) if x.id.isdigit() else 0)
            levels.append(current_level)

        return levels

    @staticmethod
    def describe_schedule(levels: list[list[Task]]) -> str:
        """把调度层级格式化成可读文本"""
        lines = [f"共 {sum(len(l) for l in levels)} 个任务，{len(levels)} 个层级："]
        for i, level in enumerate(levels):
            task_desc = ", ".join([f"#{t.id} {t.description[:30]}" for t in level])
            parallel = "（可并行）" if len(level) > 1 else ""
            lines.append(f"  第{i+1}层: {task_desc}{parallel}")
        return "\n".join(lines)

    @staticmethod
    def schedule_with_write_conflicts(tasks: list[Task]) -> list[list[Task]]:
        """拓扑排序 + **同层写冲突分层**。

        在 :meth:`schedule` 的分层基础上，把同一层内写集可能相交的任务拆到
        后续子层，保证「同一层内并行执行的任务写集互不相交」。

        未声明写集（``None``）与 ``["unknown"]`` 一律按「可能冲突」处理：
        宁可串行，不猜。

        依赖关系不受影响——被推迟的任务仍在同一次调用内执行完毕，只是排到
        本层的后续段。
        """
        # 懒加载以避免与 runtime 层形成导入环
        from react_agent.write_sets import write_sets_may_conflict

        levels = Planner.schedule(tasks)
        stratified: list[list[Task]] = []
        for level in levels:
            groups: list[list[Task]] = []
            for task in level:
                for group in groups:
                    if all(
                        not write_sets_may_conflict(task.writes, other.writes)
                        for other in group
                    ):
                        group.append(task)
                        break
                else:
                    groups.append([task])
            stratified.extend(groups)
        return stratified


# ============================================================
# 3. 全局实例
# ============================================================

PLANNER = Planner()


# ============================================================
# 4. 工具定义（供 react_loop.py 注册）
# ============================================================

PLANNER_TOOL_DEFINITION = {
    "type": "function",
    "function": {
        "name": "plan_tasks",
        "description": "将复杂请求拆成子任务并分析它们的依赖关系。"
                       "适用于需要多步骤、前后有依赖的复杂任务。"
                       "返回每个子任务及其依赖关系。",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "要分解的请求"
                },
            },
            "required": ["query"],
        },
    },
}


# ============================================================
# 5. 工具函数（注入 llm_call 后用）
# ============================================================

_planner_llm_call = None


def set_planner_llm_call(func):
    """设置 Planner 使用的 LLM 调用函数"""
    global _planner_llm_call
    _planner_llm_call = func


def tool_plan_tasks(query: str) -> str:
    """在 ReAct Loop 中调用的任务分解工具"""
    global _planner_llm_call
    if _planner_llm_call is None:
        return "错误: Planner 的 LLM 调用函数未设置"

    planner = Planner()
    tasks = planner.plan(query, llm_call=_planner_llm_call)
    if not tasks:
        return "未能分解任务"

    levels = planner.schedule(tasks)
    output = [f"[Planner] 分解为 {len(tasks)} 个子任务："]
    for t in tasks:
        deps = f"（等待 {'、'.join(['#' + d for d in t.depends_on])}）" if t.depends_on else "（无依赖，可立即执行）"
        writes = f" 写集: {', '.join(t.writes)}" if t.writes else " 写集: 未声明"
        output.append(f"  #{t.id}: {t.description} {deps}{writes}")

    output.append("")
    output.append(planner.describe_schedule(levels))
    return "\n".join(output)
