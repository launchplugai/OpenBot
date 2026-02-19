"""Git signal — observe repo state, churn, and drift."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from fixit.signals.base import Signal


class GitSignal(Signal):
    """Watch a git repo for churn, uncommitted changes, and branch state."""

    name = "git"

    def __init__(self, path: str):
        self.path = Path(path)

    def _run(self, *args: str) -> str:
        try:
            r = subprocess.run(
                ["git", "-C", str(self.path)] + list(args),
                capture_output=True, text=True, timeout=10,
            )
            return r.stdout.strip()
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return ""

    def collect(self) -> dict[str, Any]:
        if not (self.path / ".git").exists():
            return {"error": f"{self.path} is not a git repo"}

        # Current state
        branch = self._run("rev-parse", "--abbrev-ref", "HEAD")
        status_lines = self._run("status", "--porcelain").split("\n")
        status_lines = [l for l in status_lines if l]

        dirty = len(status_lines)
        untracked = len([l for l in status_lines if l.startswith("?")])
        modified = len([l for l in status_lines if l.startswith(" M") or l.startswith("M")])

        # Recent churn (files changed most in last 20 commits)
        log = self._run("log", "--oneline", "-20", "--format=%H")
        commit_count = len(log.split("\n")) if log else 0

        # Most-changed files (last 20 commits)
        churn_raw = self._run("log", "--oneline", "-20", "--name-only", "--format=")
        churn_files: dict[str, int] = {}
        for line in churn_raw.split("\n"):
            line = line.strip()
            if line:
                churn_files[line] = churn_files.get(line, 0) + 1
        hot_files = sorted(churn_files.items(), key=lambda x: -x[1])[:10]

        return {
            "path": str(self.path),
            "branch": branch,
            "dirty_files": dirty,
            "untracked": untracked,
            "modified": modified,
            "recent_commits": commit_count,
            "hot_files": [{"file": f, "changes": c} for f, c in hot_files],
        }

    def describe(self) -> str:
        return f"Git repo: {self.path}"
