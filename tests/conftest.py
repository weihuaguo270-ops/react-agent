"""pytest 启动时优先加载项目 .env，并降低沙箱副作用。"""

import os
import shutil
from pathlib import Path

from react_agent.llm import _load_dotenv

_load_dotenv(override=True)

# 集成测试默认关闭沙箱预热递归风险；需要测沙箱时用例可自行打开
os.environ.setdefault("REACT_AGENT_SANDBOX_CHILD", "")
# CI/离线套件需能执行副作用 CONFIRM（如 execute_python）。生产默认仍是 async；
# 测默认 async 的用例应显式 delenv / 设 async。
os.environ.setdefault("REACT_AGENT_APPROVAL_MODE", "auto_allow")


def _usable_basetemp(path: Path) -> bool:
    """判断 pytest 能否安全接管这个 basetemp 路径。

    pytest 在会话开始时 rmtree 已存在的 basetemp（_pytest/tmpdir.py），所以
    「目录存在但删不掉」会让每个用例在 setup 阶段抛 WinError 5 —— 在托管
    Windows 主机上，遗留目录可能属于另一个沙箱身份，当前用户只有只读权限。
    这里按 pytest 的实际行为探测：先删除、再创建、再写探针。
    """
    try:
        if path.exists():
            shutil.rmtree(path)
        path.mkdir(parents=True)
        probe = path / ".write_probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        return True
    except OSError:
        return False


def _install_permissive_mkdir() -> None:
    """把 mode=0o700 的目录创建降级为 0o755。

    CPython 的 ``tempfile.mkdtemp`` 和 pytest 的 ``tmp_path`` 都硬编码
    ``mode=0o700``（_pytest/tmpdir.py:139,158）。Windows 上该 mode 生成的 DACL
    只含属主 SID；在受限沙箱令牌下这些目录既不可写也不可删（WinError 5），于是
    tmp_path / RAG 基准等用例必然失败。仅在显式开启时安装，正常环境行为不变。
    """
    original_mkdir = os.mkdir

    def mkdir(path, mode=0o777, *args, **kwargs):
        if mode == 0o700:
            mode = 0o755
        return original_mkdir(path, mode, *args, **kwargs)

    os.mkdir = mkdir


def _permissive_test_dirs_enabled() -> bool:
    return os.environ.get("REACT_AGENT_PERMISSIVE_TEST_DIRS", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def pytest_configure(config):
    root = Path(__file__).resolve().parents[1]

    if _permissive_test_dirs_enabled():
        # 受限沙箱：先让 0o700 目录可访问，再用本进程专属的全新 basetemp
        # （遗留路径可能已被别的身份锁死，探测也无济于事）。
        _install_permissive_mkdir()
        basetemp = root / f".pytest-tmp-{os.getpid()}"
    else:
        # 优先仓库内 basetemp；遗留路径被锁时逐个探测后回退。
        basetemp = next(
            (c for c in (root / ".pytest-tmp", root / ".pytest-basetemp")
             if _usable_basetemp(c)),
            root / ".pytest-basetemp",
        )
    config.option.basetemp = str(basetemp)

    try:
        from react_agent.harness.sandbox import SANDBOX
        # 真实 LLM 测试里网络工具若再进沙箱，易叠加超时；默认 auto 保留，但关闭预热副作用
        SANDBOX._prewarmed = True  # 标记已预热，避免导入后再触发重型预热
    except Exception:
        pass
