"""
Receipt creation and validation for Openbot.

Receipts are the authoritative record of every run.
"""

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from openbot.utils import ensure_dir, generate_run_id, get_timestamp, save_json


class ReceiptValidationError(Exception):
    """Raised when receipt fails schema validation."""
    pass


def validate_receipt(receipt: Dict[str, Any], schema: Dict[str, Any]) -> List[str]:
    """
    Validate receipt against JSON schema.
    Returns list of validation errors (empty if valid).

    Note: This is a simplified validator that checks our specific schema.
    For full JSON Schema validation, jsonschema library would be needed.
    """
    errors = []

    # Check required fields
    required = schema.get("required", [])
    for field in required:
        if field not in receipt:
            errors.append(f"Missing required field: {field}")

    # Validate specific fields based on our schema
    props = schema.get("properties", {})

    # receipt_version
    if "receipt_version" in receipt:
        expected = props.get("receipt_version", {}).get("const")
        if expected and receipt["receipt_version"] != expected:
            errors.append(f"receipt_version must be '{expected}'")

    # run_id (UUID format)
    if "run_id" in receipt:
        uuid_pattern = r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
        if not re.match(uuid_pattern, receipt["run_id"]):
            errors.append("run_id must be a valid UUID")

    # commit_sha (40 hex chars)
    if "commit_sha" in receipt:
        sha_pattern = r"^[0-9a-f]{40}$"
        if not re.match(sha_pattern, receipt["commit_sha"]):
            errors.append("commit_sha must be a 40-character hex string")

    # overall_status (enum)
    if "overall_status" in receipt:
        allowed = props.get("overall_status", {}).get("enum", [])
        if allowed and receipt["overall_status"] not in allowed:
            errors.append(f"overall_status must be one of: {allowed}")

    # test object
    if "test" in receipt:
        test = receipt["test"]
        if not isinstance(test, dict):
            errors.append("test must be an object")
        else:
            test_required = ["command", "exit_code", "summary", "log_path"]
            for field in test_required:
                if field not in test:
                    errors.append(f"test.{field} is required")

            if "summary" in test:
                allowed_summaries = ["passed", "failed"]
                if test["summary"] not in allowed_summaries:
                    errors.append(f"test.summary must be one of: {allowed_summaries}")

            if "exit_code" in test and not isinstance(test["exit_code"], int):
                errors.append("test.exit_code must be an integer")

    # health object (nullable)
    if "health" in receipt and receipt["health"] is not None:
        health = receipt["health"]
        if not isinstance(health, dict):
            errors.append("health must be an object or null")
        else:
            health_required = ["url", "status_code", "ok"]
            for field in health_required:
                if field not in health:
                    errors.append(f"health.{field} is required")

            if "ok" in health and not isinstance(health["ok"], bool):
                errors.append("health.ok must be a boolean")

    # errors array
    if "errors" in receipt:
        if not isinstance(receipt["errors"], list):
            errors.append("errors must be an array")
        else:
            for i, err in enumerate(receipt["errors"]):
                if not isinstance(err, str):
                    errors.append(f"errors[{i}] must be a string")

    return errors


