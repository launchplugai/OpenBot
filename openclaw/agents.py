"""Agent coordination — dispatch and tracking for OpenClaw agents."""

import asyncio
import datetime
import shutil
import uuid


class AgentRun:
    """Represents a single agent execution."""

    def __init__(self, agent_name: str, command: str, args: list[str] | None = None):
        self.id = uuid.uuid4().hex[:12]
        self.agent_name = agent_name
        self.command = command
        self.args = args or []
        self.status = "pending"
        self.started_at: str | None = None
        self.finished_at: str | None = None
        self.exit_code: int | None = None
        self.stdout = ""
        self.stderr = ""

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "agent": self.agent_name,
            "command": self.command,
            "args": self.args,
            "status": self.status,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "exit_code": self.exit_code,
            "stdout_lines": self.stdout.count("\n") if self.stdout else 0,
            "stderr_lines": self.stderr.count("\n") if self.stderr else 0,
        }


class AgentCoordinator:
    """Manages agent definitions, dispatches runs, tracks history."""

    def __init__(self, agent_defs: dict):
        self.agents = agent_defs  # from config.yaml
        self.history: list[AgentRun] = []
        self.max_history = 100

    def list_agents(self) -> list[dict]:
        result = []
        for name, spec in self.agents.items():
            result.append({
                "name": name,
                "role": spec.get("role", "unknown"),
                "description": spec.get("description", ""),
                "command": spec.get("command", ""),
                "available": self._is_available(spec.get("command", "")),
            })
        return result

    def get_agent(self, name: str) -> dict | None:
        spec = self.agents.get(name)
        if not spec:
            return None
        return {
            "name": name,
            **spec,
            "available": self._is_available(spec.get("command", "")),
        }

    async def dispatch(self, agent_name: str, args: list[str] | None = None) -> AgentRun:
        spec = self.agents.get(agent_name)
        if not spec:
            raise ValueError(f"Unknown agent: {agent_name}")

        command = spec["command"]
        run = AgentRun(agent_name, command, args)
        run.status = "running"
        run.started_at = datetime.datetime.utcnow().isoformat() + "Z"

        try:
            full_cmd = command
            if args:
                full_cmd += " " + " ".join(args)

            proc = await asyncio.create_subprocess_shell(
                full_cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=300)

            run.stdout = stdout.decode(errors="replace")
            run.stderr = stderr.decode(errors="replace")
            run.exit_code = proc.returncode
            run.status = "completed" if proc.returncode == 0 else "failed"
        except asyncio.TimeoutError:
            run.status = "timeout"
            run.stderr = "Agent run exceeded 300s timeout"
        except Exception as exc:
            run.status = "error"
            run.stderr = str(exc)

        run.finished_at = datetime.datetime.utcnow().isoformat() + "Z"
        self.history.append(run)
        if len(self.history) > self.max_history:
            self.history = self.history[-self.max_history:]
        return run

    def get_run(self, run_id: str) -> AgentRun | None:
        for run in reversed(self.history):
            if run.id == run_id:
                return run
        return None

    def recent_runs(self, limit: int = 20) -> list[dict]:
        return [r.to_dict() for r in reversed(self.history[-limit:])]

    @staticmethod
    def _is_available(command: str) -> bool:
        binary = command.split()[0] if command else ""
        return shutil.which(binary) is not None
