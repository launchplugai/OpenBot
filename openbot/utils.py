"""
Utility functions for Openbot runtime.
"""

import datetime
import json
import os
import shutil
import subprocess
import sys
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


def get_timestamp() -> str:
    """Return current UTC timestamp in ISO8601 format."""
    return datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")


def generate_run_id() -> str:
    """Generate a unique run ID (UUID4)."""
    return str(uuid.uuid4())


def ensure_dir(path: Path) -> bool:
    """Ensure directory exists. Returns True if successful."""
    try:
        path.mkdir(parents=True, exist_ok=True)
        return True
    except OSError:
        return False


def is_writable(path: Path) -> bool:
    """Check if a path is writable. Never raises exceptions."""
    try:
        if path.exists():
            return os.access(path, os.W_OK)
        # Check if we can create it
        path.mkdir(parents=True, exist_ok=True)
        return os.access(path, os.W_OK)
    except (OSError, PermissionError):
        return False


def safe_path_exists(path: Path) -> bool:
    """Check if path exists without raising PermissionError."""
    try:
        return path.exists()
    except (OSError, PermissionError):
        return False


def find_binary(name: str) -> Optional[str]:
    """Find a binary in PATH. Returns path or None."""
    return shutil.which(name)


def run_command(
    command: str,
    cwd: Optional[Path] = None,
    timeout: int = 300,
    env: Optional[Dict[str, str]] = None
) -> Tuple[int, str, str]:
    """
    Run a shell command and capture output.

    Returns: (exit_code, stdout, stderr)
    """
    try:
        result = subprocess.run(
            command,
            shell=True,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env or os.environ.copy()
        )
        return result.returncode, result.stdout, result.stderr
    except subprocess.TimeoutExpired:
        return -1, "", f"Command timed out after {timeout}s"
    except Exception as e:
        return -1, "", str(e)


def load_json(path: Path) -> Optional[Dict[str, Any]]:
    """Load JSON from file. Returns None on error."""
    try:
        with open(path, "r") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return None


def save_json(path: Path, data: Dict[str, Any], indent: int = 2) -> bool:
    """Save data as JSON to file. Returns True on success."""
    try:
        ensure_dir(path.parent)
        with open(path, "w") as f:
            json.dump(data, f, indent=indent)
        return True
    except OSError:
        return False


def truncate_string(s: str, max_len: int = 500) -> str:
    """Truncate string to max length."""
    if len(s) <= max_len:
        return s
    return s[:max_len]


class Logger:
    """Simple logger that writes to file and optionally stdout."""

    def __init__(self, log_path: Path, also_stdout: bool = True):
        self.log_path = log_path
        self.also_stdout = also_stdout
        self._file = None

    def __enter__(self):
        ensure_dir(self.log_path.parent)
        self._file = open(self.log_path, "w")
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self._file:
            self._file.close()
        return False

    def log(self, message: str, level: str = "INFO"):
        """Log a message with timestamp."""
        ts = get_timestamp()
        line = f"[{ts}] [{level}] {message}"
        if self._file:
            self._file.write(line + "\n")
            self._file.flush()
        if self.also_stdout:
            print(line, file=sys.stderr if level == "ERROR" else sys.stdout)

    def info(self, message: str):
        self.log(message, "INFO")

    def error(self, message: str):
        self.log(message, "ERROR")

    def warn(self, message: str):
        self.log(message, "WARN")

    def command(self, cmd: str, exit_code: int, stdout: str, stderr: str):
        """Log command execution details."""
        self.log(f"COMMAND: {cmd}", "CMD")
        self.log(f"EXIT_CODE: {exit_code}", "CMD")
        if stdout.strip():
            for line in stdout.strip().split("\n"):
                self.log(f"STDOUT: {line}", "CMD")
        if stderr.strip():
            for line in stderr.strip().split("\n"):
                self.log(f"STDERR: {line}", "CMD")
