"""Run a deterministic replay twice inside the hardened Docker sandbox.

The host mounts this file read-only into ``react-agent-sandbox``. The runner
does not invoke a live tool: it proves that recorded tool results produce the
same replay trajectory, stop reason, and scoring-input hash in an isolated
container.
"""
from __future__ import annotations

import hashlib
import json
import os
import socket
from pathlib import Path

from react_agent.harness.runtime.replay import DeterministicReplay, ReplayLimits


def _fixture_ref() -> tuple[dict[str, str], bytes]:
    value = b"docker-replay-fixture-v1"
    return (
        {
            "fixture_id": "docker-replay-fixture",
            "version": "v1",
            "data_sha256": hashlib.sha256(value).hexdigest(),
        },
        value,
    )


def _trajectory() -> dict:
    return {
        "session_id": "docker-replay-session",
        "query": "calculate",
        "steps": [
            {
                "step": 1,
                "action": {
                    "name": "calculator",
                    "call_id": "call-1",
                    "arguments": '{"expression":"2+2"}',
                },
                "observation": "4",
            }
        ],
        "final_answer": "4",
        "metadata": {"stop_reason": "completed"},
    }


def _container_context() -> dict:
    status: dict[str, str] = {}
    for line in Path("/proc/self/status").read_text(encoding="utf-8").splitlines():
        key, _, value = line.partition(":")
        if key in {"CapEff", "CapBnd", "NoNewPrivs", "Seccomp"}:
            status[key] = value.strip()
    try:
        with socket.create_connection(("1.1.1.1", 443), timeout=1):
            network = "reachable"
    except OSError as exc:
        network = type(exc).__name__
    return {
        "uid": os.getuid(),
        "gid": os.getgid(),
        "status": status,
        "network": network,
        "memory_max": Path("/sys/fs/cgroup/memory.max").read_text().strip(),
        "pids_max": Path("/sys/fs/cgroup/pids.max").read_text().strip(),
        "cpu_max": Path("/sys/fs/cgroup/cpu.max").read_text().strip(),
    }


def main() -> int:
    fixture, fixture_value = _fixture_ref()
    manifest = DeterministicReplay.record(
        _trajectory(),
        tool_results={"call-1": {"result": "4"}},
        model_responses=[{"content": "4"}],
        fixture=fixture,
        manifest_id="docker-replay-manifest-1",
    )
    runner = DeterministicReplay(
        fixture_loader=lambda _ref: fixture_value,
        limits=ReplayLimits(max_steps=8, max_tool_calls=8, max_output_bytes=4096),
    )
    first = runner.replay(manifest)
    second = runner.replay(manifest)
    first_steps = first.trajectory["steps"]
    second_steps = second.trajectory["steps"]
    checks = {
        "container_uid": os.getuid() == 65532,
        "container_gid": os.getgid() == 65532,
        "network_blocked": _container_context()["network"] != "reachable",
        "recorded_result_used": first_steps[0]["observation"] == "4",
        "step_sequence_equal": first_steps == second_steps,
        "stop_reason_equal": first.stop_reason == second.stop_reason == "completed",
        "scoring_input_equal": first.scoring_input_sha256 == second.scoring_input_sha256,
        "execution_replay": first.execution_replay and not first.display_only,
    }
    report = {
        "schema_version": "docker-replay-evidence/v1",
        "image_role": "react-agent-sandbox:r5-replay",
        "manifest": manifest.to_dict(),
        "first": first.to_dict(),
        "second": second.to_dict(),
        "container": _container_context(),
        "checks": checks,
        "passed": all(checks.values()),
        "evidence_boundary": (
            "Replay consumes recorded tool results only; the Docker container provides "
            "network, filesystem, capability and resource isolation."
        ),
    }
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
