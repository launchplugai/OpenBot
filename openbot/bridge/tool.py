"""
Bridge Tool - Safe interface to OpenBot operations.

All methods:
- Check allowlist before execution
- Sanitize outputs
- Cap output sizes
- Return JSON-serializable dicts
"""

import json
import subprocess
from pathlib import Path
from typing import Dict, Any, Optional, List
from datetime import datetime

from .hooks import (
    check_allowlist,
    sanitize_output,
    cap_size,
    is_path_forbidden,
    ALLOWLIST,
)

# Paths
OPENBOT_BIN = "/usr/local/bin/openbot"
RECEIPTS_DIR = Path("/var/lib/openbot/receipts")
SERVICE_NAME = "openbot-run.service"
CONFIG_PATH = "/etc/openbot/config.yaml"


class BridgeTool:
    """Safe interface to OpenBot operations."""
    
    def __init__(self):
        self.openbot_bin = OPENBOT_BIN
        self.receipts_dir = RECEIPTS_DIR
        self.service_name = SERVICE_NAME
    
    def _run_command(
        self, 
        cmd: List[str], 
        timeout: int = 120,
        capture_output: bool = True
    ) -> Dict[str, Any]:
        """Run a command and return sanitized result."""
        try:
            result = subprocess.run(
                cmd,
                capture_output=capture_output,
                text=True,
                timeout=timeout,
            )
            stdout, truncated_out = cap_size(sanitize_output(result.stdout or ""))
            stderr, truncated_err = cap_size(sanitize_output(result.stderr or ""))
            
            return {
                "success": result.returncode == 0,
                "returncode": result.returncode,
                "stdout": stdout,
                "stderr": stderr,
                "truncated": truncated_out or truncated_err,
            }
        except subprocess.TimeoutExpired:
            return {
                "success": False,
                "returncode": -1,
                "stdout": "",
                "stderr": "Command timed out",
                "truncated": False,
            }
        except Exception as e:
            return {
                "success": False,
                "returncode": -1,
                "stdout": "",
                "stderr": sanitize_output(str(e)),
                "truncated": False,
            }
    
    def doctor(self) -> Dict[str, Any]:
        """Run OpenBot health check."""
        error = check_allowlist("doctor")
        if error:
            return error
        
        result = self._run_command([self.openbot_bin, "doctor"])
        
        # Try to parse JSON output
        doctor_data = None
        if result["success"] and result["stdout"]:
            try:
                # Doctor outputs JSON to stdout
                doctor_data = json.loads(result["stdout"].split("\n\n")[0])
            except (json.JSONDecodeError, IndexError):
                pass
        
        return {
            "ok": result["success"],
            "action": "doctor",
            "data": doctor_data,
            "raw": result if not doctor_data else None,
        }
    
    def run(self) -> Dict[str, Any]:
        """
        Trigger a test run.
        
        Uses systemctl restart on the openbot-run.service, which is
        a oneshot service that runs tests and exits.
        """
        error = check_allowlist("run")
        if error:
            return error
        
        # Restart the service to trigger a run
        result = self._run_command(
            ["sudo", "systemctl", "restart", self.service_name],
            timeout=300,  # 5 minutes max
        )
        
        if not result["success"]:
            return {
                "ok": False,
                "action": "run",
                "error": {
                    "type": "execution_failed",
                    "message": result["stderr"] or "Failed to restart service",
                },
            }
        
        # Wait for service to complete (poll status)
        import time
        max_wait = 180  # 3 minutes
        poll_interval = 2
        waited = 0
        
        while waited < max_wait:
            status = self._run_command(["systemctl", "is-active", self.service_name])
            state = status["stdout"].strip()
            
            if state in ("inactive", "failed"):
                break
            
            time.sleep(poll_interval)
            waited += poll_interval
        
        # Get the latest receipt
        receipt = self.latest_receipt()
        
        return {
            "ok": True,
            "action": "run",
            "service_state": state,
            "waited_seconds": waited,
            "latest_receipt": receipt.get("data") if receipt.get("ok") else None,
        }
    
    def service(self, action: str) -> Dict[str, Any]:
        """
        Control the openbot-run.service.
        
        Only status and restart are allowed.
        """
        error = check_allowlist("service", action=action, service=self.service_name)
        if error:
            return error
        
        if action == "status":
            # Get detailed status
            result = self._run_command([
                "systemctl", "status", self.service_name, "--no-pager"
            ])
            
            # Also get is-active for simple state
            is_active = self._run_command(["systemctl", "is-active", self.service_name])
            
            return {
                "ok": True,
                "action": "service",
                "service": self.service_name,
                "state": is_active["stdout"].strip(),
                "details": result["stdout"],
            }
        
        elif action == "restart":
            result = self._run_command([
                "sudo", "systemctl", "restart", self.service_name
            ])
            
            return {
                "ok": result["success"],
                "action": "service",
                "service": self.service_name,
                "operation": "restart",
                "error": result["stderr"] if not result["success"] else None,
            }
        
        # Should not reach here due to allowlist check
        return {
            "ok": False,
            "error": {"type": "forbidden", "message": f"Unknown action: {action}"}
        }
    
    def logs(self, lines: int = 120) -> Dict[str, Any]:
        """
        Fetch journal logs for openbot-run.service.
        """
        error = check_allowlist("logs", service=self.service_name, lines=lines)
        if error:
            return error
        
        result = self._run_command([
            "journalctl",
            "-u", self.service_name,
            "-n", str(lines),
            "--no-pager",
        ])
        
        return {
            "ok": True,
            "action": "logs",
            "service": self.service_name,
            "lines_requested": lines,
            "logs": result["stdout"],
            "truncated": result["truncated"],
        }
    
    def latest_receipt(self) -> Dict[str, Any]:
        """
        Get the most recent receipt from /var/lib/openbot/receipts.
        """
        error = check_allowlist("latest_receipt")
        if error:
            return error
        
        try:
            if not self.receipts_dir.exists():
                return {
                    "ok": False,
                    "action": "latest_receipt",
                    "error": {
                        "type": "not_found",
                        "message": f"Receipts directory not found: {self.receipts_dir}",
                    },
                }
            
            # Find newest .json file by mtime
            receipts = list(self.receipts_dir.glob("*.json"))
            if not receipts:
                return {
                    "ok": False,
                    "action": "latest_receipt",
                    "error": {
                        "type": "not_found",
                        "message": "No receipts found",
                    },
                }
            
            latest = max(receipts, key=lambda p: p.stat().st_mtime)
            
            with open(latest, "r") as f:
                data = json.load(f)
            
            # Return safe subset of fields
            safe_data = {
                "receipt_version": data.get("receipt_version"),
                "timestamp": data.get("timestamp"),
                "run_id": data.get("run_id"),
                "target_repo": data.get("target_repo"),
                "target_branch": data.get("target_branch"),
                "commit_sha": data.get("commit_sha"),
                "overall_status": data.get("overall_status"),
                "errors": data.get("errors", []),
                "policies_loaded": data.get("policies_loaded", []),
                "test": {
                    "exit_code": data.get("test", {}).get("exit_code"),
                    "summary": data.get("test", {}).get("summary"),
                    "passed": data.get("test", {}).get("passed"),
                    "failed": data.get("test", {}).get("failed", 0),
                    "runtime_seconds": data.get("test", {}).get("runtime_seconds"),
                },
                "path": str(latest),
            }
            
            return {
                "ok": True,
                "action": "latest_receipt",
                "data": safe_data,
            }
            
        except Exception as e:
            return {
                "ok": False,
                "action": "latest_receipt",
                "error": {
                    "type": "read_error",
                    "message": sanitize_output(str(e)),
                },
            }
