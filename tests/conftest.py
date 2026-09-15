"""pytest 启动时优先加载项目 .env，并降低沙箱副作用。"""

import os
from pathlib import Path

from react_agent.llm import _load_dotenv

_load_dotenv(override=True)

# 集成测试默认关闭沙箱预热递归风险；需要测沙箱时用例可自行打开
os.environ.setdefault("REACT_AGENT_SANDBOX_CHILD", "")


def pytest_configure(config):
    # Prefer an in-repo basetemp; if the legacy .pytest-tmp path is locked
    # (common on this managed Windows host), fall back to a fresh writable dir.
    root = Path(__file__).resolve().parents[1]
    preferred = root / ".pytest-tmp"
    fallback = root / ".pytest-basetemp"
    basetemp = preferred
    try:
        preferred.mkdir(parents=True, exist_ok=True)
        probe = preferred / ".write_probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
    except OSError:
        basetemp = fallback
        basetemp.mkdir(parents=True, exist_ok=True)
    config.option.basetemp = str(basetemp)
    try:
        from react_agent.harness.sandbox import SANDBOX
        # 真实 LLM 测试里网络工具若再进沙箱，易叠加超时；默认 auto 保留，但关闭预热副作用
        SANDBOX._prewarmed = True  # 标记已预热，避免导入后再触发重型预热
    except Exception:
        pass
