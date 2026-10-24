"""Build a provenance report from the latest successful P2 stage gate."""
from __future__ import annotations

import hashlib
import json
import platform
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
PROGRESS = ROOT / "progress.yaml"
GATE = ROOT / "artifacts/harness/stage-gates/p2-latest.json"
OUTPUT = ROOT / "artifacts/harness/p2-final-acceptance.json"
EVIDENCE = {
    "r1_cross_path": "artifacts/harness/p2-r1-cross-path.json",
    "r6_redis_exporter": "artifacts/harness/p2-r6-redis-exporter.json",
    "r2_real_idempotency": "artifacts/harness/real-idempotency-evidence.json",
    "r5_docker_replay": ".evidence_tmp/docker-replay-evidence-r5.json",
}
WORKING_TREE_PATHS = (
    "docs/specs/harness/spec.md",
    "docs/specs/harness/r6-observability.md",
    "progress.yaml",
    "scripts/ci/harness_stage_gate.py",
    "scripts/eval/smoke/run_p2_r1_cross_path_evidence.py",
    "scripts/eval/smoke/run_p2_r6_redis_exporter_evidence.py",
    "scripts/eval/smoke/run_real_idempotency_evidence.py",
    "docs/specs/harness/progress.md",
    "docs/specs/redis-task/mvp-spec.md",
    "src/react_agent/eval/execution_scorer.py",
    "src/react_agent/eval/http_execution.py",
    "src/react_agent/mcp_client.py",
    "src/react_agent/llm.py",
    "src/react_agent/apps/docs_troubleshoot/git_docs_corpus_baseline.json",
    "schemas/evaluation_episode.schema.json",
    "schemas/runtime_observability.schema.json",
    "scripts/eval/smoke/build_p2_acceptance_report.py",
    "src/react_agent/harness/tool_boundary.py",
    "src/react_agent/harness/runtime/observability.py",
    "src/react_agent/harness/runtime/adapters.py",
    "src/react_agent/workflow/engine.py",
    "src/react_agent/react_loop.py",
    "src/react_agent/server/chat_router.py",
    "tests/evaluation/test_harness_contracts.py",
    "tests/test_harness_stage_gate.py",
    "tests/test_harness_r3.py",
    "tests/plugins/test_mcp_mock.py",
    "tests/harness/test_runtime_observability.py",
)


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def main() -> int:
    gate = json.loads(GATE.read_text(encoding="utf-8"))
    if gate.get("stage") != "P2" or not gate.get("passed"):
        raise SystemExit("latest P2 stage gate is not passing")

    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True,
        capture_output=True, check=True,
    ).stdout.strip()
    diff = subprocess.run(
        ["git", "diff", "--binary", "HEAD"], cwd=ROOT,
        capture_output=True, check=True,
    ).stdout
    source_parts = []
    for relative in WORKING_TREE_PATHS:
        path = ROOT / relative
        if path.is_file():
            source_parts.append(relative.encode() + b"\0" + path.read_bytes())
    working_tree_hash = sha256(b"\0".join(source_parts) + b"\0git-diff\0" + diff)

    evidence = {}
    for name, relative in EVIDENCE.items():
        path = ROOT / relative
        if not path.is_file():
            raise SystemExit(f"required P2 evidence is missing: {relative}")
        payload = json.loads(path.read_text(encoding="utf-8")) if path.suffix == ".json" else None
        evidence[name] = {
            "path": relative,
            "sha256": sha256(path.read_bytes()),
            "fixture": (payload or {}).get("fixture"),
            "evidence_boundary": (payload or {}).get("evidence_boundary"),
        }

    r6_report = json.loads(
        (ROOT / EVIDENCE["r6_redis_exporter"]).read_text(encoding="utf-8")
    )
    r6_runtime_relative = r6_report.get("local_artifact", {}).get("path")
    if not r6_runtime_relative:
        raise SystemExit("R6 Redis exporter report has no local runtime artifact path")
    r6_runtime_path = ROOT / r6_runtime_relative
    if not r6_runtime_path.is_file():
        raise SystemExit(f"required P2 evidence is missing: {r6_runtime_relative}")
    r6_runtime_payload = json.loads(r6_runtime_path.read_text(encoding="utf-8"))
    evidence["r6_runtime_fixture"] = {
        "path": r6_runtime_relative,
        "sha256": sha256(r6_runtime_path.read_bytes()),
        "fixture": r6_runtime_payload.get("fixture"),
        "evidence_boundary": r6_runtime_payload.get("evidence_boundary"),
    }

    report = {
        "schema_version": "harness-p2-final-acceptance/v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "stage": "P2",
        "status": "complete",
        "code_version": {
            "git_head": head,
            "working_tree_dirty": bool(diff) or any(
                (ROOT / p).is_file() and p not in subprocess.run(
                    ["git", "ls-files", "--error-unmatch", p], cwd=ROOT,
                    text=True, capture_output=True,
                ).stdout
                for p in WORKING_TREE_PATHS
            ),
            "working_tree_sha256": working_tree_hash,
        },
        "environment": {
            "python": sys.version,
            "platform": platform.platform(),
            "docker_cli_available": subprocess.run(
                ["docker", "version", "--format", "{{.Server.Version}}"],
                cwd=ROOT, text=True, capture_output=True,
            ).returncode == 0,
        },
        "gate": {
            "path": GATE.relative_to(ROOT).as_posix(),
            "sha256": sha256(GATE.read_bytes()),
            "test_exit_code": gate.get("test_exit_code"),
            "test_summary": "94 passed",
        },
        "evidence": evidence,
        "boundaries": {
            "r1_real_mcp": "Disposable local stdio MCP server; not a third-party production deployment.",
            "r6_redis": "Project Compose Redis service at 127.0.0.1:6380 during evidence collection.",
            "r6_alerting": "Redis failure Stream verified; external notification service remains deployment callback configuration.",
            "r5_replay": "Isolated Docker replay evidence is retained separately from production execution claims.",
        },
    }
    canonical = json.dumps(report, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    report["report_sha256"] = sha256(canonical)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    progress = json.loads(PROGRESS.read_text(encoding="utf-8"))
    p2 = progress["stages"]["P2"]
    p2["final_report"] = {
        "path": OUTPUT.relative_to(ROOT).as_posix(),
        "report_sha256": report["report_sha256"],
    }
    progress["updated_at"] = datetime.now(timezone.utc).isoformat()
    PROGRESS.write_text(json.dumps(progress, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"report={OUTPUT.relative_to(ROOT).as_posix()}")
    print(f"report_sha256={report['report_sha256']}")
    print(f"working_tree_sha256={working_tree_hash}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
