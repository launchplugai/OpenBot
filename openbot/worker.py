"""
Worker management for OpenBot CLI workers.

Manages the task board, worker configuration, shared memory,
and lesson tracking for the multi-tier agent architecture.
"""

import json
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from openbot.utils import generate_run_id, get_timestamp


class TaskBoard:
    """
    Shared task board for worker coordination.

    Workers claim tasks, report progress, and mark completion.
    This enables sensor-fusion style awareness across independent workers.
    """

    def __init__(self, board_path: Path):
        self.board_path = Path(board_path)
        self._ensure_file()

    def _ensure_file(self):
        self.board_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.board_path.exists():
            self._write({"tasks": [], "lastUpdated": get_timestamp()})

    def _read(self) -> Dict[str, Any]:
        try:
            with open(self.board_path) as f:
                return json.load(f)
        except (json.JSONDecodeError, FileNotFoundError):
            return {"tasks": [], "lastUpdated": get_timestamp()}

    def _write(self, data: Dict[str, Any]):
        data["lastUpdated"] = get_timestamp()
        with open(self.board_path, "w") as f:
            json.dump(data, f, indent=2)

    def add_task(
        self,
        title: str,
        description: str = "",
        priority: str = "normal",
        assigned_to: str = "",
    ) -> str:
        """Add a task to the board. Returns task_id."""
        data = self._read()
        task_id = generate_run_id()[:8]
        task = {
            "id": task_id,
            "title": title,
            "description": description,
            "priority": priority,
            "status": "pending",
            "assigned_to": assigned_to,
            "created_at": get_timestamp(),
            "claimed_at": None,
            "completed_at": None,
            "result": None,
        }
        data["tasks"].append(task)
        self._write(data)
        return task_id

    def claim_task(self, task_id: str, worker_id: str) -> bool:
        """Worker claims a task. Returns True if successful."""
        data = self._read()
        for task in data["tasks"]:
            if task["id"] == task_id and task["status"] == "pending":
                task["status"] = "in_progress"
                task["assigned_to"] = worker_id
                task["claimed_at"] = get_timestamp()
                self._write(data)
                return True
        return False

    def complete_task(
        self, task_id: str, worker_id: str, result: str = "success", details: str = ""
    ) -> bool:
        """Worker marks a task complete."""
        data = self._read()
        for task in data["tasks"]:
            if task["id"] == task_id and task["assigned_to"] == worker_id:
                task["status"] = "done" if result == "success" else "failed"
                task["completed_at"] = get_timestamp()
                task["result"] = {"status": result, "details": details}
                self._write(data)
                return True
        return False

    def get_pending_tasks(self) -> List[Dict[str, Any]]:
        """Get all pending (unclaimed) tasks."""
        data = self._read()
        return [t for t in data["tasks"] if t["status"] == "pending"]

    def get_worker_tasks(self, worker_id: str) -> List[Dict[str, Any]]:
        """Get all tasks assigned to a specific worker."""
        data = self._read()
        return [t for t in data["tasks"] if t["assigned_to"] == worker_id]

    def get_summary(self) -> Dict[str, Any]:
        """Get task board summary."""
        data = self._read()
        tasks = data["tasks"]
        by_status = {}
        for t in tasks:
            by_status[t["status"]] = by_status.get(t["status"], 0) + 1
        return {
            "total": len(tasks),
            "by_status": by_status,
            "lastUpdated": data.get("lastUpdated"),
        }


class LessonLog:
    """
    Shared lessons learned across all workers.

    Workers write lessons, all workers read them on startup.
    Enables collective learning across independent operators.
    """

    def __init__(self, log_path: Path):
        self.log_path = Path(log_path)
        self._ensure_file()

    def _ensure_file(self):
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.log_path.exists():
            self._write({"lessons": []})

    def _read(self) -> Dict[str, Any]:
        try:
            with open(self.log_path) as f:
                return json.load(f)
        except (json.JSONDecodeError, FileNotFoundError):
            return {"lessons": []}

    def _write(self, data: Dict[str, Any]):
        with open(self.log_path, "w") as f:
            json.dump(data, f, indent=2)

    def add_lesson(
        self,
        worker_id: str,
        category: str,
        lesson: str,
        context: str = "",
    ):
        """Worker contributes a lesson learned."""
        data = self._read()
        entry = {
            "id": generate_run_id()[:8],
            "worker_id": worker_id,
            "category": category,
            "lesson": lesson,
            "context": context,
            "timestamp": get_timestamp(),
        }
        data["lessons"].append(entry)
        # Keep last 100 lessons
        if len(data["lessons"]) > 100:
            data["lessons"] = data["lessons"][-100:]
        self._write(data)

    def get_recent(self, count: int = 10) -> List[Dict[str, Any]]:
        """Get recent lessons for worker startup context."""
        data = self._read()
        return data["lessons"][-count:]

    def get_by_category(self, category: str) -> List[Dict[str, Any]]:
        """Get lessons by category (e.g., 'bug', 'pattern', 'tool')."""
        data = self._read()
        return [l for l in data["lessons"] if l["category"] == category]


