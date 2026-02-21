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


def check_aws_cli() -> Tuple[bool, str]:
    """
    Check if AWS CLI is installed and accessible.

    Returns: (is_available, version_or_error)
    """
    aws_path = find_binary("aws")
    if not aws_path:
        return False, "AWS CLI not found in PATH"

    exit_code, stdout, stderr = run_command("aws --version", timeout=10)
    if exit_code != 0:
        return False, f"AWS CLI check failed: {stderr}"

    return True, stdout.strip()


def check_ssm_plugin() -> Tuple[bool, str]:
    """
    Check if Session Manager plugin is installed.

    Returns: (is_available, version_or_error)
    """
    plugin_path = find_binary("session-manager-plugin")
    if not plugin_path:
        return False, "Session Manager plugin not found in PATH"

    exit_code, stdout, stderr = run_command("session-manager-plugin --version", timeout=10)
    if exit_code != 0:
        # Plugin might output version to stderr or have non-zero exit
        version = stdout.strip() or stderr.strip()
        if version:
            return True, version
        return False, "Session Manager plugin check failed"

    return True, stdout.strip()


def ssm_describe_instance(instance_id: str, region: Optional[str] = None) -> Tuple[bool, Dict[str, Any]]:
    """
    Get SSM instance information.

    Returns: (success, instance_info_or_error)
    """
    cmd = f"aws ssm describe-instance-information --filters Key=InstanceIds,Values={instance_id} --output json"
    if region:
        cmd += f" --region {region}"

    exit_code, stdout, stderr = run_command(cmd, timeout=30)
    if exit_code != 0:
        return False, {"error": stderr.strip() or "Failed to describe instance"}

    try:
        data = json.loads(stdout)
        instances = data.get("InstanceInformationList", [])
        if not instances:
            return False, {"error": f"Instance {instance_id} not found in SSM"}
        return True, instances[0]
    except json.JSONDecodeError as e:
        return False, {"error": f"Failed to parse response: {e}"}


def ssm_send_command(
    instance_id: str,
    command: str,
    region: Optional[str] = None,
    timeout: int = 60
) -> Tuple[bool, Dict[str, Any]]:
    """
    Send a command to an instance via SSM Run Command.

    Returns: (success, result_dict)
    """
    # Escape the command for shell
    escaped_command = command.replace('"', '\\"')

    cmd = (
        f'aws ssm send-command '
        f'--instance-ids {instance_id} '
        f'--document-name "AWS-RunShellScript" '
        f'--parameters commands="{escaped_command}" '
        f'--output json'
    )
    if region:
        cmd += f" --region {region}"

    exit_code, stdout, stderr = run_command(cmd, timeout=30)
    if exit_code != 0:
        return False, {"error": stderr.strip() or "Failed to send command"}

    try:
        data = json.loads(stdout)
        command_id = data.get("Command", {}).get("CommandId")
        if not command_id:
            return False, {"error": "No CommandId in response"}

        # Wait for command to complete and get output
        return ssm_get_command_output(instance_id, command_id, region, timeout)
    except json.JSONDecodeError as e:
        return False, {"error": f"Failed to parse response: {e}"}


def ssm_get_command_output(
    instance_id: str,
    command_id: str,
    region: Optional[str] = None,
    timeout: int = 60
) -> Tuple[bool, Dict[str, Any]]:
    """
    Wait for SSM command to complete and get output.

    Returns: (success, result_dict)
    """
    import time

    cmd = (
        f"aws ssm get-command-invocation "
        f"--command-id {command_id} "
        f"--instance-id {instance_id} "
        f"--output json"
    )
    if region:
        cmd += f" --region {region}"

    start_time = time.time()
    while time.time() - start_time < timeout:
        exit_code, stdout, stderr = run_command(cmd, timeout=30)

        if exit_code != 0:
            # Command might not be ready yet
            if "InvocationDoesNotExist" in stderr:
                time.sleep(2)
                continue
            return False, {"error": stderr.strip() or "Failed to get command output"}

        try:
            data = json.loads(stdout)
            status = data.get("Status", "")

            if status in ("Success", "Failed", "Cancelled", "TimedOut"):
                return status == "Success", {
                    "status": status,
                    "exit_code": data.get("ResponseCode", -1),
                    "stdout": data.get("StandardOutputContent", ""),
                    "stderr": data.get("StandardErrorContent", ""),
                    "command_id": command_id
                }

            # Still in progress
            time.sleep(2)

        except json.JSONDecodeError as e:
            return False, {"error": f"Failed to parse response: {e}"}

    return False, {"error": f"Command timed out after {timeout}s", "command_id": command_id}


def ssm_start_session_command(instance_id: str, region: Optional[str] = None) -> str:
    """
    Generate the AWS CLI command to start an SSM session.

    Returns the command string (user must run it interactively).
    """
    cmd = f"aws ssm start-session --target {instance_id}"
    if region:
        cmd += f" --region {region}"
    return cmd


def check_stale_workdirs(workdir: Path, max_age_hours: int = 2) -> List[Dict[str, Any]]:
    """
    Find workdirs older than max_age_hours.
    Stale workdirs indicate hung or abandoned runs.
    Returns list of stale workdir info dicts.
    """
    stale = []
    try:
        if not workdir.exists():
            return stale
        import time
        now = time.time()
        cutoff = now - (max_age_hours * 3600)
        for entry in workdir.iterdir():
            if entry.is_dir() and entry.name != ".gitkeep":
                try:
                    mtime = entry.stat().st_mtime
                    if mtime < cutoff:
                        age_hours = round((now - mtime) / 3600, 1)
                        stale.append({
                            "path": str(entry),
                            "age_hours": age_hours,
                        })
                except OSError:
                    pass
    except (OSError, PermissionError):
        pass
    return stale


