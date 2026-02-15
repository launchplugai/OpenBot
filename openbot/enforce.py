"""
Constitutional enforcement for OpenBot.

Phase 2: Policies are loaded AND enforced. Every action is validated
against the constitutional framework before execution.
"""

import fnmatch
import json
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from openbot.policy import PolicyLoader
from openbot.utils import get_timestamp, generate_run_id


class Violation:
    """A constitutional violation."""

    def __init__(self, rule_id: str, severity: str, message: str, path: str = ""):
        self.rule_id = rule_id
        self.severity = severity  # critical, high, medium, low
        self.message = message
        self.path = path
        self.timestamp = get_timestamp()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "severity": self.severity,
            "message": self.message,
            "path": self.path,
            "timestamp": self.timestamp,
        }


class PathProtector:
    """Enforces protected path policies."""

    def __init__(self, protected_globs: List[str], allowed_write_paths: List[str]):
        self.protected_globs = protected_globs
        self.allowed_write_paths = allowed_write_paths

    def check_path(self, path: str, action: str = "write") -> Optional[Violation]:
        """Check if an action on a path violates protection rules."""
        # Normalize path
        path = path.replace("\\", "/").lstrip("./")

        # Check allowed paths first (allow overrides protect)
        for pattern in self.allowed_write_paths:
            if fnmatch.fnmatch(path, pattern):
                return None

        # Check protected paths
        for pattern in self.protected_globs:
            if fnmatch.fnmatch(path, pattern):
                return Violation(
                    rule_id="protected_path",
                    severity="critical",
                    message=f"Path '{path}' is protected by pattern '{pattern}'",
                    path=path,
                )

        return None

    def check_paths(self, paths: List[str], action: str = "write") -> List[Violation]:
        """Check multiple paths, return all violations."""
        violations = []
        for path in paths:
            v = self.check_path(path, action)
            if v:
                violations.append(v)
        return violations


class QualityGate:
    """Enforces quality gates before actions are permitted."""

    def __init__(self, gates: Optional[Dict[str, Any]] = None):
        self.gates = gates or {}

    def check_pre_push(
        self,
        tests_passed: bool,
        lint_clean: bool,
        branch_name: str,
    ) -> List[Violation]:
        """Check quality gates before a push is allowed."""
        violations = []

        if not tests_passed:
            violations.append(Violation(
                rule_id="quality_gate_tests",
                severity="critical",
                message="Cannot push: tests have not passed",
            ))

        if not lint_clean:
            violations.append(Violation(
                rule_id="quality_gate_lint",
                severity="high",
                message="Cannot push: lint errors detected",
            ))

        # Check branch naming convention
        if not branch_name.startswith("claude/"):
            violations.append(Violation(
                rule_id="quality_gate_branch_name",
                severity="medium",
                message=f"Branch '{branch_name}' does not follow claude/ naming convention",
            ))

        return violations

    def check_pre_merge(
        self,
        tests_passed: bool,
        lint_clean: bool,
        pr_approved: bool,
    ) -> List[Violation]:
        """Check quality gates before a merge is allowed."""
        violations = self.check_pre_push(tests_passed, lint_clean, "claude/ok")
        if not pr_approved:
            violations.append(Violation(
                rule_id="quality_gate_approval",
                severity="critical",
                message="Cannot merge: PR not approved by PO",
            ))
        return violations


class WorkerReceipt:
    """Receipt for a single worker action."""

    def __init__(self, worker_id: str):
        self.receipt_id = generate_run_id()
        self.worker_id = worker_id
        self.action = ""
        self.target = ""
        self.started_at = get_timestamp()
        self.finished_at: Optional[str] = None
        self.duration_ms: int = 0
        self._start_time = time.time()
        self.details: Dict[str, Any] = {}
        self.cost_tokens: int = 0
        self.status = "in_progress"
        self.violations: List[Dict[str, Any]] = []
        self.error: Optional[str] = None

    def set_action(self, action: str, target: str = ""):
        self.action = action
        self.target = target

    def set_details(self, **kwargs):
        self.details.update(kwargs)

    def add_violation(self, violation: Violation):
        self.violations.append(violation.to_dict())

    def complete(self, status: str = "success", error: Optional[str] = None):
        self.finished_at = get_timestamp()
        self.duration_ms = int((time.time() - self._start_time) * 1000)
        self.status = status
        self.error = error

    def to_dict(self) -> Dict[str, Any]:
        result = {
            "receipt_id": self.receipt_id,
            "worker_id": self.worker_id,
            "action": self.action,
            "target": self.target,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "duration_ms": self.duration_ms,
            "details": self.details,
            "cost_tokens": self.cost_tokens,
            "status": self.status,
            "violations": self.violations,
        }
        if self.error:
            result["error"] = self.error
        return result


