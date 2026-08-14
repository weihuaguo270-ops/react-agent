"""Harness — Agent 运行保障层

将 Sandbox（沙箱隔离）、Recorder（轨迹记录）、Replay（回放调试）
合并为统一入口，概念上对应 Agent = LLM + Harness 中的 Harness。

使用方式:
    from react_agent.harness import Harness
    h = Harness()
    h.start_session(query, model, system_prompt)
    # Agent 运行...
    h.add_step(step, thought=..., action_name=..., result=...)
    h.set_final_answer(...)
    h.save()
"""

from .recorder import Trajectory, start_trajectory, current_trajectory, finish_trajectory
from .sandbox import Sandbox, SANDBOX, SANDBOX_TOOL_DEFINITION, tool_toggle_sandbox
from .replay import Replay, Replayer
from .schema import (
    assert_valid,
    load_and_validate,
    normalize_trajectory,
    validate_trajectory,
    TrajectorySchemaError,
)

# ----------
# 统一入口
# ----------
class Harness:
    """统一 Harness 层

    同时管理轨迹记录、沙箱隔离和重放调试。
    """

    def __init__(self, sandbox_enabled: bool = False, sandbox_timeout: int = 30):
        self.recorder = None
        self.sandbox = Sandbox(enabled=sandbox_enabled, timeout=sandbox_timeout)
        self.replayer = Replay()

    # --- 轨迹记录 (委托给 recorder 模块) ---
    def start_session(self, query: str, model: str = "", system_prompt: str = "") -> "Harness":
        """创建并绑定一条新的进程级当前轨迹。"""
        self.recorder = start_trajectory(query, model, system_prompt)
        return self

    def add_step(self, step: int, thought: str = "",
                 action_name: str = "", action_args: str = "",
                 result: str = "", tokens: int = 0) -> "Harness":
        """向已开始的会话追加步骤；无会话时保持空操作兼容。"""
        if self.recorder:
            self.recorder.add_step(step, thought, action_name, action_args, result, tokens)
        return self

    def set_final_answer(self, answer: str) -> "Harness":
        """设置当前轨迹终答；无会话时保持空操作兼容。"""
        if self.recorder:
            self.recorder.set_final_answer(answer)
        return self

    def save(self) -> str:
        """保存并返回文件路径"""
        if self.recorder:
            return self.recorder.save()
        return ""

    # --- 沙箱 (委托给 sandbox 模块) ---
    @property
    def sandbox_enabled(self) -> bool:
        """返回 Harness 沙箱策略是否启用。"""
        return self.sandbox.enabled

    @sandbox_enabled.setter
    def sandbox_enabled(self, value: bool):
        """切换普通沙箱策略；required 模式仍会拒绝关闭。"""
        self.sandbox.enabled = value

    def run_sandboxed(self, tool_call: dict) -> str:
        """通过 Harness 绑定的隔离后端执行工具调用。"""
        return self.sandbox.run(tool_call)

    # --- 重放 (委托给 replay 模块) ---
    def list_recordings(self, directory: str = "") -> list:
        """列出指定目录或默认目录中的可回放轨迹。"""
        return self.replayer.list_recordings(directory)

    def playback(self, filepath: str, step_by_step: bool = False):
        """加载轨迹并按连续或逐步模式回放。"""
        return self.replayer.play(filepath, step_by_step=step_by_step)

    # --- 直接入口 (兼容旧接口) ---
    def start_trajectory(self, query, model="", system_prompt=""):
        """兼容旧调用方，直接创建进程级当前轨迹。"""
        return start_trajectory(query, model, system_prompt)

    @property
    def current(self):
        """返回进程级当前轨迹；未开始时返回 ``None``。"""
        return current_trajectory()

    @staticmethod
    def finish_trajectory(answer=""):
        """保存并清除进程级当前轨迹。"""
        return finish_trajectory(answer)


# 注册工具
TOOL_DEFINITIONS = [SANDBOX_TOOL_DEFINITION]