def check_disk_space(path: Path) -> Optional[Dict[str, Any]]:
    """
    Check available disk space at path.
    Returns dict with total_mb, free_mb, used_percent, or None on error.
    """
    try:
        stat = shutil.disk_usage(str(path))
        return {
            "total_mb": round(stat.total / (1024 * 1024)),
            "free_mb": round(stat.free / (1024 * 1024)),
            "used_percent": round((stat.used / stat.total) * 100, 1),
        }
    except (OSError, PermissionError):
        return None


def check_openbot_processes() -> List[Dict[str, Any]]:
    """
    Find running openbot processes (potential zombies or hung runs).
    Returns list of process info dicts.
    """
    processes = []
    try:
        exit_code, stdout, stderr = run_command(
            "ps aux | grep -E 'openbot\\.(cli|runner)' | grep -v grep",
            timeout=10,
        )
        if exit_code == 0 and stdout.strip():
            for line in stdout.strip().split("\n"):
                parts = line.split(None, 10)
                if len(parts) >= 11:
                    processes.append({
                        "user": parts[0],
                        "pid": parts[1],
                        "cpu": parts[2],
                        "mem": parts[3],
                        "command": parts[10],
                    })
    except Exception:
        pass
    return processes


def check_systemd_service(service_name: str = "openbot-run.service") -> Optional[Dict[str, str]]:
    """
    Check systemd service status.
    Returns dict with active_state, sub_state, or None if systemd unavailable.
    """
    try:
        exit_code, stdout, stderr = run_command(
            f"systemctl show {service_name} --property=ActiveState,SubState,Result --no-pager",
            timeout=10,
        )
        if exit_code != 0:
            return None
        info = {}
        for line in stdout.strip().split("\n"):
            if "=" in line:
                k, v = line.split("=", 1)
                info[k.strip()] = v.strip()
        return info
    except Exception:
        return None


# ── OpenClaw-specific diagnostics ──────────────────────────────────────────

OPENCLAW_CONFIG_PATH = Path("/root/.openclaw/openclaw.json")
OPENCLAW_MEMORY_DIR = Path("/root/.openclaw/memory")
OPENCLAW_SESSIONS_DIR = Path("/tmp/openclaw/sessions")
OPENCLAW_GATEWAY_PORT = 18789
OPENCLAW_MEMORY_FILES = [
    "MEMORY.md",
    "current-work.json",
    "taskboard.json",
    "lessons.json",
    "decisions.md",
]


def check_openclaw_config() -> Dict[str, Any]:
    """
    Check OpenClaw config file validity.

    Returns dict with found, valid_json, writable status.
    Does not raise — safe to call in any environment.
    """
    result: Dict[str, Any] = {
        "path": str(OPENCLAW_CONFIG_PATH),
        "found": False,
        "valid_json": False,
        "writable": False,
    }
    try:
        if not OPENCLAW_CONFIG_PATH.exists():
            return result
        result["found"] = True
        result["writable"] = os.access(str(OPENCLAW_CONFIG_PATH), os.W_OK)
        with open(OPENCLAW_CONFIG_PATH, "r") as f:
            json.load(f)
        result["valid_json"] = True
    except (OSError, PermissionError):
        pass
    except json.JSONDecodeError:
        pass
    return result


def check_openclaw_gateway() -> Dict[str, Any]:
    """
    Check OpenClaw gateway service and port.

    Uses Python socket instead of ss/netstat — no external binary required.
    Returns dict with port_listening and optional service status.
    """
    import socket as _socket

    result: Dict[str, Any] = {
        "port": OPENCLAW_GATEWAY_PORT,
        "port_listening": False,
        "service": None,
    }

    # Pure-Python port check — works even without ss/netstat
    try:
        with _socket.create_connection(("127.0.0.1", OPENCLAW_GATEWAY_PORT), timeout=2):
            result["port_listening"] = True
    except (OSError, _socket.error):
        result["port_listening"] = False

    # Systemd service check (gracefully returns None on non-systemd hosts)
    svc = check_systemd_service("openclaw-gateway")
    if svc:
        result["service"] = svc

    return result


def check_openclaw_memory() -> Dict[str, Any]:
    """
    Check OpenClaw memory system files.

    Returns dict with per-file presence and missing count.
    """
    result: Dict[str, Any] = {
        "memory_dir": str(OPENCLAW_MEMORY_DIR),
        "memory_dir_exists": safe_path_exists(OPENCLAW_MEMORY_DIR),
        "files": {},
        "missing_count": 0,
        "daily_notes": None,
    }

    for fname in OPENCLAW_MEMORY_FILES:
        exists = safe_path_exists(OPENCLAW_MEMORY_DIR / fname)
        result["files"][fname] = exists
        if not exists:
            result["missing_count"] += 1

    daily_dir = OPENCLAW_MEMORY_DIR / "daily"
    if safe_path_exists(daily_dir):
        try:
            result["daily_notes"] = len(list(daily_dir.iterdir()))
        except (OSError, PermissionError):
            result["daily_notes"] = 0

    return result


def check_openclaw_sessions() -> Dict[str, Any]:
    """
    Check OpenClaw session count (bloat detection).

    Returns dict with count and bloated flag (>40 sessions).
    """
    result: Dict[str, Any] = {
        "sessions_dir": str(OPENCLAW_SESSIONS_DIR),
        "dir_exists": False,
        "count": 0,
        "bloated": False,
    }
    try:
        if not OPENCLAW_SESSIONS_DIR.exists():
            return result
        result["dir_exists"] = True
        entries = list(OPENCLAW_SESSIONS_DIR.iterdir())
        result["count"] = len(entries)
        result["bloated"] = len(entries) > 40
    except (OSError, PermissionError):
        pass
    return result


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
