"""Category-based signal collectors for the heartbeat.

These are LIGHTWEIGHT. Each collector runs in <2 seconds and produces
a focused signal for one category of concern. The heartbeat picks
which categories to run based on what's changed since last beat.

Categories:
  lint      — comment errors, syntax warnings, type issues
  logs      — recent log anomalies + questions the logs raise
  active    — current git work (uncommitted, recent commits, hot files)
  drift     — config/env changes since last beat
  resource  — disk, memory, sessions (only if trending bad)
"""

from __future__ import annotations

import json
import os
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from fixit.signals.base import Signal


@dataclass
class CategoryResult:
    """Output from a category collector."""
    category: str
    timestamp: float
    data: dict[str, Any]
    changed: bool = False   # True if something changed since last beat


class LintCategory:
    """Collect lint/syntax/comment errors from the codebase.

    Runs the lightest possible checks — no full type-checking.
    Looks for: syntax errors, TODO/FIXME/HACK markers,
    broken JSON configs, dangling imports.
    """

    name = "lint"

    def __init__(self, paths: list[str], extensions: list[str] | None = None):
        self.paths = [Path(p) for p in paths]
        self.extensions = extensions or [".py", ".json", ".yaml", ".yml", ".sh"]

    def collect(self) -> CategoryResult:
        findings: list[dict] = []

        for root_path in self.paths:
            if not root_path.exists():
                continue

            # 1. Check JSON configs for syntax errors
            for json_file in root_path.rglob("*.json"):
                try:
                    json.loads(json_file.read_text())
                except json.JSONDecodeError as e:
                    findings.append({
                        "type": "json_syntax",
                        "file": str(json_file),
                        "error": str(e),
                        "severity": "high",
                    })
                except (OSError, PermissionError):
                    pass

            # 2. Scan for TODO/FIXME/HACK markers (questions the code is asking)
            for ext in self.extensions:
                for src_file in root_path.rglob(f"*{ext}"):
                    try:
                        lines = src_file.read_text(errors="replace").split("\n")
                        for i, line in enumerate(lines, 1):
                            line_upper = line.upper()
                            for marker in ("TODO", "FIXME", "HACK", "XXX", "BUG"):
                                if marker in line_upper:
                                    findings.append({
                                        "type": "marker",
                                        "file": str(src_file),
                                        "line": i,
                                        "marker": marker,
                                        "text": line.strip()[:120],
                                        "severity": "low",
                                    })
                    except (OSError, PermissionError):
                        pass

            # 3. Python syntax check (fast — just compile, don't run)
            for py_file in root_path.rglob("*.py"):
                try:
                    source = py_file.read_text()
                    compile(source, str(py_file), "exec")
                except SyntaxError as e:
                    findings.append({
                        "type": "python_syntax",
                        "file": str(py_file),
                        "line": e.lineno,
                        "error": str(e.msg),
                        "severity": "high",
                    })
                except (OSError, PermissionError):
                    pass

        return CategoryResult(
            category=self.name,
            timestamp=time.time(),
            data={
                "finding_count": len(findings),
                "by_type": _count_by(findings, "type"),
                "by_severity": _count_by(findings, "severity"),
                "findings": findings[:50],  # cap to keep signals small
            },
            changed=len(findings) > 0,
        )


