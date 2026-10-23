"""Operate the repository's registry-backed Spec progress workflow."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCRIPT = Path(__file__).resolve()
ROOT = SCRIPT.parents[4]
REGISTRY_PATH = ROOT / "docs/specs/registry.yaml"


def repo_path(value: str) -> Path:
    candidate = Path(value)
    if not candidate.is_absolute():
        candidate = ROOT / candidate
    candidate = candidate.resolve()
    if not candidate.is_relative_to(ROOT.resolve()):
        raise ValueError(f"path escapes repository: {value}")
    return candidate


def relative_path(path: Path) -> str:
    return path.resolve().relative_to(ROOT.resolve()).as_posix()


def read_data(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        try:
            import yaml  # type: ignore
        except ImportError as exc:
            raise ValueError(f"{path} is not JSON-compatible YAML and PyYAML is unavailable") from exc
        value = yaml.safe_load(text)
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain an object")
    return value


def write_data(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def load_registry() -> dict[str, Any]:
    registry = read_data(REGISTRY_PATH)
    if registry.get("schema_version") != "spec-registry/v1":
        raise ValueError("registry schema_version must be spec-registry/v1")
    directions = registry.get("directions")
    if not isinstance(directions, dict):
        raise ValueError("registry directions must be an object")
    return registry


def direction_entry(registry: dict[str, Any], direction: str) -> dict[str, Any]:
    entry = registry["directions"].get(direction)
    if not isinstance(entry, dict):
        raise ValueError(f"unknown direction: {direction}")
    return entry


def load_progress(entry: dict[str, Any]) -> tuple[Path, dict[str, Any]]:
    path = repo_path(str(entry["progress_source"]))
    return path, read_data(path)


def status_snapshot(registry: dict[str, Any], direction: str) -> dict[str, Any]:
    entry = direction_entry(registry, direction)
    progress_path, progress = load_progress(entry)
    stages = progress.get("stages", {})
    if not isinstance(stages, dict):
        raise ValueError(f"{progress_path} stages must be an object")
    active = [name for name, stage in stages.items() if stage.get("status") == "in_progress"]
    pending = [
        item["id"]
        for stage in stages.values()
        if isinstance(stage, dict)
        for item in stage.get("acceptance", [])
        if isinstance(item, dict) and item.get("status") != "complete" and "id" in item
    ]
    report = None
    last_gate = progress.get("last_gate")
    if isinstance(last_gate, dict) and last_gate.get("report"):
        report_path = repo_path(str(last_gate["report"]))
        if report_path.exists():
            report = {
                "path": relative_path(report_path),
                "sha256": hashlib.sha256(report_path.read_bytes()).hexdigest(),
            }
    return {
        "direction": direction,
        "display_name": entry.get("display_name", direction),
        "goal": entry.get("goal"),
        "progress_source": relative_path(progress_path),
        "updated_at": progress.get("updated_at"),
        "stages": {
            name: {
                "name": stage.get("name"),
                "status": stage.get("status"),
                "gate_command": stage.get("gate_command"),
                "last_gate": stage.get("last_gate"),
            }
            for name, stage in stages.items()
            if isinstance(stage, dict)
        },
        "active_stages": active,
        "pending_acceptance": pending,
        "last_gate": last_gate,
        "report": report,
    }


def validate_registry(registry: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    directions = registry["directions"]
    progress_owners: dict[str, str] = {}
    registered_specs: set[str] = set()
    for direction, entry in directions.items():
        if not isinstance(entry, dict):
            errors.append(f"{direction}: entry must be an object")
            continue
        required = ("goal", "progress_source", "source_spec", "specs", "gate")
        for key in required:
            if key not in entry:
                errors.append(f"{direction}: missing registry field {key}")
        try:
            goal = repo_path(str(entry["goal"]))
            progress_path = repo_path(str(entry["progress_source"]))
            source_spec = repo_path(str(entry["source_spec"]))
        except (KeyError, TypeError, ValueError) as exc:
            errors.append(f"{direction}: invalid path: {exc}")
            continue
        if not goal.exists():
            errors.append(f"{direction}: missing goal {relative_path(goal)}")
        if not progress_path.exists():
            errors.append(f"{direction}: missing progress source {relative_path(progress_path)}")
        if not source_spec.exists():
            errors.append(f"{direction}: missing source Spec {relative_path(source_spec)}")
        progress_key = relative_path(progress_path)
        previous = progress_owners.setdefault(progress_key, direction)
        if previous != direction:
            errors.append(f"duplicate progress_source {progress_key}: {previous}, {direction}")
        specs = entry.get("specs", [])
        if not isinstance(specs, list) or not specs:
            errors.append(f"{direction}: specs must be a non-empty list")
            specs = []
        spec_paths = set()
        for spec in specs:
            try:
                spec_path = repo_path(str(spec))
            except (TypeError, ValueError) as exc:
                errors.append(f"{direction}: invalid Spec path {spec!r}: {exc}")
                continue
            normalized = relative_path(spec_path)
            spec_paths.add(normalized)
            registered_specs.add(normalized)
            if not spec_path.exists():
                errors.append(f"{direction}: missing detailed Spec {normalized}")
        if relative_path(source_spec) not in spec_paths:
            errors.append(f"{direction}: source_spec is not listed in specs")
        if goal.exists():
            goal_text = goal.read_text(encoding="utf-8")
            expected = f"progress_source: {progress_key}"
            if expected not in goal_text:
                errors.append(f"{direction}: goal does not declare {expected}")
            for spec in spec_paths:
                spec_name = Path(spec).name
                if spec not in goal_text and spec_name not in goal_text:
                    errors.append(f"{direction}: goal does not route detailed Spec {spec}")
        if progress_path.exists():
            try:
                progress = read_data(progress_path)
                if "spec_id" in progress and progress.get("spec_id") != direction:
                    errors.append(f"{direction}: progress spec_id mismatch")
                if progress.get("source_spec") != relative_path(source_spec):
                    errors.append(f"{direction}: progress source_spec mismatch")
                stages = progress.get("stages", {})
                if not isinstance(stages, dict) or not stages:
                    errors.append(f"{direction}: progress has no stages")
                gate = entry.get("gate", {})
                template = gate.get("command_template") if isinstance(gate, dict) else None
                tests = gate.get("tests") if isinstance(gate, dict) else None
                for stage_name, stage in (stages.items() if isinstance(stages, dict) else []):
                    command = stage.get("gate_command") if isinstance(stage, dict) else None
                    if not command:
                        errors.append(f"{direction}/{stage_name}: missing gate_command")
                    elif template and command != template.format(stage=stage_name, direction=direction):
                        errors.append(f"{direction}/{stage_name}: gate_command differs from registry template")
                    if isinstance(tests, dict) and stage_name not in tests:
                        errors.append(f"{direction}/{stage_name}: missing registry gate tests")
            except (OSError, ValueError, KeyError) as exc:
                errors.append(f"{direction}: invalid progress source: {exc}")
    for candidate in (ROOT / "docs/specs").glob("*_SPEC.md"):
        normalized = relative_path(candidate)
        if normalized not in registered_specs:
            errors.append(f"unregistered detailed Spec {normalized}")
    return errors


def _finding(code: str, severity: str, message: str, **context: Any) -> dict[str, Any]:
    return {
        "code": code,
        "severity": severity,
        "message": message,
        **context,
    }


def phase_statuses(text: str) -> dict[str, str]:
    """Read explicit Phase status rows from a markdown table."""
    statuses: dict[str, str] = {}
    for line in text.splitlines():
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) < 2:
            continue
        phase_match = re.match(r"(?i)^Phase\s*(\d+)\b", cells[0])
        status_match = re.match(
            r"(?i)^(Complete|Completed|Partial|In Progress|Proposed|Not Started)\b",
            cells[1],
        )
        if phase_match and status_match:
            statuses[f"P{phase_match.group(1)}"] = status_match.group(1).lower()
    return statuses


def analyze_direction(registry: dict[str, Any], direction: str) -> dict[str, Any]:
    """Check consistency across a direction's Spec, goal, registry and progress.

    This is deliberately read-only. It catches cross-file contradictions before a
    stage gate runs; it does not infer completion from prose or execute tests.
    """
    entry = direction_entry(registry, direction)
    findings: list[dict[str, Any]] = []
    registry_errors = validate_registry(registry)
    findings.extend(
        _finding("registry-invalid", "error", error)
        for error in registry_errors
        if error.startswith(f"{direction}:") or error.startswith(f"{direction}/")
    )

    progress_path, progress = load_progress(entry)
    source_spec = repo_path(str(entry["source_spec"]))
    goal = repo_path(str(entry["goal"]))
    spec_statuses: dict[str, dict[str, str]] = {}
    for spec_value in entry.get("specs", []):
        spec_path = repo_path(str(spec_value))
        if spec_path.exists():
            spec_statuses[relative_path(spec_path)] = phase_statuses(
                spec_path.read_text(encoding="utf-8")
            )
    source_text = source_spec.read_text(encoding="utf-8") if source_spec.exists() else ""
    spec_phase_status = spec_statuses.get(relative_path(source_spec), {})

    per_phase: dict[str, list[tuple[str, str]]] = {}
    for spec_path, statuses in spec_statuses.items():
        for stage_name, declared_status in statuses.items():
            per_phase.setdefault(stage_name, []).append((spec_path, declared_status))
    for stage_name, declarations in per_phase.items():
        distinct = {status for _, status in declarations}
        if len(distinct) > 1:
            findings.append(_finding(
                "cross-spec-phase-status-conflict",
                "error",
                f"{stage_name} has conflicting statuses across registered Specs",
                stage=stage_name,
                declarations=[{"spec": path, "status": status} for path, status in declarations],
            ))

    stages = progress.get("stages", {})
    if not isinstance(stages, dict) or not stages:
        findings.append(_finding("progress-no-stages", "error", "progress source has no stages"))
        stages = {}

    for stage_name, stage in stages.items():
        if not isinstance(stage, dict):
            findings.append(_finding("stage-invalid", "error", f"{stage_name} is not an object", stage=stage_name))
            continue
        stage_status = stage.get("status")
        if stage_status == "complete":
            acceptance = stage.get("acceptance", [])
            for item in acceptance:
                if not isinstance(item, dict):
                    findings.append(_finding("acceptance-invalid", "error", f"{stage_name} has a non-object acceptance item", stage=stage_name))
                    continue
                if item.get("status") != "complete":
                    findings.append(_finding(
                        "complete-stage-pending-acceptance",
                        "error",
                        f"{stage_name} is complete but acceptance {item.get('id', '<unknown>')} is {item.get('status')!r}",
                        stage=stage_name,
                        acceptance=item.get("id"),
                    ))
                for evidence in item.get("evidence", []):
                    if not repo_path(str(evidence)).exists():
                        findings.append(_finding(
                            "missing-acceptance-evidence",
                            "review",
                            f"{stage_name}/{item.get('id', '<unknown>')} references missing evidence {evidence}",
                            stage=stage_name,
                            acceptance=item.get("id"),
                            path=evidence,
                        ))
            last_gate = stage.get("last_gate")
            if not isinstance(last_gate, dict) or last_gate.get("status") != "passed":
                findings.append(_finding(
                    "complete-stage-without-passed-gate",
                    "review",
                    f"{stage_name} is marked complete without a recorded passed last_gate",
                    stage=stage_name,
                ))
            elif last_gate.get("report") and not repo_path(str(last_gate["report"])).exists():
                findings.append(_finding(
                    "missing-stage-gate-report",
                    "review",
                    f"{stage_name} last_gate report is missing: {last_gate['report']}",
                    stage=stage_name,
                    path=last_gate["report"],
                ))
        elif stage_status == "not_started" and any(
            isinstance(item, dict) and item.get("status") == "complete"
            for item in stage.get("acceptance", [])
        ):
            findings.append(_finding(
                "stage-acceptance-status-conflict",
                "error",
                f"{stage_name} is not_started but contains complete acceptance items",
                stage=stage_name,
            ))

        stage_number = re.fullmatch(r"P(\d+)", str(stage_name))
        if stage_number:
            declarations = per_phase.get(stage_name, [])
            if not declarations:
                findings.append(_finding(
                    "stage-not-described-by-spec",
                    "review",
                    f"{stage_name} is present in progress but no registered Spec has a status row for it",
                    stage=stage_name,
                ))
            for spec_path, declared_status in declarations:
                if stage_status == "complete" and declared_status in {"partial", "in progress", "proposed", "not started"}:
                    findings.append(_finding(
                        "spec-progress-status-conflict",
                        "error",
                        f"{stage_name} is complete in progress but {declared_status!r} in {spec_path}",
                        stage=stage_name,
                        spec=spec_path,
                        spec_status=declared_status,
                        progress_status=stage_status,
                    ))
                elif stage_status != "complete" and declared_status in {"complete", "completed"}:
                    findings.append(_finding(
                        "spec-progress-status-conflict",
                        "error",
                        f"{stage_name} is {stage_status!r} in progress but complete in {spec_path}",
                        stage=stage_name,
                        spec=spec_path,
                        spec_status=declared_status,
                        progress_status=stage_status,
                    ))

    errors = [item for item in findings if item["severity"] == "error"]
    return {
        "direction": direction,
        "source_spec": relative_path(source_spec),
        "goal": relative_path(goal),
        "progress_source": relative_path(progress_path),
        "spec_phase_status": spec_phase_status,
        "registered_spec_phase_status": spec_statuses,
        "stages": {name: stage.get("status") for name, stage in stages.items() if isinstance(stage, dict)},
        "status": "fail" if errors else "pass",
        "findings": findings,
    }


def insert_goal_link(goal: Path, spec: Path) -> bool:
    text = goal.read_text(encoding="utf-8") if goal.exists() else ""
    normalized = relative_path(spec)
    if normalized in text or spec.name in text:
        return False
    link = os.path.relpath(spec, goal.parent).replace(os.sep, "/")
    line = f"- [{spec.name}]({link})\n"
    marker = "## 定向阅读"
    if marker in text:
        start = text.index(marker) + len(marker)
        next_heading = text.find("\n## ", start)
        insertion = next_heading if next_heading != -1 else len(text)
        text = text[:insertion].rstrip() + "\n" + line + text[insertion:]
    else:
        text = text.rstrip() + f"\n\n{marker}\n\n" + line
    goal.write_text(text, encoding="utf-8")
    return True


def register(args: argparse.Namespace) -> dict[str, Any]:
    registry = load_registry()
    directions = registry["directions"]
    spec_path = repo_path(args.spec)
    if not spec_path.exists():
        raise ValueError(f"Spec does not exist: {relative_path(spec_path)}")
    normalized_spec = relative_path(spec_path)
    owners = [name for name, entry in directions.items() if normalized_spec in entry.get("specs", [])]
    if owners and (args.direction not in owners or len(owners) > 1):
        raise ValueError(f"Spec is already registered under {', '.join(owners)}")
    created = False
    if args.direction not in directions:
        if not args.new_direction:
            raise ValueError(f"unknown direction {args.direction!r}; use --new-direction with scaffolding paths")
        required = {"goal": args.goal, "progress_source": args.progress_source, "source_spec": args.source_spec, "gate_command": args.gate_command}
        missing = [key for key, value in required.items() if not value]
        if missing:
            raise ValueError("new direction requires: " + ", ".join(missing))
        goal = repo_path(args.goal)
        progress = repo_path(args.progress_source)
        source_spec = repo_path(args.source_spec)
        for path in (goal, progress):
            if path.exists():
                raise ValueError(f"refusing to overwrite existing path: {relative_path(path)}")
        if not source_spec.exists():
            raise ValueError(f"source Spec does not exist: {relative_path(source_spec)}")
        registered_specs = [relative_path(source_spec)]
        if normalized_spec not in registered_specs:
            registered_specs.append(normalized_spec)
        directions[args.direction] = {
            "display_name": args.display_name or args.direction,
            "goal": relative_path(goal),
            "progress_source": relative_path(progress),
            "source_spec": relative_path(source_spec),
            "specs": registered_specs,
            "gate": {"command_template": args.gate_command, "tests": {args.stage: args.tests or []}},
        }
        goal.write_text(
            f"# {args.display_name or args.direction}\n\n"
            f"唯一进度源：`{relative_path(progress)}`。\n\n"
            "## 定向阅读\n\n"
            f"- [{source_spec.name}]({os.path.relpath(source_spec, goal.parent).replace(os.sep, '/')})\n"
            + (f"- [{spec_path.name}]({os.path.relpath(spec_path, goal.parent).replace(os.sep, '/')})\n" if spec_path != source_spec else ""),
            encoding="utf-8",
        )
        write_data(progress, {
            "schema_version": "spec-progress/v1",
            "spec_id": args.direction,
            "source_spec": relative_path(source_spec),
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "stages": {args.stage: {"name": args.stage, "status": "not_started", "gate_command": args.gate_command.format(stage=args.stage, direction=args.direction), "acceptance": []}},
            "last_gate": None,
        })
        created = True
    else:
        entry = direction_entry(registry, args.direction)
        entry.setdefault("specs", [])
        if normalized_spec not in entry["specs"]:
            entry["specs"].append(normalized_spec)
        goal = repo_path(str(entry["goal"]))
        linked = insert_goal_link(goal, spec_path)
        write_data(REGISTRY_PATH, registry)
        return {"direction": args.direction, "spec": normalized_spec, "registered": True, "goal_link_added": linked, "progress_source": entry["progress_source"], "progress_changed": False}
    write_data(REGISTRY_PATH, registry)
    return {"direction": args.direction, "spec": normalized_spec, "registered": created, "goal_link_added": True, "progress_source": directions[args.direction]["progress_source"], "progress_changed": True}


def sync_routes() -> dict[str, Any]:
    registry = load_registry()
    changed: list[str] = []
    for entry in registry["directions"].values():
        goal = repo_path(str(entry["goal"]))
        for spec_value in entry.get("specs", []):
            spec = repo_path(str(spec_value))
            if spec.exists() and goal.exists() and insert_goal_link(goal, spec):
                changed.append(relative_path(goal))
    errors = validate_registry(registry)
    return {"synced_goals": sorted(set(changed)), "progress_sources_untouched": True, "valid": not errors, "errors": errors}


def update_progress(args: argparse.Namespace) -> dict[str, Any]:
    """Update progress.yaml with validation (safer than manual editing)."""
    registry = load_registry()
    entry = direction_entry(registry, args.direction)
    progress_path, progress = load_progress(entry)

    # Validate stage exists
    stages = progress.get("stages", {})
    if args.stage not in stages:
        raise ValueError(f"stage {args.stage!r} not found in {args.direction}")

    stage = stages[args.stage]

    # Update stage status if provided
    if args.stage_status:
        valid_statuses = ["not_started", "in_progress", "complete"]
        if args.stage_status not in valid_statuses:
            raise ValueError(f"stage status must be one of: {valid_statuses}")
        stage["status"] = args.stage_status

    # Update acceptance item if provided
    if args.acceptance:
        acceptance_items = stage.get("acceptance", [])
        item_found = False
        for item in acceptance_items:
            if item.get("id") == args.acceptance:
                item_found = True
                if args.acceptance_status:
                    valid_statuses = ["not_started", "in_progress", "partial", "complete"]
                    if args.acceptance_status not in valid_statuses:
                        raise ValueError(f"acceptance status must be one of: {valid_statuses}")
                    item["status"] = args.acceptance_status
                if args.note:
                    if "notes" not in item:
                        item["notes"] = args.note
                    else:
                        item["notes"] = args.note
                break

        if not item_found:
            raise ValueError(f"acceptance item {args.acceptance!r} not found in stage {args.stage}")

    # Update timestamp
    progress["updated_at"] = datetime.now(timezone.utc).isoformat()

    # Validate before saving
    if args.validate:
        # Check that gate_command exists
        if not stage.get("gate_command"):
            raise ValueError(f"stage {args.stage} has no gate_command")

    # Save updated progress
    write_data(progress_path, progress)

    return {
        "updated": True,
        "progress_source": relative_path(progress_path),
        "stage": args.stage,
        "stage_status": stage.get("status"),
        "acceptance_updated": args.acceptance if args.acceptance else None,
        "updated_at": progress["updated_at"],
    }


def run_gate(args: argparse.Namespace) -> int:
    registry = load_registry()
    entry = direction_entry(registry, args.direction)
    consistency = analyze_direction(registry, args.direction)
    print(json.dumps(consistency, ensure_ascii=False, indent=2))
    if consistency["status"] != "pass":
        print("Spec consistency check failed; stage gate was not run.", file=sys.stderr)
        return 2
    progress_path, progress = load_progress(entry)
    stage = progress.get("stages", {}).get(args.stage)
    if not isinstance(stage, dict):
        raise ValueError(f"unknown stage {args.stage!r} for {args.direction}")
    command = stage.get("gate_command")
    if not command:
        raise ValueError(f"{args.direction}/{args.stage} has no gate_command")
    result = subprocess.run(command, cwd=ROOT, shell=True, text=True, capture_output=True, check=False)
    fresh = read_data(progress_path)
    payload = {"direction": args.direction, "stage": args.stage, "command": command, "returncode": result.returncode, "stdout": result.stdout, "stderr": result.stderr, "status": fresh.get("stages", {}).get(args.stage, {}).get("status"), "last_gate": fresh.get("stages", {}).get(args.stage, {}).get("last_gate")}
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return result.returncode


def watch(args: argparse.Namespace) -> int:
    registry = load_registry()
    entry = direction_entry(registry, args.direction)
    progress_path = repo_path(str(entry["progress_source"]))
    previous = None
    count = 0
    try:
        while not args.iterations or count < args.iterations:
            snapshot = status_snapshot(registry, args.direction)
            serialized = json.dumps(snapshot, ensure_ascii=False, sort_keys=True)
            if serialized != previous:
                print(json.dumps({"observed_at": datetime.now(timezone.utc).isoformat(), "event": "changed", "status": snapshot}, ensure_ascii=False))
                previous = serialized
            count += 1
            if args.iterations and count >= args.iterations:
                break
            time.sleep(args.interval)
            registry = load_registry()
            entry = direction_entry(registry, args.direction)
            progress_path = repo_path(str(entry["progress_source"]))
    except KeyboardInterrupt:
        return 0
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", help="repository root (reserved for external callers)")
    sub = parser.add_subparsers(dest="mode", required=True)
    sub.add_parser("validate")
    analyze = sub.add_parser(
        "analyze",
        help="Check cross-file consistency before running a Spec stage gate",
    )
    analyze.add_argument("--direction", required=True)
    sub.add_parser("sync")
    status = sub.add_parser("status")
    status.add_argument("--direction", required=True)
    gate = sub.add_parser("gate")
    gate.add_argument("--direction", required=True)
    gate.add_argument("--stage", required=True)
    register_parser = sub.add_parser("register")
    register_parser.add_argument("--direction", required=True)
    register_parser.add_argument("--spec", required=True)
    register_parser.add_argument("--new-direction", action="store_true")
    register_parser.add_argument("--goal")
    register_parser.add_argument("--progress-source")
    register_parser.add_argument("--source-spec")
    register_parser.add_argument("--gate-command")
    register_parser.add_argument("--stage", default="INITIAL")
    register_parser.add_argument("--tests", nargs="*")
    register_parser.add_argument("--display-name")
    watch_parser = sub.add_parser("watch")
    watch_parser.add_argument("--direction", required=True)
    watch_parser.add_argument("--interval", type=float, default=2.0)
    watch_parser.add_argument("--iterations", type=int, default=0)
    update_parser = sub.add_parser("update", help="Update progress.yaml with validation")
    update_parser.add_argument("--direction", required=True, help="Direction to update")
    update_parser.add_argument("--stage", required=True, help="Stage to update")
    update_parser.add_argument("--stage-status", help="New stage status (not_started, in_progress, complete)")
    update_parser.add_argument("--acceptance", help="Acceptance item ID to update")
    update_parser.add_argument("--acceptance-status", help="New acceptance status (not_started, in_progress, partial, complete)")
    update_parser.add_argument("--note", help="Note to add/update for acceptance item")
    update_parser.add_argument("--validate", action="store_true", default=True, help="Validate after update")
    args = parser.parse_args()
    if args.root:
        global ROOT, REGISTRY_PATH
        ROOT = Path(args.root).resolve()
        REGISTRY_PATH = ROOT / "docs/specs/registry.yaml"
    try:
        if args.mode == "validate":
            errors = validate_registry(load_registry())
            print(json.dumps({"valid": not errors, "errors": errors}, ensure_ascii=False, indent=2))
            return 0 if not errors else 1
        if args.mode == "analyze":
            result = analyze_direction(load_registry(), args.direction)
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0 if result["status"] == "pass" else 1
        if args.mode == "sync":
            result = sync_routes()
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0 if result["valid"] else 1
        if args.mode == "status":
            print(json.dumps(status_snapshot(load_registry(), args.direction), ensure_ascii=False, indent=2))
            return 0
        if args.mode == "register":
            print(json.dumps(register(args), ensure_ascii=False, indent=2))
            return 0
        if args.mode == "gate":
            return run_gate(args)
        if args.mode == "update":
            print(json.dumps(update_progress(args), ensure_ascii=False, indent=2))
            return 0
        if args.mode == "watch":
            if args.interval <= 0:
                raise ValueError("watch interval must be positive")
            return watch(args)
    except (OSError, ValueError, KeyError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
