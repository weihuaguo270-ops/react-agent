"""Run non-destructive checks against the configured container sandbox."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from react_agent.harness.sandbox import Sandbox  # noqa: E402


def _call(name: str, arguments: dict) -> dict:
    return {"function": {"name": name, "arguments": json.dumps(arguments)}}


def _probe_code() -> str:
    """Return a probe that reads policy metadata and writes disposable /tmp data."""
    return r'''
import json, os, pathlib, resource, socket, subprocess, tempfile, time

def attempt_write(path):
    try:
        pathlib.Path(path).write_text("probe", encoding="utf-8")
    except Exception as exc:
        return type(exc).__name__
    finally:
        try:
            pathlib.Path(path).unlink()
        except Exception:
            pass
    return "writable"

def attempt_exec():
    path = pathlib.Path(tempfile.gettempdir()) / "sandbox-probe.sh"
    try:
        path.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        path.chmod(0o700)
        subprocess.run([str(path)], check=True, capture_output=True)
    except Exception as exc:
        return type(exc).__name__
    finally:
        try:
            path.unlink()
        except Exception:
            pass
    return "executable"

def read_file(path):
    try:
        return pathlib.Path(path).read_text().strip()
    except Exception as exc:
        return type(exc).__name__

def namespace_inode(name):
    try:
        return os.stat("/proc/self/ns/" + name).st_ino
    except Exception:
        return None

def init_reaps_orphan():
    read_fd, write_fd = os.pipe()
    child = os.fork()
    if child == 0:
        os.close(read_fd)
        orphan = os.fork()
        if orphan == 0:
            time.sleep(0.25)
            os._exit(0)
        os.write(write_fd, str(orphan).encode("ascii"))
        os.close(write_fd)
        os._exit(0)
    os.close(write_fd)
    raw = os.read(read_fd, 64)
    os.close(read_fd)
    os.waitpid(child, 0)
    try:
        orphan = int(raw.decode("ascii"))
    except (TypeError, ValueError):
        return False
    time.sleep(0.7)
    try:
        next(
            line
            for line in pathlib.Path(f"/proc/{orphan}/status").read_text().splitlines()
            if line.startswith("State:")
        )
    except (FileNotFoundError, StopIteration):
        return True
    return False

status = {}
try:
    for line in pathlib.Path("/proc/self/status").read_text().splitlines():
        key, _, value = line.partition(":")
        if key in {"Uid", "Gid", "CapEff", "CapBnd", "NoNewPrivs", "Seccomp"}:
            status[key] = value.strip()
except Exception as exc:
    status["proc_status_error"] = type(exc).__name__

network = "blocked"
try:
    with socket.create_connection(("1.1.1.1", 443), timeout=1):
        network = "reachable"
except Exception as exc:
    network = type(exc).__name__

nofile = resource.getrlimit(resource.RLIMIT_NOFILE)
print(json.dumps({
    "uid": os.getuid(),
    "gid": os.getgid(),
    "status": status,
    "uid_map": read_file("/proc/self/uid_map"),
    "gid_map": read_file("/proc/self/gid_map"),
    "namespaces": {name: namespace_inode(name) for name in ("user", "ipc", "net", "pid")},
    "cgroup": {
        key: read_file(path)
        for key, path in {
            "memory_max": "/sys/fs/cgroup/memory.max",
            "memory_swap_max": "/sys/fs/cgroup/memory.swap.max",
            "pids_max": "/sys/fs/cgroup/pids.max",
            "cpu_max": "/sys/fs/cgroup/cpu.max",
        }.items()
    },
    "nofile": list(nofile),
    "etc_write": attempt_write("/etc/react-agent-sandbox-probe"),
    "tmp_write": attempt_write(pathlib.Path(tempfile.gettempdir()) / "sandbox-probe.txt"),
    "tmp_exec": attempt_exec(),
    "init_reaps_orphan": init_reaps_orphan(),
    "network": network,
    "api_key_present": bool(os.environ.get("DEEPSEEK_API_KEY")),
}, sort_keys=True))
'''


def _extract_probe(raw: str) -> dict:
    """Extract the JSON line emitted before the tool's timing footer."""
    for line in raw.splitlines():
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict) and "uid" in value:
            return value
    return {}


def _runtime_path(sandbox: Sandbox) -> str | None:
    return shutil.which(sandbox.runtime)


def _machine_status(sandbox: Sandbox) -> dict:
    if not Path(sandbox.runtime).name.lower().startswith("podman"):
        return {"applicable": False}
    executable = _runtime_path(sandbox)
    if not executable:
        return {"applicable": True, "error": f"runtime not found: {sandbox.runtime}"}
    try:
        result = subprocess.run(
            [executable, "machine", "inspect"], capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=20,
        )
        machines = json.loads(result.stdout) if result.returncode == 0 else []
        machine = machines[0] if machines else {}
        return {
            "applicable": True,
            "runtime_returncode": result.returncode,
            "name": machine.get("Name"),
            "state": machine.get("State"),
            "running": machine.get("State") == "running",
            "raw_error": (result.stderr or "").strip() or None,
        }
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError) as exc:
        return {"applicable": True, "error": f"{type(exc).__name__}: {exc}"}


def _image_status(sandbox: Sandbox) -> dict:
    executable = _runtime_path(sandbox)
    if not executable:
        return {"available": False, "error": "runtime not found"}
    try:
        result = subprocess.run(
            [executable, "image", "inspect", sandbox.image],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=20,
        )
        values = json.loads(result.stdout) if result.returncode == 0 else []
        image = values[0] if values else {}
        return {
            "available": result.returncode == 0 and bool(image),
            "id": image.get("Id"),
            "created": image.get("Created"),
            "error": (result.stderr or "").strip() or None,
        }
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError) as exc:
        return {"available": False, "error": f"{type(exc).__name__}: {exc}"}