class LogCategory:
    """Collect recent log anomalies and the questions they raise.

    Reads journalctl or log files. Extracts error patterns.
    Crucially: also extracts the QUESTIONS the logs imply.
    "Connection refused" → "Is the target service running?"
    "EPERM" → "Are file permissions correct?"
    """

    name = "logs"

    # Patterns that imply questions
    QUESTION_MAP = {
        "connection refused": "Is the target service running and listening?",
        "eperm": "Are file permissions correct? Is the process running as the right user?",
        "timeout": "Is the target service overloaded or the network path blocked?",
        "out of memory": "Is something leaking memory? Are limits set correctly?",
        "disk full": "Is log rotation configured? Are old files being cleaned?",
        "permission denied": "Is the process running as the right user?",
        "no such file": "Was a file deleted or moved? Is the path hardcoded?",
        "invalid json": "Was a config file hand-edited with a syntax error?",
        "rate limit": "Are we retrying without backoff? Too many concurrent requests?",
        "ssl": "Is a certificate expired or misconfigured?",
        "dns": "Is DNS resolving? Network configuration correct?",
        "segfault": "Memory corruption — is a C extension or native dependency broken?",
    }

    def __init__(self, units: list[str] | None = None, log_files: list[str] | None = None,
                 tail_lines: int = 100):
        self.units = units or []
        self.log_files = [Path(f) for f in (log_files or [])]
        self.tail_lines = tail_lines

    def collect(self) -> CategoryResult:
        log_lines: list[str] = []

        # Collect from systemd journal
        for unit in self.units:
            try:
                r = subprocess.run(
                    ["journalctl", "-u", unit, "--no-pager", "-n", str(self.tail_lines),
                     "--since", "1 hour ago"],
                    capture_output=True, text=True, timeout=5,
                )
                if r.stdout:
                    log_lines.extend(r.stdout.strip().split("\n"))
            except (subprocess.TimeoutExpired, FileNotFoundError):
                pass

        # Collect from log files
        for log_file in self.log_files:
            try:
                lines = log_file.read_text().strip().split("\n")
                log_lines.extend(lines[-self.tail_lines:])
            except (OSError, PermissionError):
                pass

        # Extract errors and questions
        errors: list[dict] = []
        questions: list[str] = []
        seen_questions: set[str] = set()

        for line in log_lines:
            line_lower = line.lower()
            is_error = any(w in line_lower for w in
                          ("error", "fatal", "exception", "failed", "refused", "denied", "timeout"))

            if is_error:
                errors.append({"line": line.strip()[:200]})

                # What question does this error imply?
                for pattern, question in self.QUESTION_MAP.items():
                    if pattern in line_lower and question not in seen_questions:
                        questions.append(question)
                        seen_questions.add(question)

        return CategoryResult(
            category=self.name,
            timestamp=time.time(),
            data={
                "total_lines": len(log_lines),
                "error_count": len(errors),
                "errors": errors[:20],
                "questions_from_logs": questions,
            },
            changed=len(errors) > 0,
        )


class ActiveWorkCategory:
    """Collect signals about current development activity.

    What's being worked on RIGHT NOW:
    - Uncommitted changes (what might break)
    - Recent commits (what just changed)
    - Hot files (where churn concentrates)
    - Current branch context
    """

    name = "active"

    def __init__(self, repo_path: str):
        self.repo_path = Path(repo_path)

    def _git(self, *args: str) -> str:
        try:
            r = subprocess.run(
                ["git", "-C", str(self.repo_path)] + list(args),
                capture_output=True, text=True, timeout=10,
            )
            return r.stdout.strip()
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return ""

    def collect(self) -> CategoryResult:
        if not (self.repo_path / ".git").exists():
            return CategoryResult(self.name, time.time(), {"error": "not a git repo"})

        branch = self._git("rev-parse", "--abbrev-ref", "HEAD")

        # Uncommitted changes
        status = self._git("status", "--porcelain")
        status_lines = [l for l in status.split("\n") if l]
        modified = [l[3:] for l in status_lines if l.startswith(" M") or l.startswith("M")]
        added = [l[3:] for l in status_lines if l.startswith("A") or l.startswith("??")]

        # Recent commits (last 5)
        recent = self._git("log", "--oneline", "-5", "--format=%h %s")
        recent_commits = [l for l in recent.split("\n") if l]

        # Files with most churn in last 10 commits
        churn_raw = self._git("log", "-10", "--name-only", "--format=")
        churn: dict[str, int] = {}
        for line in churn_raw.split("\n"):
            line = line.strip()
            if line:
                churn[line] = churn.get(line, 0) + 1
        hot_files = sorted(churn.items(), key=lambda x: -x[1])[:10]

        # Diff stats for uncommitted work
        diff_stat = self._git("diff", "--stat")

        has_activity = bool(modified or added or recent_commits)

        return CategoryResult(
            category=self.name,
            timestamp=time.time(),
            data={
                "branch": branch,
                "modified_files": modified[:20],
                "new_files": added[:20],
                "recent_commits": recent_commits,
                "hot_files": [{"file": f, "changes": c} for f, c in hot_files],
                "diff_summary": diff_stat[:500] if diff_stat else "clean",
            },
            changed=has_activity,
        )