class WorkerConfig:
    """
    Generates worker-specific CLAUDE.md configuration.

    Each CLI worker gets a tailored configuration that defines its
    identity, mission, ROE, and session protocol.
    """

    CLAUDE_MD_TEMPLATE = """# CLI Worker {worker_id} — OpenClaw Organization

## Identity
You are **CLI Worker {worker_id}** in the OpenClaw multi-tier AI organization.
Your manager: Kimi 128K Sub-agent Master
Your commander: Kimi 2.5 Executive Coordinator
Your president: The User

## Mission
Execute coding tasks assigned by your manager with FULL TACTICAL AUTONOMY.
You are empowered to make decisions within your Rules of Engagement.
Do NOT ask for permission for authorized actions — act decisively.

## Rules of Engagement (ROE)

### AUTHORIZED (Act without asking)
- Create and switch git branches (claude/worker-{worker_id}/*)
- Run all tests (pytest, lint, type checks)
- Write and modify code in your workspace
- Create commits with descriptive messages
- Read any file in the workspace
- Search the codebase (grep, glob, find)
- Install dev dependencies
- Write to shared memory (lessons, taskboard updates)

### REQUIRES ESCALATION (Report to manager)
- Push to remote repository
- Create pull requests
- Modify configuration files (*.yaml, *.json, *.toml)
- Delete files or directories
- Change test fixtures or test data
- Merge branches
- Any action affecting other workers' branches

### PROHIBITED (Never, under any circumstances)
- Touch production repositories
- Modify system files outside workspace
- Delete git history (force push, reset --hard)
- Skip tests before pushing (--no-verify)
- Override lint failures
- Access credentials outside auth-profiles
- Modify other workers' branches or worktrees
- Push to main/master directly

## Session Protocol

### On Startup
1. Read shared memory: /root/.openclaw/memory/MEMORY.md
2. Read lessons: /root/.openclaw/memory/lessons.json
3. Check taskboard: /root/.openclaw/memory/taskboard.json
4. Claim your assigned task (update status to in_progress)
5. Verify workspace is clean (git status)
6. Verify remote is quarantine (git remote -v)

### During Work
- Write code changes incrementally
- Run tests frequently (fail fast)
- Commit working increments (don't batch everything)
- If stuck >10 minutes: write lesson, escalate to manager

### On Completion
1. Run final tests (must pass)
2. Run lint (must be clean)
3. Commit with descriptive message
4. Update taskboard (mark task done)
5. Write lessons learned
6. Generate worker receipt

### On Failure
1. Log the error clearly
2. Write lesson (what went wrong, what to try differently)
3. Update taskboard (mark task failed with details)
4. Escalate to manager with context

## Workspace
- Worktree: {workspace_path}
- Branch naming: claude/worker-{worker_id}/<task-description>
- Remote: quarantine repo ONLY
- Shared memory: /root/.openclaw/memory/

## Self-Improvement
After every task, ask yourself:
- Did I solve this efficiently?
- Could I have found a better approach?
- What would I do differently next time?
Write the answer to /root/.openclaw/memory/lessons.json

## Cost Awareness
You are an Opus 4.6 instance — powerful but expensive.
- Prefer efficient solutions over verbose exploration
- Don't read files you don't need
- Don't run commands speculatively
- Focus on the task, complete it, move on
"""

    @classmethod
    def generate(cls, worker_id: str, workspace_path: str = "") -> str:
        """Generate a CLAUDE.md for a specific worker."""
        if not workspace_path:
            workspace_path = f"/root/.openclaw/workspace/worker-{worker_id}"
        return cls.CLAUDE_MD_TEMPLATE.format(
            worker_id=worker_id,
            workspace_path=workspace_path,
        )

    @classmethod
    def write_configs(cls, base_dir: Path, worker_count: int = 4):
        """Write CLAUDE.md files for all workers."""
        base_dir = Path(base_dir)
        for i in range(1, worker_count + 1):
            worker_dir = base_dir / f"worker-{i}"
            worker_dir.mkdir(parents=True, exist_ok=True)
            config = cls.generate(str(i), str(worker_dir))
            claude_md_path = worker_dir / "CLAUDE.md"
            with open(claude_md_path, "w") as f:
                f.write(config)
