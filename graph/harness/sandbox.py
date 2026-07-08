"""Sandbox — LangGraph 版工具沙箱隔离

直接复用手写版的 Sandbox 类和三策略逻辑。
graph/ 和手写版共享同一份风险分类和子进程执行代码。
"""

import os
import sys

# 把 repo 根目录加入 path，直接导入 harness.sandbox
_repo_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _repo_dir not in sys.path:
    sys.path.insert(0, _repo_dir)

# 子进程 runner 路径（共享手写版的 _sandbox_runner.py）
RUNNER_PATH = os.path.join(
    _repo_dir,
    "harness",
    "_sandbox_runner.py",
)

# 直接复用手写版的类
from harness.sandbox import Sandbox  # noqa: E402
from harness.sandbox import should_sandbox_by_risk, classify_risk, VALID_STRATEGIES  # noqa: E402, F401
