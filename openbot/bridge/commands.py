"""
Bridge Commands - CLI command handlers.

Each function handles a bridge subcommand and returns an exit code.
All output is JSON-only (no prose).
"""

import json
import sys
from typing import Any

from .tool import BridgeTool
from .triage import local_triage


def _output_json(data: Any, exit_code: int = 0) -> int:
    """Print JSON and return exit code."""
    print(json.dumps(data, indent=2))
    return exit_code


def cmd_status(args) -> int:
    """
    Bridge status command.
    
    Combines: doctor + service(status) + latest_receipt
    """
    tool = BridgeTool()
    
    result = {
        "ok": True,
        "action": "status",
        "doctor": None,
        "service": None,
        "latest_receipt": None,
    }
    
    # Run doctor
    doctor_result = tool.doctor()
    result["doctor"] = doctor_result
    if not doctor_result.get("ok"):
        result["ok"] = False
    
    # Get service status
    service_result = tool.service("status")
    result["service"] = service_result
    
    # Get latest receipt
    receipt_result = tool.latest_receipt()
    result["latest_receipt"] = receipt_result
    
    # Add triage if receipt available
    if receipt_result.get("ok") and receipt_result.get("data"):
        result["triage"] = local_triage(receipt_result["data"])
    
    return _output_json(result, 0 if result["ok"] else 1)


def cmd_night_run(args) -> int:
    """
    Bridge night-run command.
    
    Triggers a test run and returns summary with triage.
    """
    tool = BridgeTool()
    
    # Trigger run
    run_result = tool.run()
    
    result = {
        "ok": run_result.get("ok", False),
        "action": "night-run",
        "service": {
            "state": run_result.get("service_state"),
            "waited_seconds": run_result.get("waited_seconds"),
        },
        "latest_receipt": run_result.get("latest_receipt"),
        "triage": None,
        "error": run_result.get("error"),
    }
    
    # Add triage
    if run_result.get("latest_receipt"):
        result["triage"] = local_triage(run_result["latest_receipt"])
    else:
        result["triage"] = local_triage(None)
    
    return _output_json(result, 0 if result["ok"] else 1)


def cmd_logs(args) -> int:
    """
    Bridge logs command.
    
    Fetches last N lines of journal logs for openbot-run.service.
    """
    tool = BridgeTool()
    
    lines = getattr(args, "lines", 120)
    result = tool.logs(lines=lines)
    
    return _output_json(result, 0 if result.get("ok") else 1)


def cmd_service(args) -> int:
    """
    Bridge service command.
    
    Controls openbot-run.service (status or restart only).
    """
    tool = BridgeTool()
    
    action = getattr(args, "action", "status")
    result = tool.service(action=action)
    
    return _output_json(result, 0 if result.get("ok") else 1)