def _host_namespace_control(sandbox: Sandbox) -> dict:
    """Read namespace identifiers from an explicit host-namespace container."""
    executable = _runtime_path(sandbox)
    if not executable:
        return {"error": "runtime not found"}
    code = (
        "import json, os, pathlib; "
        "print(json.dumps({'user': os.stat('/proc/self/ns/user').st_ino, "
        "'ipc': os.stat('/proc/self/ns/ipc').st_ino, "
        "'uid_map': pathlib.Path('/proc/self/uid_map').read_text().strip()}))"
    )
    try:
        result = subprocess.run(
            [
                executable, "run", "--rm", "--network", "none", "--read-only",
                "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
                "--userns", "host", "--ipc", "host", "--user", "65532:65532",
                "--entrypoint", "python", sandbox.image, "-c", code,
            ],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30,
        )
        return json.loads(result.stdout) if result.returncode == 0 else {
            "error": (result.stderr or result.stdout).strip()
        }
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError) as exc:
        return {"error": f"{type(exc).__name__}: {exc}"}


def _leftover_containers(sandbox: Sandbox) -> list[str]:
    executable = _runtime_path(sandbox)
    if not executable:
        return ["runtime-not-found"]
    try:
        result = subprocess.run(
            [executable, "ps", "-a", "--filter", "name=react-agent-sbx-", "--format", "{{.Names}}"],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=20,
        )
        return [line.strip() for line in result.stdout.splitlines() if line.strip()]
    except (OSError, subprocess.SubprocessError):
        return ["inspection-error"]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()

    original_key = os.environ.get("DEEPSEEK_API_KEY")
    os.environ["DEEPSEEK_API_KEY"] = "sandbox-live-check-host-sentinel"
    try:
        sandbox = Sandbox(strategy="on", backend="container", required=True, prewarm=False)
        machine = _machine_status(sandbox)
        image = _image_status(sandbox)
        host_namespaces = _host_namespace_control(sandbox)
        calculator = sandbox.run(_call("calculator", {"expression": "40+2"}))
        probe_results = [sandbox.run(_call("execute_python", {"code": _probe_code()})) for _ in range(2)]
        probes = [_extract_probe(raw) for raw in probe_results]
        first = probes[0] if probes else {}

        timeout_sandbox = Sandbox(timeout=1, strategy="on", backend="container", required=True, prewarm=False)
        started = time.monotonic()
        timeout_result = timeout_sandbox.run(_call("execute_python", {"code": "import time; time.sleep(5)"}))
        timeout_elapsed = round(time.monotonic() - started, 3)
        leftovers = _leftover_containers(timeout_sandbox)
    finally:
        if original_key is None:
            os.environ.pop("DEEPSEEK_API_KEY", None)
        else:
            os.environ["DEEPSEEK_API_KEY"] = original_key

    status = first.get("status") or {}
    cgroup = first.get("cgroup") or {}
    nofile = first.get("nofile") or []
    first_ns = first.get("namespaces") or {}
    checks = {
        "machine_running": machine.get("running", True) if machine.get("applicable") else True,
        "image_available": image.get("available") is True,
        "calculator": calculator == "42",
        "non_root_uid": str(first.get("uid")) == "65532",
        "non_root_gid": str(first.get("gid")) == "65532",
        "user_namespace_private": bool(first.get("uid_map"))
        and first_ns.get("user") != host_namespaces.get("user")
        and first.get("uid_map") != host_namespaces.get("uid_map"),
        "ipc_namespace_private": first_ns.get("ipc") is not None
        and first_ns.get("ipc") != host_namespaces.get("ipc"),
        "seccomp": status.get("Seccomp") == "2",
        "no_new_privileges": status.get("NoNewPrivs") == "1",
        "capabilities_dropped": status.get("CapEff") in {"0000000000000000", "0"} and status.get("CapBnd") in {"0000000000000000", "0"},
        "rootfs_read_only": first.get("etc_write") != "writable",
        "tmpfs_writable": first.get("tmp_write") == "writable",
        "tmpfs_noexec": first.get("tmp_exec") != "executable",
        "init_reaps_orphans": first.get("init_reaps_orphan") is True,
        "resource_memory": cgroup.get("memory_max") == "268435456",
        "resource_memory_swap": cgroup.get("memory_swap_max") == "0",
        "resource_pids": cgroup.get("pids_max") == "64",
        "resource_cpu": cgroup.get("cpu_max") == "50000 100000",
        "resource_nofile": nofile == [64, 64],
        "network_blocked": first.get("network") != "reachable",
        "host_api_key_hidden": first.get("api_key_present") is False,
        "timeout_triggered": "超时" in timeout_result or "timed out" in timeout_result,
        "timeout_cleanup": leftovers == [],
    }
    report = {
        "schema_version": "sandbox-live-check/v2",
        "backend": sandbox.status(),
        "machine": machine,
        "image": image,
        "host_namespace_control": host_namespaces,
        "calculator_result": calculator,
        "probe_results": probe_results,
        "probe_values": probes,
        "timeout_result": timeout_result,
        "timeout_elapsed_seconds": timeout_elapsed,
        "leftover_containers": leftovers,
        "checks": checks,
        "passed": all(checks.values()),
        "evidence_boundary": "Two disposable containers plus a one-second timeout check; does not replace escape testing, image scanning, or host security review.",
    }
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    print(rendered)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(rendered + "\n", encoding="utf-8")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