class DriftCategory:
    """Detect config and env drift since last heartbeat.

    Compares current state to a snapshot from the previous beat.
    Flags anything that changed without a commit.
    """

    name = "drift"

    def __init__(self, config_paths: list[str], snapshot_path: str):
        self.config_paths = [Path(p) for p in config_paths]
        self.snapshot_path = Path(snapshot_path)

    def collect(self) -> CategoryResult:
        current: dict[str, str] = {}
        diffs: list[dict] = []

        # Snapshot current config checksums
        for config_path in self.config_paths:
            if config_path.is_file():
                try:
                    content = config_path.read_text()
                    current[str(config_path)] = str(hash(content))
                except (OSError, PermissionError):
                    pass
            elif config_path.is_dir():
                for f in config_path.rglob("*"):
                    if f.is_file() and f.suffix in (".json", ".yaml", ".yml", ".conf", ".env"):
                        try:
                            content = f.read_text()
                            current[str(f)] = str(hash(content))
                        except (OSError, PermissionError):
                            pass

        # Load previous snapshot
        previous: dict[str, str] = {}
        if self.snapshot_path.exists():
            try:
                previous = json.loads(self.snapshot_path.read_text())
            except (json.JSONDecodeError, OSError):
                pass

        # Compare
        for path, checksum in current.items():
            prev = previous.get(path)
            if prev is None:
                diffs.append({"path": path, "change": "new"})
            elif prev != checksum:
                diffs.append({"path": path, "change": "modified"})

        for path in previous:
            if path not in current:
                diffs.append({"path": path, "change": "deleted"})

        # Save current as new snapshot
        self.snapshot_path.parent.mkdir(parents=True, exist_ok=True)
        self.snapshot_path.write_text(json.dumps(current, indent=2))

        return CategoryResult(
            category=self.name,
            timestamp=time.time(),
            data={
                "tracked_files": len(current),
                "changes_since_last_beat": diffs,
                "drift_count": len(diffs),
            },
            changed=len(diffs) > 0,
        )


class ResourceCategory:
    """Quick resource check — only flags if trending toward trouble."""

    name = "resource"

    def __init__(self, session_dir: str | None = None):
        self.session_dir = Path(session_dir) if session_dir else None

    def collect(self) -> CategoryResult:
        data: dict[str, Any] = {}
        warnings: list[str] = []

        # Memory
        try:
            r = subprocess.run(["free", "-m"], capture_output=True, text=True, timeout=5)
            for line in r.stdout.split("\n"):
                if line.startswith("Mem:"):
                    parts = line.split()
                    total = int(parts[1])
                    available = int(parts[-1])
                    used_pct = round((total - available) / total * 100)
                    data["memory"] = {"total_mb": total, "available_mb": available, "used_pct": used_pct}
                    if available < 500:
                        warnings.append(f"Low memory: {available}MB available")
        except (subprocess.TimeoutExpired, FileNotFoundError, (ValueError, IndexError)):
            pass

        # Disk
        try:
            r = subprocess.run(["df", "-h", "/"], capture_output=True, text=True, timeout=5)
            lines = r.stdout.strip().split("\n")
            if len(lines) >= 2:
                parts = lines[1].split()
                use_pct = int(parts[4].rstrip("%"))
                data["disk"] = {"use_pct": use_pct, "available": parts[3]}
                if use_pct > 85:
                    warnings.append(f"Disk usage at {use_pct}%")
        except (subprocess.TimeoutExpired, FileNotFoundError, (ValueError, IndexError)):
            pass

        # Session count (if applicable)
        if self.session_dir and self.session_dir.exists():
            try:
                count = len(list(self.session_dir.iterdir()))
                data["sessions"] = {"count": count}
                if count > 30:
                    warnings.append(f"Session bloat: {count} sessions")
            except OSError:
                pass

        return CategoryResult(
            category=self.name,
            timestamp=time.time(),
            data={**data, "warnings": warnings},
            changed=len(warnings) > 0,
        )


def _count_by(items: list[dict], key: str) -> dict[str, int]:
    """Count items by a key value."""
    counts: dict[str, int] = {}
    for item in items:
        val = item.get(key, "unknown")
        counts[val] = counts.get(val, 0) + 1
    return counts