class Receipt:
    """Builder for Openbot run receipts."""

    def __init__(self):
        self.run_id = generate_run_id()
        self.timestamp: Optional[str] = None
        self.target_repo: str = ""
        self.target_branch: str = ""
        self.commit_sha: str = ""
        self.test_command: str = ""
        self.test_exit_code: int = -1
        self.test_summary: str = "failed"
        self.test_log_path: str = ""
        self.test_passed: Optional[int] = None
        self.test_failed: Optional[int] = None
        self.test_runtime_seconds: Optional[float] = None
        self.setup_command: Optional[str] = None
        self.health_url: Optional[str] = None
        self.health_status_code: Optional[int] = None
        self.health_body_snippet: Optional[str] = None
        self.health_ok: Optional[bool] = None
        self.health_log_path: Optional[str] = None
        self.overall_status: str = "FAILED"
        self.errors: List[str] = []
        self.policies_loaded: List[str] = []

    def set_target(self, repo: str, branch: str, commit_sha: str):
        """Set target repository details."""
        self.target_repo = repo
        self.target_branch = branch
        self.commit_sha = commit_sha

    def set_test_result(
        self,
        command: str,
        exit_code: int,
        log_path: str,
        passed: Optional[int] = None,
        failed: Optional[int] = None,
        runtime_seconds: Optional[float] = None,
        setup_command: Optional[str] = None
    ):
        """Set test execution results."""
        self.test_command = command
        self.test_exit_code = exit_code
        self.test_summary = "passed" if exit_code == 0 else "failed"
        self.test_log_path = log_path
        self.test_passed = passed
        self.test_failed = failed
        self.test_runtime_seconds = runtime_seconds
        self.setup_command = setup_command

    def set_health_result(
        self,
        url: str,
        status_code: Optional[int],
        body_snippet: Optional[str],
        ok: bool,
        log_path: Optional[str] = None
    ):
        """Set health check results."""
        self.health_url = url
        self.health_status_code = status_code
        self.health_body_snippet = body_snippet
        self.health_ok = ok
        self.health_log_path = log_path

    def add_error(self, error: str):
        """Add an error message."""
        self.errors.append(error)
        self.overall_status = "FAILED"

    def set_policies_loaded(self, policies: List[str]):
        """Set list of loaded policies."""
        self.policies_loaded = policies

    def finalize(self) -> Dict[str, Any]:
        """
        Finalize and return the receipt as a dictionary.
        Sets timestamp and calculates overall status.
        """
        self.timestamp = get_timestamp()

        # Calculate overall status
        if not self.errors and self.test_exit_code == 0:
            self.overall_status = "SUCCESS"
        else:
            self.overall_status = "FAILED"

        # Build test object with optional fields
        test_obj = {
            "command": self.test_command,
            "exit_code": self.test_exit_code,
            "summary": self.test_summary,
            "log_path": self.test_log_path
        }

        # Add optional test fields if present
        if self.test_passed is not None:
            test_obj["passed"] = self.test_passed
        if self.test_failed is not None:
            test_obj["failed"] = self.test_failed
        if self.test_runtime_seconds is not None:
            test_obj["runtime_seconds"] = self.test_runtime_seconds
        if self.setup_command is not None:
            test_obj["setup_command"] = self.setup_command

        receipt = {
            "receipt_version": "v1",
            "timestamp": self.timestamp,
            "run_id": self.run_id,
            "target_repo": self.target_repo,
            "target_branch": self.target_branch,
            "commit_sha": self.commit_sha,
            "test": test_obj,
            "health": None,
            "overall_status": self.overall_status,
            "errors": self.errors,
            "policies_loaded": self.policies_loaded
        }

        # Add health if present
        if self.health_url:
            receipt["health"] = {
                "url": self.health_url,
                "status_code": self.health_status_code,
                "body_snippet": self.health_body_snippet,
                "ok": self.health_ok,
                "log_path": self.health_log_path
            }

        return receipt


class ReceiptWriter:
    """Writes receipts to disk with validation."""

    def __init__(self, receipts_dir: Path, schema: Optional[Dict[str, Any]] = None):
        self.receipts_dir = Path(receipts_dir)
        self.schema = schema
        self.quarantine_dir = self.receipts_dir / "quarantine"

    def write(self, receipt: Dict[str, Any]) -> tuple[bool, str]:
        """
        Write receipt to disk after validation.

        Returns: (success, path_or_error)
        - If validation passes: (True, receipt_path)
        - If validation fails: (False, quarantine_path) - quarantine receipt written
        """
        run_id = receipt.get("run_id", generate_run_id())

        # Validate if schema provided
        if self.schema:
            validation_errors = validate_receipt(receipt, self.schema)
            if validation_errors:
                # Write quarantine receipt
                quarantine_receipt = {
                    "quarantined": True,
                    "quarantine_reason": "Schema validation failed",
                    "validation_errors": validation_errors,
                    "original_receipt": receipt,
                    "timestamp": get_timestamp()
                }
                ensure_dir(self.quarantine_dir)
                quarantine_path = self.quarantine_dir / f"{run_id}_quarantine.json"
                save_json(quarantine_path, quarantine_receipt)
                return False, str(quarantine_path)

        # Write valid receipt
        ensure_dir(self.receipts_dir)
        receipt_path = self.receipts_dir / f"{run_id}.json"
        if save_json(receipt_path, receipt):
            return True, str(receipt_path)
        else:
            return False, "Failed to write receipt to disk"
