"""Create a read-only security snapshot for CI workflow migration planning.

This audit records observable workflow, secret, permission, action, and Docker
image facts. It is evidence for the CI redesign; it does not claim that the
Phase 1 R9 acceptance work is complete.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
EVIDENCE = ROOT / "docs/specs/ci/evidence"
SHA = re.compile(r"^[0-9a-f]{40}$", re.IGNORECASE)


def tracked_files() -> list[Path]:
    result = subprocess.run(
        ["git", "ls-files", "-z"], cwd=ROOT, check=True, capture_output=True
    )
    return [ROOT / item.decode("utf-8") for item in result.stdout.split(b"\0") if item]


def git_head() -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def workflow_snapshot(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    uses = []
    for match in re.finditer(r"^\s*-?\s*uses:\s*([^\s#]+)", text, re.MULTILINE):
        ref = match.group(1)
        action, _, version = ref.rpartition("@")
        uses.append(
            {
                "reference": ref,
                "action": action or ref,
                "version": version or None,
                "pinned_commit": bool(SHA.fullmatch(version)),
            }
        )
    secrets = sorted(set(re.findall(r"secrets\.([A-Za-z_][A-Za-z0-9_]*)", text)))
    write_permissions = sorted(
        set(re.findall(r"^\s{2,}(actions|contents|pull-requests):\s*write\s*$", text, re.MULTILINE))
    )
    return {
        "path": path.relative_to(ROOT).as_posix(),
        "events": sorted(
            set(
                re.findall(
                    r"^\s{2}(push|pull_request|pull_request_target|workflow_dispatch|schedule):\s*$",
                    text,
                    re.MULTILINE,
                )
            )
        ),
        "uses": uses,
        "secret_refs": secrets,
        "write_permissions": write_permissions,
        "explicit_permissions": bool(re.search(r"^permissions:\s*$", text, re.MULTILINE)),
        "contains_pull_request_target": "pull_request_target:" in text,
        "checkout_refs_pr_head": "github.event.pull_request.head.sha" in text,
        "write_operations": sorted(
            phrase
            for phrase, needle in (
                ("git push", "git push"),
                ("gh pr create", "gh pr create"),
                ("gh pr merge", "gh pr merge"),
                ("gh api write", "gh api -X"),
            )
            if needle in text
        ),
    }


def docker_snapshot() -> list[dict]:
    images = []
    for path in tracked_files():
        if not path.name.startswith("Dockerfile"):
            continue
        for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            match = re.match(r"\s*FROM\s+([^\s]+)", line)
            if not match:
                continue
            image = match.group(1)
            images.append(
                {
                    "path": path.relative_to(ROOT).as_posix(),
                    "line": line_no,
                    "image": image,
                    "pinned_digest": "@sha256:" in image,
                }
            )
    return images


def audit() -> dict:
    workflows = [
        workflow_snapshot(path)
        for path in sorted(tracked_files())
        if path.parent == ROOT / ".github/workflows" and path.suffix in {".yml", ".yaml"}
    ]
    images = docker_snapshot()
    findings = []
    for workflow in workflows:
        unpinned = [item["reference"] for item in workflow["uses"] if not item["pinned_commit"]]
        if unpinned:
            findings.append(
                {
                    "id": "external-actions-not-commit-pinned",
                    "severity": "high",
                    "path": workflow["path"],
                    "details": unpinned,
                    "planned_phase": "Phase 1",
                }
            )
        if workflow["contains_pull_request_target"]:
            findings.append(
                {
                    "id": "pull-request-target-present",
                    "severity": "high",
                    "path": workflow["path"],
                    "details": "Review whether untrusted pull request content could execute with elevated context.",
                    "planned_phase": "Phase 1",
                }
            )
        if not workflow["explicit_permissions"]:
            findings.append(
                {
                    "id": "workflow-permissions-not-explicit",
                    "severity": "medium",
                    "path": workflow["path"],
                    "details": "Effective GITHUB_TOKEN permissions depend on repository defaults.",
                    "planned_phase": "Phase 1",
                }
            )
        if workflow["write_permissions"] and workflow["write_operations"]:
            findings.append(
                {
                    "id": "write-capable-workflow",
                    "severity": "high",
                    "path": workflow["path"],
                    "details": {
                        "permissions": workflow["write_permissions"],
                        "operations": workflow["write_operations"],
                    },
                    "planned_phase": "Phase 1",
                }
            )
    for image in images:
        if not image["pinned_digest"]:
            findings.append(
                {
                    "id": "docker-base-image-not-digest-pinned",
                    "severity": "medium",
                    "path": image["path"],
                    "details": f"{image['image']} (line {image['line']})",
                    "planned_phase": "Phase 1",
                }
            )
    return {
        "schema_version": "ci-r9-security-snapshot/v1",
        "status": "attention_required" if findings else "clean",
        "collected_at": datetime.now(timezone.utc).isoformat(),
        "head_sha": git_head(),
        "scope": {
            "workflow_files": [item["path"] for item in workflows],
            "dockerfiles": sorted({item["path"] for item in images}),
            "read_only": True,
            "acceptance_status": "Phase 1 R9 acceptance not claimed",
        },
        "workflows": workflows,
        "docker_base_images": images,
        "findings": findings,
    }


def render(report: dict) -> str:
    lines = [
        "# CI R9 安全快照",
        "",
        f"**状态：** `{report['status']}`（这是 Phase 0 事实快照，不是 Phase 1 R9 验收通过）",
        f"**采集提交：** `{report['head_sha']}`",
        f"**采集时间：** `{report['collected_at']}`",
        "",
        "## 范围",
        "",
        "- workflow 事件、权限、Secret 引用、外部 Action 引用和写操作。",
        "- Dockerfile 的基础镜像引用。",
        "- 该文件只记录静态可观察事实；fork Secret 隔离和运行时权限仍需 Phase 1 验收证据。",
        "",
        "## 发现",
        "",
    ]
    if report["findings"]:
        for finding in report["findings"]:
            lines.append(
                f"- `{finding['id']}` ({finding['severity']})：`{finding['path']}`；"
                f"计划阶段：{finding['planned_phase']}；详情：`{json.dumps(finding['details'], ensure_ascii=False)}`"
            )
    else:
        lines.append("- 未发现静态问题。")
    lines.extend(["", "机器可读明细见同目录的 `phase0-r9-security-snapshot.json`。", ""])
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, default=EVIDENCE)
    args = parser.parse_args()
    report = audit()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "phase0-r9-security-snapshot.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (args.output_dir / "phase0-r9-security-snapshot.md").write_text(render(report), encoding="utf-8")
    print(json.dumps({"status": report["status"], "findings": len(report["findings"]), "head_sha": report["head_sha"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
