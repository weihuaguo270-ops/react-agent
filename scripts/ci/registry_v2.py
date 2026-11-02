"""Validate and select rules from the CI Registry v2 contract."""

from __future__ import annotations

import argparse
import fnmatch
import json
import re
import subprocess
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REGISTRY = ROOT / "docs/specs/ci/registry-v2.json"


def load_registry(path: Path = REGISTRY) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def repo_files() -> set[str]:
    result = subprocess.run(
        ["git", "ls-files"], cwd=ROOT, check=True, capture_output=True, text=True
    )
    tracked = {line.replace("\\", "/") for line in result.stdout.splitlines() if line}
    for path in ROOT.rglob("*"):
        if path.is_file() and ".git" not in path.parts and ".venv" not in path.parts:
            tracked.add(path.relative_to(ROOT).as_posix())
    return tracked


def path_matches(path: str, pattern: str) -> bool:
    path = path.replace("\\", "/")
    pattern = pattern.replace("\\", "/")
    return fnmatch.fnmatchcase(path, pattern) or Path(path).match(pattern)


def validate_registry(registry: dict | None = None) -> list[str]:
    registry = registry or load_registry()
    errors: list[str] = []
    if registry.get("schema_version") != "spec-registry/v2":
        errors.append("schema_version must be spec-registry/v2")
    files = repo_files()
    for direction_id, direction in registry.get("directions", {}).items():
        ids: set[str] = set()
        rule_ids = {rule.get("id") for rule in direction.get("rules", [])}
        for field in ("goal", "progress_source", "source_spec"):
            path = direction.get(field)
            if not path or path not in files:
                errors.append(f"{direction_id}.{field} does not exist: {path}")
        for rule in direction.get("rules", []):
            rule_id = rule.get("id")
            if not rule_id or rule_id in ids:
                errors.append(f"duplicate or missing rule id: {rule_id}")
            ids.add(rule_id)
            if not rule.get("path_globs"):
                errors.append(f"{rule_id}: path_globs is empty")
            for pattern in rule.get("path_globs", []):
                normalized = pattern.replace("\\", "/")
                if normalized.startswith("/") or ".." in Path(normalized).parts:
                    errors.append(f"{rule_id}: unsafe path glob: {pattern}")
                elif not any(path_matches(path, normalized) for path in files):
                    errors.append(f"{rule_id}: path glob matches no tracked file: {pattern}")
            if rule.get("execution") == "automated" and not rule.get("gate"):
                errors.append(f"{rule_id}: automated rule has no gate")
            gate = rule.get("gate", {})
            for key in ("argv", "working_directory", "timeout_minutes", "network", "allowed_domains", "secret_refs", "write_paths"):
                if key not in gate:
                    errors.append(f"{rule_id}: gate missing {key}")
            workdir = gate.get("working_directory")
            if workdir and not (ROOT / workdir).is_dir():
                errors.append(f"{rule_id}: working_directory does not exist: {workdir}")
            argv = gate.get("argv", [])
            if any(any(token in arg for token in (";", "&&", "||", "|", ">", "<", "..")) for arg in argv):
                errors.append(f"{rule_id}: unsafe gate argv")
            if gate.get("network") == "none" and gate.get("allowed_domains"):
                errors.append(f"{rule_id}: network=none cannot allow domains")
            if gate.get("network") == "allowlist" and not gate.get("allowed_domains"):
                errors.append(f"{rule_id}: network=allowlist needs allowed_domains")
        for item in direction.get("unmapped", []):
            if item.get("safety_gate_rule_id") not in rule_ids:
                errors.append(f"{item.get('id')}: safety gate rule is missing")
            try:
                if date.fromisoformat(item.get("expires_at", "")) < date.today():
                    errors.append(f"{item.get('id')}: unmapped exception expired")
            except ValueError:
                errors.append(f"{item.get('id')}: invalid expires_at")
        for item in direction.get("exceptions", []):
            if item.get("rule_id") not in rule_ids:
                errors.append(f"{item.get('id')}: exception references missing rule")
            try:
                if date.fromisoformat(item.get("expires_at", "")) < date.today():
                    errors.append(f"{item.get('id')}: exception expired")
            except ValueError:
                errors.append(f"{item.get('id')}: invalid expires_at")
            if not item.get("approved_by_role") or not item.get("approved_at") or not item.get("evidence"):
                errors.append(f"{item.get('id')}: approval provenance is incomplete")
        for path in (direction.get("goal"), direction.get("progress_source"), direction.get("source_spec")):
            if path and not re.fullmatch(r"[A-Za-z0-9._*?,{}!/-]+", path):
                errors.append(f"invalid repository path: {path}")
    return errors


def select(changed_files: list[str], registry: dict | None = None) -> dict:
    registry = registry or load_registry()
    direction = registry["directions"]["ci"]
    selected: dict[str, list[str]] = {}
    unmapped: list[str] = []
    for path in changed_files:
        matched = []
        for rule in direction["rules"]:
            if any(path_matches(path, glob) for glob in rule["path_globs"]):
                if not any(path_matches(path, glob) for glob in rule.get("exclude_globs", [])):
                    matched.append(rule["id"])
        if matched:
            for rule_id in matched:
                selected.setdefault(rule_id, []).append(path)
        else:
            unmapped.append(path)
    status = "blocked" if unmapped else "pass"
    safety_rule = direction["unmapped"][0]["safety_gate_rule_id"] if unmapped else None
    if safety_rule:
        selected.setdefault(safety_rule, [])
    return {
        "schema_version": "ci-selector/v1",
        "status": status,
        "changed_files": changed_files,
        "selected_rules": selected,
        "unmapped_paths": unmapped,
        "safety_gate_rule_id": safety_rule,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("validate")
    select_parser = sub.add_parser("select")
    select_parser.add_argument("paths", nargs="*")
    args = parser.parse_args()
    if args.command == "validate":
        errors = validate_registry()
        print(json.dumps({"status": "pass" if not errors else "fail", "errors": errors}, ensure_ascii=False, indent=2))
        return 0 if not errors else 1
    print(json.dumps(select(args.paths), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
