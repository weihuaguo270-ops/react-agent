"""工具执行隔离。

process 后端只隔离崩溃和超时，不是安全边界。container 后端通过非 root、
只读根文件系统、最小环境、默认断网和资源配额提供系统权限隔离。
生产环境应同时设置 REACT_AGENT_SANDBOX_REQUIRED=1、
REACT_AGENT_SANDBOX_BACKEND=container 和 REACT_AGENT_SANDBOX_STRATEGY=on。
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import uuid
from pathlib import Path
from typing import Any

_RUNNER_PATH = Path(__file__).with_name("_sandbox_runner.py")
_PACKAGE_SRC = Path(__file__).resolve().parents[2]
_SANDBOX_CHILD_ENV = "REACT_AGENT_SANDBOX_CHILD"

VALID_STRATEGIES = ("off", "auto", "on")
VALID_BACKENDS = ("process", "container")

RISK_CONTROL = "control"
RISK_SAFE = "safe"
RISK_IO = "io"
RISK_CPU = "cpu"
RISK_UNTRUSTED = "untrusted"

CONTROL_PLANE_TOOLS = {"toggle_sandbox"}
SAFE_TOOLS = {
    "get_time",
    "get_current_time",
    "calculator",
    "switch_cot_strategy",
    "switch_role",
    "switch_context_strategy",
}
IO_TOOLS = {
    "web_search",
    "fetch_page",
    "rag_query",
    "clear_trajectories",
    "search_docs",
    "lookup_api",
    "fetch_trace",
    "search_files",
    "read_text_file",
    "list_directory",
    "directory_tree",
    "get_file_info",
}
CPU_TOOLS = {"summarize", "tot_reasoning", "execute_python"}
NETWORK_TOOLS = {"web_search", "fetch_page"}

_CONTAINER_ENV_ALLOWLIST = {
    "REACT_AGENT_APP",
    "REACT_AGENT_DEFAULT_APP",
    "REACT_AGENT_EXPERIMENTAL_TOOLS",
    "REACT_AGENT_RAG_MODE",
    "REACT_AGENT_DATA_DIR",
    "REACT_AGENT_MEMORY_FILE",
    "REACT_AGENT_RAG_INDEX",
    "REACT_AGENT_TRAJECTORY_DIR",
    "REACT_AGENT_REPORT_DIR",
    "REACT_AGENT_DOCS_INDEX_DIR",
}

_PROCESS_ENV_ALLOWLIST = {
    "PATH",
    "PATHEXT",
    "SYSTEMROOT",
    "WINDIR",
    "COMSPEC",
    "TEMP",
    "TMP",
    "LANG",
    "LC_ALL",
    "SSL_CERT_FILE",
    "REQUESTS_CA_BUNDLE",
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "NO_PROXY",
    "HOME",
    "USERPROFILE",
    "HOMEDRIVE",
    "HOMEPATH",
    "REACT_AGENT_APP",
    "REACT_AGENT_DEFAULT_APP",
    "REACT_AGENT_EXPERIMENTAL_TOOLS",
    "REACT_AGENT_RAG_MODE",
    "REACT_AGENT_SKIP_RAG",
    "REACT_AGENT_DATA_DIR",
    "REACT_AGENT_MEMORY_FILE",
    "REACT_AGENT_RAG_INDEX",
    "REACT_AGENT_TRAJECTORY_DIR",
    "REACT_AGENT_REPORT_DIR",
    "REACT_AGENT_DOCS_INDEX_DIR",
}
_NETWORK_NAME_RE = re.compile(r"^[A-Za-z0-9_.-]{1,128}$")
_MEMORY_RE = re.compile(r"^[1-9][0-9]*(?:[bkmgBKMG])?$")
_CPU_RE = re.compile(r"^(?:0[.][1-9][0-9]*|[1-9][0-9]*(?:[.][0-9]+)?)$")


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _bounded_int(name: str, default: int, minimum: int, maximum: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} 必须是整数") from exc
    if not minimum <= value <= maximum:
        raise ValueError(f"{name} 必须在 {minimum}..{maximum} 之间")
    return value


def _validated_value(name: str, default: str, pattern: re.Pattern[str]) -> str:
    value = os.environ.get(name, default).strip()
    if not pattern.fullmatch(value):
        raise ValueError(f"{name} 的值不合法: {value!r}")
    return value


def _in_sandbox_child() -> bool:
    return os.environ.get(_SANDBOX_CHILD_ENV) == "1"


def _runner_env(
    tool_name: str,
    max_output: int,
    max_input: int,
) -> dict[str, str]:
    """只向进程后端传递运行所需配置，不继承 API Key 等宿主秘密。"""
    env = {
        key: value
        for key, value in os.environ.items()
        if key.upper() in _PROCESS_ENV_ALLOWLIST
    }
    env.update(
        {
            "PYTHONIOENCODING": "utf-8",
            _SANDBOX_CHILD_ENV: "1",
            "REACT_AGENT_DISABLE_MCP": "1",
            "REACT_AGENT_SANDBOX_ALLOWED_TOOLS": tool_name,
            "REACT_AGENT_SANDBOX_MAX_OUTPUT": str(max_output),
            "REACT_AGENT_SANDBOX_MAX_INPUT": str(max_input),
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONPATH": str(_PACKAGE_SRC),
        }
    )
    return env


def classify_risk(tool_name: str) -> str:
    """返回工具风险类别；未知工具按不可信处理。"""
    if tool_name in CONTROL_PLANE_TOOLS:
        return RISK_CONTROL
    if tool_name in SAFE_TOOLS:
        return RISK_SAFE
    if tool_name in IO_TOOLS:
        return RISK_IO
    if tool_name in CPU_TOOLS:
        return RISK_CPU
    return RISK_UNTRUSTED


def should_sandbox_by_risk(tool_name: str, strategy: str) -> bool:
    """控制面工具始终在宿主执行，其余工具按策略决定。"""
    if strategy not in VALID_STRATEGIES:
        raise ValueError(f"未知沙箱策略: {strategy}")
    if classify_risk(tool_name) == RISK_CONTROL:
        return False
    if strategy == "on":
        return True
    if strategy == "off":
        return False
    return classify_risk(tool_name) in {RISK_IO, RISK_CPU, RISK_UNTRUSTED}


def _ensure_runner() -> None:
    if not _RUNNER_PATH.is_file():
        raise RuntimeError(f"沙箱 Runner 不存在: {_RUNNER_PATH}")


def _decode_runner_result(
    *,
    tool_name: str,
    returncode: int,
    stdout: str | None,
    stderr: str | None,
) -> str:
    out = (stdout or "").strip()
    err = (stderr or "").strip()
    try:
        envelope = json.loads(out) if out else None
    except json.JSONDecodeError:
        envelope = None
    if isinstance(envelope, dict) and envelope.get("ok") is True:
        return str(envelope.get("result") or f"(工具 '{tool_name}' 无返回)")
    if isinstance(envelope, dict):
        detail = str(envelope.get("error") or "工具执行失败")
    else:
        detail = err or out or f"子进程退出码 {returncode}"
    return f"[沙箱] 工具 '{tool_name}' 执行失败: {detail[:500]}"


class Sandbox:
    """可切换的进程/容器工具执行后端。"""

    def __init__(
        self,
        timeout: int = 30,
        strategy: str | None = None,
        prewarm: bool = True,
        *,
        backend: str | None = None,
        required: bool | None = None,
        enabled: bool | None = None,
    ):
        strategy = strategy or os.environ.get("REACT_AGENT_SANDBOX_STRATEGY", "auto")
        if enabled is not None:
            strategy = "auto" if enabled else "off"
        backend = backend or os.environ.get("REACT_AGENT_SANDBOX_BACKEND", "process")
        required = _env_bool("REACT_AGENT_SANDBOX_REQUIRED") if required is None else required

        if strategy not in VALID_STRATEGIES:
            raise ValueError(f"未知沙箱策略: {strategy}，可选: {VALID_STRATEGIES}")
        if backend not in VALID_BACKENDS:
            raise ValueError(f"未知沙箱后端: {backend}，可选: {VALID_BACKENDS}")
        if required and (backend != "container" or strategy != "on"):
            raise ValueError("required 模式必须使用 strategy=on 和 backend=container")

        if _in_sandbox_child():
            strategy = "off"
            backend = "process"
            required = False
            prewarm = False
        if os.environ.get("REACT_AGENT_SANDBOX_PREWARM", "1") == "0":
            prewarm = False

        self.timeout = max(1, min(int(timeout), 300))
        self.strategy = strategy
        self.backend = backend
        self.required = bool(required)
        self.runtime = os.environ.get("REACT_AGENT_SANDBOX_RUNTIME", "docker").strip()
        if Path(self.runtime).name.lower() not in {
            "docker",
            "docker.exe",
            "podman",
            "podman.exe",
        }:
            raise ValueError("REACT_AGENT_SANDBOX_RUNTIME 仅允许 docker 或 podman")
        self.image = os.environ.get(
            "REACT_AGENT_SANDBOX_IMAGE", "react-agent-sandbox:0.7.0"
        ).strip()
        if not self.image or any(ch.isspace() for ch in self.image):
            raise ValueError("REACT_AGENT_SANDBOX_IMAGE 不合法")
        self.memory = _validated_value(
            "REACT_AGENT_SANDBOX_MEMORY", "256m", _MEMORY_RE
        )
        self.cpus = _validated_value("REACT_AGENT_SANDBOX_CPUS", "0.5", _CPU_RE)
        self.pids_limit = _bounded_int("REACT_AGENT_SANDBOX_PIDS", 64, 16, 1024)
        self.tmpfs_size = _validated_value(
            "REACT_AGENT_SANDBOX_TMPFS", "64m", _MEMORY_RE
        )
        self.max_output = _bounded_int(
            "REACT_AGENT_SANDBOX_MAX_OUTPUT", 65536, 1024, 1048576
        )
        self.max_input = _bounded_int(
            "REACT_AGENT_SANDBOX_MAX_INPUT", 1048576, 1024, 10485760
        )
        self.egress_network = os.environ.get(
            "REACT_AGENT_SANDBOX_EGRESS_NETWORK", ""
        ).strip()
        if self.egress_network and not _NETWORK_NAME_RE.fullmatch(
            self.egress_network
        ):
            raise ValueError("REACT_AGENT_SANDBOX_EGRESS_NETWORK 不合法")
        self._prewarmed = False
        self._runtime_error: str | None = None
        self._runtime_checked = False
        _ensure_runner()
        if self.required:
            ready, error = self.verify_runtime()
            if not ready:
                raise RuntimeError(
                    f"SANDBOX_REQUIRED_UNAVAILABLE: required 沙箱后端未就绪，服务拒绝启动: {error}"
                )
        if prewarm and strategy != "off" and backend == "process":
            self._prewarm_process()

    @property
    def enabled(self) -> bool:
        """返回策略是否要求至少一类工具进入隔离后端。"""
        return self.strategy != "off"

    @enabled.setter
    def enabled(self, value: bool) -> None:
        """切换普通模式策略；required 模式禁止降级关闭。"""
        if not value and self.required:
            raise ValueError("required 模式禁止关闭沙箱")
        self.strategy = "auto" if value else "off"

    @property
    def secure(self) -> bool:
        """返回配置是否要求全部非控制面工具使用容器后端。"""
        return self.backend == "container" and self.strategy == "on"

    @property
    def warm_status(self) -> str:
        """返回进程后端的预热状态，容器可用性不由此表示。"""
        return "已预热" if self._prewarmed else "未预热"

    def status(self) -> dict[str, Any]:
        """返回配置和最近一次运行时探测结果，不主动触发探测。"""
        return {
            "strategy": self.strategy,
            "backend": self.backend,
            "required": self.required,
            "secure_configured": self.secure,
            "runtime_checked": self._runtime_checked,
            "runtime_ready": (
                None
                if not self._runtime_checked
                else self._runtime_error is None
            ),
            "runtime_error": self._runtime_error,
        }

    def should_sandbox(self, tool_name: str) -> bool:
        """按当前策略和工具风险分类判断是否进入隔离后端。"""
        return should_sandbox_by_risk(tool_name, self.strategy)

    def external_tool_block_reason(self, tool_name: str) -> str | None:
        """严格容器模式禁止 MCP/HTTP 工具绕过隔离后端。"""
        if not self.secure and not self.required:
            return None
        return json.dumps(
            {
                "error": "blocked by sandbox boundary",
                "tool": tool_name,
                "reason": "external tool requires an isolated MCP broker",
            },
            ensure_ascii=False,
        )

    def verify_runtime(self) -> tuple[bool, str | None]:
        """验证容器命令和固定镜像是否可用，并缓存探测结果。

        进程后端不提供系统权限隔离，因此只返回“无需容器探测”；调用方
        必须结合 :attr:`secure` 判断当前配置是否构成安全边界。
        """
        if self.backend != "container":
            return True, None
        if self._runtime_checked:
            return self._runtime_error is None, self._runtime_error
        executable = shutil.which(self.runtime)
        if not executable:
            self._runtime_error = f"找不到容器运行时: {self.runtime}"
            self._runtime_checked = True
            return False, self._runtime_error
        try:
            result = subprocess.run(
                [executable, "image", "inspect", self.image],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=10,
            )
            if result.returncode != 0:
                detail = (result.stderr or result.stdout or "镜像不存在").strip()
                self._runtime_error = (
                    f"容器镜像不可用 {self.image}: {detail[:300]}"
                )
        except (OSError, subprocess.SubprocessError) as exc:
            self._runtime_error = f"容器运行时检查失败: {exc}"
        self._runtime_checked = True
        return self._runtime_error is None, self._runtime_error

    def _prewarm_process(self) -> None:
        try:
            payload = json.dumps(
                {"function": {"name": "get_time", "arguments": "{}"}},
                ensure_ascii=False,
            )
            subprocess.run(
                [sys.executable, str(_RUNNER_PATH)],
                input=payload,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=10,
                cwd=str(_RUNNER_PATH.parent),
                env=_runner_env("get_time", self.max_output, self.max_input),
            )
            self._prewarmed = True
        except (OSError, subprocess.SubprocessError):
            self._prewarmed = False

    def _run_process(self, tool_name: str, payload: str) -> str:
        result = subprocess.run(
            [sys.executable, str(_RUNNER_PATH)],
            input=payload,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=self.timeout,
            cwd=str(_RUNNER_PATH.parent),
            env=_runner_env(tool_name, self.max_output, self.max_input),
        )
        return _decode_runner_result(
            tool_name=tool_name,
            returncode=result.returncode,
            stdout=result.stdout,
            stderr=result.stderr,
        )

    def _container_network(self, tool_name: str) -> str:
        if tool_name in NETWORK_TOOLS and self.egress_network:
            return self.egress_network
        return "none"

    def _container_userns(self) -> str:
        """Use a rootless-compatible private namespace for Podman.

        Podman's rootless ``private`` mode requires explicit UID/GID maps on
        this host, while ``auto`` allocates an isolated map automatically.
        Docker keeps the original private mode.
        """
        return "auto" if Path(self.runtime).name.lower().startswith("podman") else "private"

    def _container_command(
        self, executable: str, name: str, tool_name: str
    ) -> list[str]:
        """Construct the least-privileged container command for one tool call."""
        return [
            executable,
            "run",
            "--rm",
            "--interactive",
            "--init",
            "--name",
            name,
            "--pull",
            "never",
            "--network",
            self._container_network(tool_name),
            "--read-only",
            "--userns",
            self._container_userns(),
            "--ipc",
            "private",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges",
            "--pids-limit",
            str(self.pids_limit),
            "--memory",
            self.memory,
            "--memory-swap",
            self.memory,
            "--cpus",
            self.cpus,
            "--ulimit",
            f"nofile={self.pids_limit}:{self.pids_limit}",
            "--ulimit",
            "core=0:0",
            "--user",
            "65532:65532",
            "--tmpfs",
            f"/tmp:rw,noexec,nosuid,nodev,size={self.tmpfs_size}",
            "--workdir",
            "/tmp",
            "--env",
            "PYTHONIOENCODING=utf-8",
            "--env",
            "PYTHONDONTWRITEBYTECODE=1",
            "--env",
            f"{_SANDBOX_CHILD_ENV}=1",
            "--env",
            "REACT_AGENT_DISABLE_MCP=1",
            "--env",
            "REACT_AGENT_SKIP_RAG=1",
            "--env",
            f"REACT_AGENT_SANDBOX_ALLOWED_TOOLS={tool_name}",
            "--env",
            f"REACT_AGENT_SANDBOX_MAX_OUTPUT={self.max_output}",
            "--env",
            f"REACT_AGENT_SANDBOX_MAX_INPUT={self.max_input}",
        ] + [
            item
            for key in sorted(_CONTAINER_ENV_ALLOWLIST)
            if key in os.environ
            for item in ("--env", key)
        ] + [self.image]

    @staticmethod
    def _remove_container(executable: str, name: str) -> None:
        try:
            subprocess.run(
                [executable, "rm", "--force", name],
                capture_output=True,
                timeout=10,
            )
        except (OSError, subprocess.SubprocessError):
            pass

    def _run_container(self, tool_name: str, payload: str) -> str:
        """Run one call in a disposable container and clean it up on exit."""
        ok, error = self.verify_runtime()
        if not ok:
            return f"[沙箱] 安全后端不可用，已拒绝执行: {error}"
        executable = shutil.which(self.runtime)
        if not executable:
            return f"[沙箱] 安全后端不可用，已拒绝执行: {self.runtime}"
        name = f"react-agent-sbx-{uuid.uuid4().hex[:12]}"
        command = self._container_command(executable, name, tool_name)
        try:
            result = subprocess.run(
                command,
                input=payload,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=self.timeout,
            )
            return _decode_runner_result(
                tool_name=tool_name,
                returncode=result.returncode,
                stdout=result.stdout,
                stderr=result.stderr,
            )
        except subprocess.TimeoutExpired:
            self._remove_container(executable, name)
            return f"[沙箱] 工具 '{tool_name}' 执行超时（{self.timeout}秒）"
        except OSError as exc:
            return f"[沙箱] 安全后端异常，已拒绝执行: {exc}"
        finally:
            self._remove_container(executable, name)

    def run(self, tool_call: dict[str, Any]) -> str:
        """Apply risk policy, input limits and backend-specific isolation."""
        function = tool_call.get("function") or {}
        tool_name = str(function.get("name") or "")
        if not tool_name:
            return "[沙箱] 工具调用缺少 function.name"
        if not self.should_sandbox(tool_name):
            if self.required and classify_risk(tool_name) != RISK_CONTROL:
                return "[沙箱] required 模式拒绝未隔离执行"
            return "__SANDBOX_DISABLED__"
        payload = json.dumps(tool_call, ensure_ascii=False)
        if len(payload.encode("utf-8")) > self.max_input:
            return (
                f"[沙箱] 工具 '{tool_name}' 参数超过 "
                f"{self.max_input} 字节上限，已拒绝执行"
            )
        try:
            if self.backend == "container":
                return self._run_container(tool_name, payload)
            if self.required:
                return "[沙箱] required 模式拒绝 process 后端"
            return self._run_process(tool_name, payload)
        except subprocess.TimeoutExpired:
            return f"[沙箱] 工具 '{tool_name}' 执行超时（{self.timeout}秒）"
        except OSError as exc:
            return f"[沙箱] 工具 '{tool_name}' 异常: {exc}"


SANDBOX = Sandbox()

SANDBOX_TOOL_DEFINITION = {
    "type": "function",
    "function": {
        "name": "toggle_sandbox",
        "description": "切换工具隔离策略；生产 required 模式禁止关闭",
        "parameters": {
            "type": "object",
            "properties": {
                "strategy": {
                    "type": "string",
                    "enum": ["off", "auto", "on"],
                    "description": "off=直跑，auto=按风险，on=全部隔离",
                }
            },
            "required": ["strategy"],
        },
    },
}


def tool_toggle_sandbox(strategy: str = "auto") -> str:
    if strategy not in VALID_STRATEGIES:
        return f"未知策略: {strategy}，可选: {', '.join(VALID_STRATEGIES)}"
    if SANDBOX.required and strategy != "on":
        return "拒绝切换：required 模式强制 strategy=on"
    old = SANDBOX.strategy
    SANDBOX.strategy = strategy
    SANDBOX.timeout = 30
    return (
        f"沙箱策略: {old} → {strategy}; backend={SANDBOX.backend}; "
        f"secure_configured={str(SANDBOX.secure).lower()}"
    )
