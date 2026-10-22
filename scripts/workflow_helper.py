#!/usr/bin/env python3
"""Workflow Helper - Guide users through common repository workflows.

This tool provides interactive checklists and guidance for common tasks,
helping developers follow the correct workflow without memorizing all steps.
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Optional

# Simple ASCII symbols for Windows compatibility
RED = ""
GREEN = ""
YELLOW = ""
BLUE = ""
BOLD = ""
RESET = ""
SYMBOLS = {
    "success": "[+]",
    "fail": "[-]",
    "arrow": "->",
    "warning": "[!]",
}


def print_step(step_num: int, description: str, status: str = "arrow"):
    """Print a workflow step with status indicator."""
    symbol = SYMBOLS.get(status, "->")
    print(f"{symbol} Step {step_num}: {description}")


def print_header(title: str):
    """Print a section header."""
    print(f"\n{'=' * 60}")
    print(f"{title}")
    print(f"{'=' * 60}\n")


def run_command(cmd: list[str], description: str, check: bool = True) -> tuple[bool, str]:
    """Run a command and return success status and output."""
    print(f"\n[Running] {' '.join(cmd)}")
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        output = result.stdout
        if result.stderr:
            output = f"{output}\n{result.stderr}" if output else result.stderr
        if result.returncode != 0:
            print(f"[-] Failed: {description}")
            if result.stderr:
                print(f"{result.stderr[:500]}")
            return False, output
        print(f"[+] Success: {description}")
        return True, output
    except Exception as e:
        print(f"[-] Error: {e}")
        return False, str(e)


def workflow_spec_update(direction: str):
    """Guide through updating a Spec and its progress."""
    print_header(f"Spec Update Workflow: {direction}")

    print(f"This workflow will guide you through:")
    print("  1. Checking current progress")
    print("  2. Reading relevant Spec files")
    print("  3. Validating configuration")
    print("  4. Running stage gate")
    print("  5. Checking PR readiness\n")

    # Step 1: Check current status
    print_step(1, f"Check current progress for {direction}")
    success, output = run_command(
        [sys.executable, ".codex/skills/spec-progress-workflow/scripts/spec_workflow.py",
         "status", "--direction", direction],
        "Query current progress",
        check=False
    )
    if not success:
        print("[-] Cannot continue because the Spec status lookup failed.")
        return False
    print(f"{output[:1000]}")

    # Step 2: Files to read
    print_step(2, "Read required Spec files")
    print("  -> docs/specs/ORGANIZATION_RULES.md (required for all Spec work)")
    print(f"  -> docs/specs/goals/{direction}.md (direction-specific goals)")
    print("  -> Read the progress source declared in docs/specs/registry.yaml")
    print("\n  Make code changes, then update progress with spec_workflow.py")

    input(f"\nPress Enter when you've made your changes...")

    # Step 3: Validate configuration
    print_step(3, "Validate Spec configuration")
    success, output = run_command(
        [sys.executable, ".codex/skills/spec-progress-workflow/scripts/spec_workflow.py", "validate"],
        "Validate spec workflow configuration"
    )
    if not success:
        print(f"[-] Validation failed. Fix errors before continuing.")
        return False

    # Step 4: Analyze cross-file Spec consistency before executing tests.
    print_step(4, "Analyze Spec and progress consistency")
    success, output = run_command(
        [sys.executable, ".codex/skills/spec-progress-workflow/scripts/spec_workflow.py",
         "analyze", "--direction", direction],
        "Analyze Spec consistency",
        check=False,
    )
    if not success:
        print("[-] Resolve Spec consistency errors before running the stage gate.")
        return False
    print(output[:2500])

    # Step 5: Run stage gate (optional)
    print_step(5, "Run stage gate (optional)")
    stage = input(f"Enter stage to test (or press Enter to skip): ").strip()
    if stage:
        if direction == "harness":
            cmd = [sys.executable, "scripts/ci/harness_stage_gate.py", "--stage", stage]
        else:
            cmd = [sys.executable, "scripts/ci/spec_stage_gate.py",
                   "--spec", direction, "--stage", stage]
        success, _ = run_command(cmd, f"Run {stage} gate", check=False)
        if not success:
            return False

    # Step 6: Check PR readiness
    print_step(6, "Check PR readiness")
    success, output = run_command(
        [sys.executable, "scripts/ci/check_pr_ready.py"],
        "Verify PR is ready",
        check=False
    )

    if not success:
        print("[-] PR readiness check failed. Fix the reported blockers before submitting.")
        return False

    if "docs corpus baseline is changed" in output:
        print(f"\n[!] Docs baseline needs refresh")
        refresh = input(f"Run git-docs evaluation? (y/n): ").strip().lower()
        if refresh == 'y':
            run_command(
                [sys.executable, "scripts/eval/docs/run_git_docs_eval.py", "--refresh-baseline"],
                "Refresh docs corpus baseline"
            )

    # Summary
    print_header("Workflow Complete")
    print(f"[+] Configuration validated")
    print(f"[+] Changes ready for review")
    print(f"\nNext steps:")
    print(f"  1. Review git diff")
    print(f"  2. Commit your changes")
    print(f"  3. Create/update PR")

    return True


def workflow_check_status(direction: Optional[str] = None):
    """Check status of one or all directions."""
    print_header("Spec Progress Status")

    if direction:
        cmd = [sys.executable, ".codex/skills/spec-progress-workflow/scripts/spec_workflow.py",
               "status", "--direction", direction]
    else:
        # Show all directions
        print(f"{BOLD}Available directions:{RESET}")
        print("  - harness (registered in docs/specs/registry.yaml)")
        direction = input(f"\n{BOLD}Enter direction (or 'all' for summary):{RESET} ").strip()
        if direction == "all":
            for d in ["harness"]:
                print(f"\n{BOLD}=== {d} ==={RESET}")
                run_command(
                    [sys.executable, ".codex/skills/spec-progress-workflow/scripts/spec_workflow.py",
                     "status", "--direction", d],
                    f"Status for {d}",
                    check=False
                )
            return
        cmd = [sys.executable, ".codex/skills/spec-progress-workflow/scripts/spec_workflow.py",
               "status", "--direction", direction]

    run_command(cmd, f"Get status for {direction}")


def workflow_pr_ready():
    """Run pre-PR checklist."""
    print_header("Pre-PR Checklist")

    checklist = [
        ("Git status check", ["git", "status", "--short", "--branch"]),
        ("Git diff check", ["git", "diff", "--check"]),
        ("Git cached diff check", ["git", "diff", "--cached", "--check"]),
        ("Spec validation", [sys.executable, ".codex/skills/spec-progress-workflow/scripts/spec_workflow.py", "validate"]),
    ]
    registry_path = Path("docs/specs/registry.yaml")
    try:
        directions = json.loads(registry_path.read_text(encoding="utf-8"))["directions"]
        for direction in directions:
            checklist.append((
                f"Spec consistency ({direction})",
                [sys.executable, ".codex/skills/spec-progress-workflow/scripts/spec_workflow.py",
                 "analyze", "--direction", direction],
            ))
    except (OSError, ValueError, KeyError, TypeError) as exc:
        checklist.append((
            "Spec registry readable",
            [sys.executable, ".codex/skills/spec-progress-workflow/scripts/spec_workflow.py", "validate"],
        ))
        print(f"[-] Cannot enumerate registered Specs: {exc}")
    checklist.append(("PR ready check", [sys.executable, "scripts/ci/check_pr_ready.py"]))

    results = []
    for description, cmd in checklist:
        success, output = run_command(cmd, description, check=False)
        results.append((description, success))
        if not success and "check_pr_ready" not in cmd[-1]:
            print(f"{RED}✗ Failed: {description}{RESET}")

    # Summary
    print_header("Checklist Summary")
    for description, success in results:
        status = f"{GREEN}✓{RESET}" if success else f"{RED}✗{RESET}"
        print(f"{status} {description}")

    all_passed = all(success for _, success in results)
    if all_passed:
        print(f"\n{GREEN}{BOLD}✓ All checks passed! PR is ready.{RESET}")
    else:
        print(f"\n{RED}{BOLD}✗ Some checks failed. Review and fix before creating PR.{RESET}")

    return all_passed


def workflow_list():
    """List available workflows."""
    print_header("Available Workflows")

    workflows = [
        ("spec-update", "Update a Spec and its progress (guided workflow)"),
        ("status", "Check current progress for a direction"),
        ("pr-ready", "Run pre-PR checklist"),
        ("list", "Show this list of workflows"),
    ]

    print(f"{BOLD}Usage:{RESET} python scripts/workflow_helper.py --workflow <name> [options]\n")

    for name, description in workflows:
        print(f"  {BLUE}{name:<15}{RESET} {description}")

    print(f"\n{BOLD}Examples:{RESET}")
    print(f"  python scripts/workflow_helper.py --workflow spec-update --direction harness")
    print(f"  python scripts/workflow_helper.py --workflow status")
    print(f"  python scripts/workflow_helper.py --workflow pr-ready")


def main():
    parser = argparse.ArgumentParser(
        description="Workflow helper for repository tasks",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--workflow",
        choices=["spec-update", "status", "pr-ready", "list"],
        required=True,
        help="Workflow to run",
    )
    parser.add_argument(
        "--direction",
        help="Spec direction registered in docs/specs/registry.yaml",
    )

    args = parser.parse_args()

    try:
        if args.workflow == "list":
            workflow_list()
        elif args.workflow == "spec-update":
            if not args.direction:
                print(f"{RED}Error: --direction required for spec-update{RESET}")
                sys.exit(1)
            workflow_spec_update(args.direction)
        elif args.workflow == "status":
            workflow_check_status(args.direction)
        elif args.workflow == "pr-ready":
            success = workflow_pr_ready()
            sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        print(f"\n{YELLOW}Workflow interrupted{RESET}")
        sys.exit(1)
    except Exception as e:
        print(f"\n{RED}Error: {e}{RESET}")
        sys.exit(1)


if __name__ == "__main__":
    main()
