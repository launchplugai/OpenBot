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
    safe_path_exists,
    ensure_dir,
    get_timestamp,
    generate_run_id,
    save_json,
    Logger,
    check_aws_cli,
    check_ssm_plugin,
    ssm_describe_instance,
    ssm_send_command,
    ssm_start_session_command,
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
    Always outputs JSON report, even on errors.
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

    # Check writable directories (with PermissionError handling)
    dirs_to_check = {
        "logs": logs_dir,
        "receipts": receipts_dir,
        "workdir": workdir
    }
    dirs_ok = True
    report["checks"]["directories"] = {}

    for name, dir_path in dirs_to_check.items():
        # is_writable and safe_path_exists never raise PermissionError
        writable = is_writable(dir_path)
        exists = safe_path_exists(dir_path)
        report["checks"]["directories"][name] = {
            "path": str(dir_path),
            "writable": writable,
            "exists": exists
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

    # Output to stdout (always)
    print(json.dumps(report, indent=2))

    # Write report to disk with fallback paths
    log_path = _write_doctor_report(report, run_id, logs_dir)
    if log_path:
        print(f"\nDoctor report written to: {log_path}", file=sys.stderr)

    # Return appropriate exit code
    if report["overall_status"] == "HEALTHY":
        return 0
    elif report["overall_status"] == "DEGRADED":
        return 1
    else:
        return 2


def _write_doctor_report(report: Dict[str, Any], run_id: str, primary_logs_dir: Path) -> str:
    """
    Write doctor report to disk with fallback paths.

    Tries in order:
    1. Primary logs directory (e.g., /var/lib/openbot/logs or ./logs)
    2. /tmp
    3. Current working directory

    Returns the path where report was written, or empty string on failure.
    """
    fallback_dirs = [
        primary_logs_dir,
        Path("/tmp"),
        Path(".")
    ]

    filename = f"doctor_{run_id}.json"

    for logs_dir in fallback_dirs:
        if is_writable(logs_dir):
            ensure_dir(logs_dir)
            log_path = logs_dir / filename
            if save_json(log_path, report):
                return str(log_path)

    return ""


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

        return 1

    # Create runner
    runner = Runner(
        target_repo=args.target_repo,
        target_branch=args.target_branch,
        workdir=workdir,
        command=args.command,
        logs_dir=logs_dir,
        receipts_dir=receipts_dir,
        health_url=args.health_url,
        setup_command=getattr(args, 'setup_command', None)
    )

    # Execute run
    success, receipt_path = runner.run()

    print(f"\nReceipt written to: {receipt_path}", file=sys.stderr)

    return 0 if success else 1


def cmd_ssm_verify(args) -> int:
    """
    Verify SSM prerequisites and instance connectivity.

    Checks:
    - AWS CLI is installed
    - Session Manager plugin is installed
    - Instance is registered with SSM (if instance-id provided)

    Returns 0 if all checks pass, non-zero otherwise.
    """
    report: Dict[str, Any] = {
        "report_type": "ssm_verify",
        "timestamp": get_timestamp(),
        "checks": {},
        "errors": [],
        "overall_status": "READY"
    }

    # Check AWS CLI
    aws_ok, aws_info = check_aws_cli()
    report["checks"]["aws_cli"] = {
        "available": aws_ok,
        "info": aws_info
    }
    if not aws_ok:
        report["errors"].append(f"AWS CLI: {aws_info}")

    # Check Session Manager plugin
    plugin_ok, plugin_info = check_ssm_plugin()
    report["checks"]["session_manager_plugin"] = {
        "available": plugin_ok,
        "info": plugin_info
    }
    if not plugin_ok:
        report["errors"].append(f"Session Manager plugin: {plugin_info}")

    # Check instance if provided
    if args.instance_id:
        instance_ok, instance_info = ssm_describe_instance(
            args.instance_id,
            region=args.region
        )
        report["checks"]["instance"] = {
            "instance_id": args.instance_id,
            "managed": instance_ok,
            "info": instance_info
        }
        if instance_ok:
            report["checks"]["instance"]["ping_status"] = instance_info.get("PingStatus", "Unknown")
            report["checks"]["instance"]["platform"] = instance_info.get("PlatformName", "Unknown")
            report["checks"]["instance"]["agent_version"] = instance_info.get("AgentVersion", "Unknown")
        else:
            report["errors"].append(f"Instance: {instance_info.get('error', 'Unknown error')}")

    # Determine overall status
    if not aws_ok or not plugin_ok:
        report["overall_status"] = "NOT_READY"
    elif args.instance_id and not instance_ok:
        report["overall_status"] = "INSTANCE_NOT_MANAGED"
    else:
        report["overall_status"] = "READY"

    print(json.dumps(report, indent=2))

    return 0 if report["overall_status"] == "READY" else 1


def cmd_ssm_connect(args) -> int:
    """
    Print the command to start an SSM session.

    Since SSM sessions are interactive, this command outputs the
    AWS CLI command that the user should run.
    """
    # First verify prerequisites
    aws_ok, aws_info = check_aws_cli()
    if not aws_ok:
        print(f"Error: {aws_info}", file=sys.stderr)
        return 1

    plugin_ok, plugin_info = check_ssm_plugin()
    if not plugin_ok:
        print(f"Error: {plugin_info}", file=sys.stderr)
        print("\nTo install the Session Manager plugin:", file=sys.stderr)
        print("  https://docs.aws.amazon.com/systems-manager/latest/userguide/session-manager-working-with-install-plugin.html", file=sys.stderr)
        return 1

    # Verify instance is managed (if requested)
    if not args.skip_verify:
        instance_ok, instance_info = ssm_describe_instance(
            args.instance_id,
            region=args.region
        )
        if not instance_ok:
            print(f"Error: Instance {args.instance_id} is not managed by SSM", file=sys.stderr)
            print(f"Details: {instance_info.get('error', 'Unknown error')}", file=sys.stderr)
            return 1

        ping_status = instance_info.get("PingStatus", "Unknown")
        if ping_status != "Online":
            print(f"Warning: Instance ping status is '{ping_status}' (expected 'Online')", file=sys.stderr)

    # Generate and print the connect command
    connect_cmd = ssm_start_session_command(args.instance_id, region=args.region)

    print("Run the following command to start an SSM session:\n")
    print(f"  {connect_cmd}\n")

    return 0


def cmd_ssm_run(args) -> int:
    """
    Execute a command on a remote instance via SSM Run Command.

    Returns 0 if command succeeds, non-zero otherwise.
    """
    # Verify AWS CLI
    aws_ok, aws_info = check_aws_cli()
    if not aws_ok:
        print(f"Error: {aws_info}", file=sys.stderr)
        return 1

    # Execute command
    print(f"Sending command to {args.instance_id}...", file=sys.stderr)

    success, result = ssm_send_command(
        args.instance_id,
        args.command,
        region=args.region,
        timeout=args.timeout
    )

    if args.json:
        # JSON output mode
        output = {
            "instance_id": args.instance_id,
            "command": args.command,
            "success": success,
            "result": result
        }
        print(json.dumps(output, indent=2))
    else:
        # Human-readable output
        if success:
            print(f"\nCommand completed successfully (exit code: {result.get('exit_code', 0)})")
            stdout = result.get("stdout", "").strip()
            if stdout:
                print("\n--- STDOUT ---")
                print(stdout)
            stderr = result.get("stderr", "").strip()
            if stderr:
                print("\n--- STDERR ---")
                print(stderr)
        else:
            print(f"\nCommand failed: {result.get('error', result.get('status', 'Unknown error'))}", file=sys.stderr)
            stderr = result.get("stderr", "").strip()
            if stderr:
                print("\n--- STDERR ---", file=sys.stderr)
                print(stderr, file=sys.stderr)

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
        "--setup-command",
        help="Optional setup command to run before tests (e.g., pip install -r requirements.txt)"
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

    # SSM command (with subcommands)
    ssm_parser = subparsers.add_parser(
        "ssm",
        help="AWS Systems Manager (SSM) operations"
    )
    ssm_subparsers = ssm_parser.add_subparsers(dest="ssm_subcommand", help="SSM commands")

    # SSM verify subcommand
    ssm_verify_parser = ssm_subparsers.add_parser(
        "verify",
        help="Verify SSM prerequisites and instance connectivity"
    )
    ssm_verify_parser.add_argument(
        "--instance-id",
        help="EC2 instance ID to verify (optional)"
    )
    ssm_verify_parser.add_argument(
        "--region",
        help="AWS region (uses default if not specified)"
    )

    # SSM connect subcommand
    ssm_connect_parser = ssm_subparsers.add_parser(
        "connect",
        help="Get command to start an SSM session"
    )
    ssm_connect_parser.add_argument(
        "instance_id",
        help="EC2 instance ID to connect to"
    )
    ssm_connect_parser.add_argument(
        "--region",
        help="AWS region (uses default if not specified)"
    )
    ssm_connect_parser.add_argument(
        "--skip-verify",
        action="store_true",
        help="Skip verifying instance is managed by SSM"
    )

    # SSM run subcommand
    ssm_run_parser = ssm_subparsers.add_parser(
        "run",
        help="Execute a command on a remote instance via SSM"
    )
    ssm_run_parser.add_argument(
        "instance_id",
        help="EC2 instance ID to run command on"
    )
    ssm_run_parser.add_argument(
        "--command", "-c",
        required=True,
        help="Command to execute on the instance"
    )
    ssm_run_parser.add_argument(
        "--region",
        help="AWS region (uses default if not specified)"
    )
    ssm_run_parser.add_argument(
        "--timeout",
        type=int,
        default=60,
        help="Command timeout in seconds (default: 60)"
    )
    ssm_run_parser.add_argument(
        "--json",
        action="store_true",
        help="Output results as JSON"
    )


    # Bridge command group (OpenClaw-compatible interface)
    bridge_parser = subparsers.add_parser(
        "bridge",
        help="OpenClaw-compatible bridge interface (JSON-only output)"
    )
    bridge_subparsers = bridge_parser.add_subparsers(dest="bridge_subcommand", help="Bridge commands")

    # Bridge status subcommand
    bridge_status_parser = bridge_subparsers.add_parser(
        "status",
        help="Get combined status: doctor + service + latest_receipt"
    )

    # Bridge night-run subcommand
    bridge_nightrun_parser = bridge_subparsers.add_parser(
        "night-run",
        help="Trigger test run and return summary with triage"
    )

    # Bridge logs subcommand
    bridge_logs_parser = bridge_subparsers.add_parser(
        "logs",
        help="Fetch journal logs for openbot-run.service"
    )
    bridge_logs_parser.add_argument(
        "--lines", "-n",
        type=int,
        default=120,
        help="Number of lines to fetch (default: 120, max: 1000)"
    )

    # Bridge service subcommand
    bridge_service_parser = bridge_subparsers.add_parser(
        "service",
        help="Control openbot-run.service (status or restart only)"
    )
    bridge_service_parser.add_argument(
        "action",
        choices=["status", "restart"],
        help="Action to perform"
    )

    args = parser.parse_args()

    if args.subcommand is None:
        parser.print_help()
        return 1

    if args.subcommand == "doctor":
        return cmd_doctor(args)
    elif args.subcommand == "run":
        return cmd_run(args)
    elif args.subcommand == "ssm":
        if args.ssm_subcommand is None:
            ssm_parser.print_help()
            return 1
        elif args.ssm_subcommand == "verify":
            return cmd_ssm_verify(args)
        elif args.ssm_subcommand == "connect":
            return cmd_ssm_connect(args)
        elif args.ssm_subcommand == "run":
            return cmd_ssm_run(args)
        else:
            ssm_parser.print_help()
            return 1
    elif args.subcommand == "bridge":
        from openbot.bridge.commands import cmd_status, cmd_night_run, cmd_logs, cmd_service
        if args.bridge_subcommand is None:
            bridge_parser.print_help()
            return 1

            return cmd_status(args)
        elif args.bridge_subcommand == "night-run":
            return cmd_night_run(args)
        elif args.bridge_subcommand == "logs":
            return cmd_logs(args)
        elif args.bridge_subcommand == "service":
            return cmd_service(args)
        else:
            bridge_parser.print_help()
            return 1
    else:
        parser.print_help()
        return 1


if __name__ == "__main__":
    sys.exit(main())

