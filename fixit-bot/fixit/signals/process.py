"""Process signal — observe running processes."""

from __future__ import annotations

import subprocess
from typing import Any

from fixit.signals.base import Signal


class ProcessSignal(Signal):
    """Watch a named process for health signals."""

    name = "process"

    def __init__(self, process_name: str):
        self.process_name = process_name

    def collect(self) -> dict[str, Any]:
        result = {"process": self.process_name, "running": False}

        try:
            ps = subprocess.run(
                ["pgrep", "-af", self.process_name],
                capture_output=True, text=True, timeout=5,
            )
            lines = [l for l in ps.stdout.strip().split("\n") if l]
            result["running"] = len(lines) > 0
            result["pid_count"] = len(lines)
            result["pids"] = lines[:5]  # cap at 5
        except (subprocess.TimeoutExpired, FileNotFoundError):
            result["error"] = "pgrep unavailable"

        # Memory usage via ps
        try:
            ps = subprocess.run(
                ["ps", "-C", self.process_name, "-o", "rss=,vsz=,%mem=,%cpu="],
                capture_output=True, text=True, timeout=5,
            )
            if ps.stdout.strip():
                parts = ps.stdout.strip().split()
                if len(parts) >= 4:
                    result["rss_kb"] = int(parts[0])
                    result["vsz_kb"] = int(parts[1])
                    result["mem_pct"] = float(parts[2])
                    result["cpu_pct"] = float(parts[3])
        except (subprocess.TimeoutExpired, FileNotFoundError, ValueError):
            pass

        # Port listening
        try:
            ss = subprocess.run(
                ["ss", "-tlnp"], capture_output=True, text=True, timeout=5,
            )
            ports = []
            for line in ss.stdout.split("\n"):
                if self.process_name in line:
                    # Extract port from LISTEN line
                    parts = line.split()
                    for part in parts:
                        if ":" in part:
                            port = part.rsplit(":", 1)[-1]
                            if port.isdigit():
                                ports.append(int(port))
                                break
            result["listening_ports"] = ports
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass

        return result

    def describe(self) -> str:
        return f"Process: {self.process_name}"
