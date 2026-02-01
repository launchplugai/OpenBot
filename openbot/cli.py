#!/usr/bin/env python3
"""
Openbot CLI - Command line interface for Openbot automation runtime.

Usage:
    python -m openbot.cli doctor
    python -m openbot.cli run --target-repo <url> --target-branch <branch> ...
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Dict, Any, List

from openbot.utils import (
    find_binary,
    is_writable,
    ensure_dir,
    get_timestamp,
    generate_run_id,
    save_json,
    Logger,
)
from openbot.runner import Runner
from openbot.policy import PolicyLoader


# Default paths
DEFAULT_LOGS_DIR = Path("/var/lib/openbot/logs")
DEFAULT_RECEIPTS_DIR = Path("/var/lib/openbot/receipts")
DEFAULT_WORKDIR = Path("/var/lib/openbot/workdir")

# For local development, use relative paths
LOCAL_LOGS_DIR = Path("./logs")
LOCAL_RECEIPTS_DIR = Path("./receipts")
LOCAL_WORKDIR = Path("./workdir")


def get_paths(local: bool = False) -> tuple[Path, Path, Path]:
    """Get paths based on mode."""
    if local:
        return LOCAL_LOGS_DIR, LOCAL_RECEIPTS_DIR, LOCAL_WORKDIR
    return DEFAULT_LOGS_DIR, DEFAULT_RECEIPTS_DIR, DEFAULT_WORKDIR


def cmd_doctor(args) -> int:
    """
    Run environment health checks.

    Checks:
    - Required binaries exist
    - Required directories are writable
    - Policies can be loaded

    Returns 0 if healthy, non-zero otherwise.
    """
    logs_dir, receipts_dir, workdir = get_paths(args.local)
    run_id = generate_run_id()

    report: Dict[str, Any] = {
        "report_type": "doctor",
        "timestamp": get_timestamp(),
        "run_id": run_id,
        "checks": {},
        "errors": [],
        "overall_status": "HEALTHY"
    }

    # Check required binaries
    required_binaries = ["git", "python3"]
    binaries_ok = True
    report["checks"]["binaries"] = {}

    for binary in required_binaries:
        path = find_binary(binary)
        report["checks"]["binaries"][binary] = {
            "found": path is not None,
            "path": path
        }
        if path is None:
            binaries_ok = False
            report["errors"].append(f"Required binary not found: {binary}")

    # Check writable directories
    dirs_to_check = {
        "logs": logs_dir,
        "receipts": receipts_dir,
        "workdir": workdir
    }
    dirs_ok = True
    report["checks"]["directories"] = {}

    for name, dir_path in dirs_to_check.items():
        writable = is_writable(dir_path)
        report["checks"]["directories"][name] = {
            "path": str(dir_path),
            "writable": writable,
            "exists": dir_path.exists()
        }
        if not writable:
            dirs_ok = False
            report["errors"].append(f"Directory not writable: {dir_path}")

    # Check policies
    policy_loader = PolicyLoader()
    policies_ok = policy_loader.load_all()
    report["checks"]["policies"] = {
        "loaded": policy_loader.get_loaded_policy_names(),
        "errors": policy_loader.get_load_errors()
    }
    if not policies_ok:
        report["errors"].extend(policy_loader.get_load_errors())

    # Determine overall status
    if not binaries_ok or not dirs_ok:
        report["overall_status"] = "UNHEALTHY"
    elif not policies_ok:
        report["overall_status"] = "DEGRADED"
    else:
        report["overall_status"] = "HEALTHY"

    # Output to stdout
    print(json.dumps(report, indent=2))

    # Write to logs if possible
    if is_writable(logs_dir):
        ensure_dir(logs_dir)
        log_path = logs_dir / f"doctor_{run_id}.json"
        save_json(log_path, report)
        print(f"\nDoctor report written to: {log_path}", file=sys.stderr)

    # Return appropriate exit code
    if report["overall_status"] == "HEALTHY":
        return 0
    elif report["overall_status"] == "DEGRADED":
        return 1
    else:
        return 2


def cmd_run(args) -> int:
    """
    Execute a test run against target repository.

    Returns 0 on success, non-zero on failure.
    """
    logs_dir, receipts_dir, default_workdir = get_paths(args.local)

    # Override with args if provided
    if args.logs_dir:
        logs_dir = Path(args.logs_dir)
    if args.receipts_dir:
        receipts_dir = Path(args.receipts_dir)
    workdir = Path(args.workdir) if args.workdir else default_workdir

    # Validate required arguments
    if not args.target_repo:
        print("Error: --target-repo is required", file=sys.stderr)
        return 1
    if not args.target_branch:
        print("Error: --target-branch is required", file=sys.stderr)
        return 1
    if not args.command:
        print("Error: --command is required", file=sys.stderr)
        return 1

    # Create runner
    runner = Runner(
        target_repo=args.target_repo,
        target_branch=args.target_branch,
        workdir=workdir,
        command=args.command,
        logs_dir=logs_dir,
        receipts_dir=receipts_dir,
        health_url=args.health_url
    )

    # Execute run
    success, receipt_path = runner.run()

    print(f"\nReceipt written to: {receipt_path}", file=sys.stderr)

    return 0 if success else 1


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        prog="openbot",
        description="Openbot Automation Runtime CLI"
    )
    parser.add_argument(
        "--version",
        action="version",
        version="openbot 0.1.0"
    )

    subparsers = parser.add_subparsers(dest="subcommand", help="Available commands")

    # Doctor command
    doctor_parser = subparsers.add_parser(
        "doctor",
        help="Check runtime environment health"
    )
    doctor_parser.add_argument(
        "--local",
        action="store_true",
        help="Use local paths instead of system paths"
    )

    # Run command
    run_parser = subparsers.add_parser(
        "run",
        help="Execute test run against target repository"
    )
    run_parser.add_argument(
        "--target-repo",
        required=True,
        help="Git repository URL to clone"
    )
    run_parser.add_argument(
        "--target-branch",
        required=True,
        help="Git branch to checkout"
    )
    run_parser.add_argument(
        "--workdir",
        help="Working directory for clone (default: system or local path)"
    )
    run_parser.add_argument(
        "--command",
        required=True,
        help="Test command to execute"
    )
    run_parser.add_argument(
        "--health-url",
        help="Optional health check URL"
    )
    run_parser.add_argument(
        "--local",
        action="store_true",
        help="Use local paths instead of system paths"
    )
    run_parser.add_argument(
        "--logs-dir",
        help="Override logs directory"
    )
    run_parser.add_argument(
        "--receipts-dir",
        help="Override receipts directory"
    )

    args = parser.parse_args()

    if args.subcommand is None:
        parser.print_help()
        return 1

    if args.subcommand == "doctor":
        return cmd_doctor(args)
    elif args.subcommand == "run":
        return cmd_run(args)
    else:
        parser.print_help()
        return 1


if __name__ == "__main__":
    sys.exit(main())