class Enforcer:
    """
    Constitutional enforcer - validates all actions against policies.

    This is the core of Phase 2: policies are actually enforced, not just loaded.
    """

    def __init__(self, policies_dir: Optional[Path] = None):
        self.policy_loader = PolicyLoader(policies_dir)
        self.policy_loader.load_all()

        # Initialize sub-enforcers
        self.path_protector = PathProtector(
            protected_globs=self.policy_loader.get_protected_globs(),
            allowed_write_paths=self.policy_loader.get_allowed_write_paths(),
        )
        self.quality_gate = QualityGate()

        # Track violations and receipts
        self.violations: List[Violation] = []
        self.worker_receipts: List[WorkerReceipt] = []

    def check_file_write(self, path: str) -> Tuple[bool, Optional[Violation]]:
        """Check if a file write is allowed. Returns (allowed, violation_or_none)."""
        violation = self.path_protector.check_path(path, "write")
        if violation:
            self.violations.append(violation)
            return False, violation
        return True, None

    def check_file_writes(self, paths: List[str]) -> Tuple[bool, List[Violation]]:
        """Check multiple file writes. Returns (all_allowed, violations)."""
        violations = self.path_protector.check_paths(paths)
        self.violations.extend(violations)
        return len(violations) == 0, violations

    def check_push(
        self,
        branch: str,
        tests_passed: bool,
        lint_clean: bool,
    ) -> Tuple[bool, List[Violation]]:
        """Check if a push is allowed. Returns (allowed, violations)."""
        violations = self.quality_gate.check_pre_push(
            tests_passed, lint_clean, branch
        )
        self.violations.extend(violations)
        has_critical = any(v.severity == "critical" for v in violations)
        return not has_critical, violations

    def check_remote(self, remote_url: str) -> Tuple[bool, Optional[Violation]]:
        """Check if a git remote is the quarantine repo (not production)."""
        # Production indicators
        production_patterns = ["betapp", "bet-app", "production"]
        for pattern in production_patterns:
            if pattern in remote_url.lower():
                v = Violation(
                    rule_id="quarantine_violation",
                    severity="critical",
                    message=f"Remote '{remote_url}' appears to be production. "
                    "All work must go to quarantine repo.",
                )
                self.violations.append(v)
                return False, v
        return True, None

    def create_worker_receipt(self, worker_id: str) -> WorkerReceipt:
        """Create a new worker receipt for tracking."""
        receipt = WorkerReceipt(worker_id)
        self.worker_receipts.append(receipt)
        return receipt

    def get_violation_summary(self) -> Dict[str, Any]:
        """Get a summary of all violations."""
        by_severity = {"critical": 0, "high": 0, "medium": 0, "low": 0}
        for v in self.violations:
            by_severity[v.severity] = by_severity.get(v.severity, 0) + 1

        return {
            "total": len(self.violations),
            "by_severity": by_severity,
            "violations": [v.to_dict() for v in self.violations],
            "blocked": by_severity["critical"] > 0,
        }

    def get_worker_summary(self) -> Dict[str, Any]:
        """Get a summary of all worker receipts."""
        by_status = {"success": 0, "failed": 0, "in_progress": 0, "blocked": 0}
        total_tokens = 0
        total_duration_ms = 0

        for r in self.worker_receipts:
            by_status[r.status] = by_status.get(r.status, 0) + 1
            total_tokens += r.cost_tokens
            total_duration_ms += r.duration_ms

        return {
            "total_receipts": len(self.worker_receipts),
            "by_status": by_status,
            "total_tokens": total_tokens,
            "total_duration_ms": total_duration_ms,
            "receipts": [r.to_dict() for r in self.worker_receipts],
        }

    def save_receipts(self, receipts_dir: Path):
        """Save all worker receipts to disk."""
        receipts_dir = Path(receipts_dir)
        workers_dir = receipts_dir / "workers"
        workers_dir.mkdir(parents=True, exist_ok=True)

        for receipt in self.worker_receipts:
            path = workers_dir / f"{receipt.receipt_id}.json"
            with open(path, "w") as f:
                json.dump(receipt.to_dict(), f, indent=2)
