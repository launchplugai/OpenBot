"""
Runner module - executes test runs against target repositories.
"""

import os
import re
import shutil
import time
import traceback
import urllib.request
import urllib.error
from pathlib import Path
from typing import Optional, Tuple

from openbot.enforce import Enforcer
from openbot.policy import PolicyLoader
from openbot.receipts import Receipt, ReceiptWriter
from openbot.utils import (
    Logger,
    ensure_dir,
    run_command,
    truncate_string,
    generate_run_id,
    get_timestamp,
)


def parse_pytest_output(output: str) -> Tuple[Optional[int], Optional[int]]:
    """
    Parse pytest output to extract pass/fail counts.

    Looks for patterns like:
    - "831 passed, 9 failed"
    - "831 passed"
    - "9 failed"
    - "===== 831 passed, 9 failed in 5.23s ====="

    Returns: (passed_count, failed_count) - either can be None if not found
    """
    passed = None
    failed = None

    # Match pytest summary line patterns
    # Pattern: "X passed" or "X passed,"
    passed_match = re.search(r'(\d+)\s+passed', output)
    if passed_match:
        passed = int(passed_match.group(1))

    # Pattern: "X failed" or "X failed,"
    failed_match = re.search(r'(\d+)\s+failed', output)
    if failed_match:
        failed = int(failed_match.group(1))

    return passed, failed


def load_credentials(credentials_file: Path = Path("/etc/openbot/credentials")) -> dict:
    """
    Load credentials from /etc/openbot/credentials file.

    Format: KEY=VALUE (one per line, no quotes needed)
    Returns dict of key-value pairs.
    """
    creds = {}
    if credentials_file.exists():
        try:
            with open(credentials_file, "r") as f:
                for line in f:
                    line = line.strip()
                    if line and "=" in line and not line.startswith("#"):
                        key, value = line.split("=", 1)
                        creds[key.strip()] = value.strip()
        except (OSError, PermissionError):
            pass
    return creds


def get_authenticated_url(repo_url: str, credentials: dict) -> str:
    """
    Convert a GitHub URL to an authenticated URL using stored credentials.

    Supports DNA_REPO_TOKEN for github.com/launchplugai/DNA access.
    """
    # Check if this is a GitHub URL that needs authentication
    if "github.com/launchplugai/DNA" in repo_url and "DNA_REPO_TOKEN" in credentials:
        token = credentials["DNA_REPO_TOKEN"]
        # Convert https://github.com/... to https://<token>@github.com/...
        if repo_url.startswith("https://github.com/"):
            return repo_url.replace("https://github.com/", f"https://{token}@github.com/")
    return repo_url


class Runner:
    """Executes Openbot runs against target repositories."""

    def __init__(
        self,
        target_repo: str,
        target_branch: str,
        workdir: Path,
        command: str,
        logs_dir: Path,
        receipts_dir: Path,
        health_url: Optional[str] = None,
        policies_dir: Optional[Path] = None,
        setup_command: Optional[str] = None,
    ):
        self.target_repo = target_repo
        self.target_branch = target_branch
        self.base_workdir = Path(workdir)
        self.command = command
        self.setup_command = setup_command
        self.logs_dir = Path(logs_dir)
        self.receipts_dir = Path(receipts_dir)
        self.health_url = health_url

        self.run_id = generate_run_id()
        # Fresh workdir per run: /var/lib/openbot/workdir/<run_id>/
        self.workdir = self.base_workdir / self.run_id
        self.target_dir = self.workdir / "target"
        self.log_path = self.logs_dir / f"{self.run_id}.log"

        # Load credentials for authenticated git access
        self.credentials = load_credentials()

        # Load policies
        self.policy_loader = PolicyLoader(policies_dir)
        self.policy_loader.load_all()

        # Initialize enforcer (Phase 2: policies are enforced)
        self.enforcer = Enforcer(policies_dir)

        # Initialize receipt
        self.receipt = Receipt()
        self.receipt.run_id = self.run_id
        self.receipt.set_policies_loaded(self.policy_loader.get_loaded_policy_names())

    def run(self) -> Tuple[bool, str]:
        """
        Execute the full run.

        Returns: (success, receipt_path)
        """
        ensure_dir(self.logs_dir)
        ensure_dir(self.workdir)

        start_time = time.time()

        with Logger(self.log_path, also_stdout=True) as logger:
            try:
                logger.info(f"=== Openbot Run Started ===")
                logger.info(f"Run ID: {self.run_id}")
                logger.info(f"Target repo: {self.target_repo}")
                logger.info(f"Target branch: {self.target_branch}")
                logger.info(f"Workdir: {self.workdir}")
                if self.setup_command:
                    logger.info(f"Setup command: {self.setup_command}")
                logger.info(f"Test command: {self.command}")

                # Step 1: Clone repository (always fresh clone per run)
                commit_sha = self._clone_repo(logger)
                if not commit_sha:
                    self.receipt.add_error("Failed to clone repository")
                    self.receipt.set_target(self.target_repo, self.target_branch, "0" * 40)
                    runtime = round(time.time() - start_time, 2)
                    self.receipt.set_test_result(
                        self.command, -1, str(self.log_path),
                        runtime_seconds=runtime,
                        setup_command=self.setup_command
                    )
                    return self._finalize_receipt(logger, cleanup=True)

                self.receipt.set_target(self.target_repo, self.target_branch, commit_sha)
                logger.info(f"Commit SHA: {commit_sha}")

                # Step 2: Run setup command (optional)
                if self.setup_command:
                    setup_exit_code = self._run_setup_command(logger)
                    if setup_exit_code != 0:
                        self.receipt.add_error(f"Setup command failed with exit code {setup_exit_code}")
                        runtime = round(time.time() - start_time, 2)
                        self.receipt.set_test_result(
                            self.command, -1, str(self.log_path),
                            runtime_seconds=runtime,
                            setup_command=self.setup_command
                        )
                        return self._finalize_receipt(logger, cleanup=True)

                # Step 3: Run test command
                test_exit_code, test_output = self._run_test_command(logger)

                # Parse pytest output for pass/fail counts
                passed, failed = parse_pytest_output(test_output)
                logger.info(f"Pytest results: passed={passed}, failed={failed}")

                runtime = round(time.time() - start_time, 2)
                self.receipt.set_test_result(
                    self.command, test_exit_code, str(self.log_path),
                    passed=passed,
                    failed=failed,
                    runtime_seconds=runtime,
                    setup_command=self.setup_command
                )

                # Step 4: Validate constraints (Phase 2 enforcement)
                self._validate_constraints(logger, test_exit_code)

                # Step 5: Optional health check
                if self.health_url:
                    self._run_health_check(logger)

                logger.info(f"=== Openbot Run Completed (runtime: {runtime}s) ===")
                return self._finalize_receipt(logger, cleanup=True)

            except Exception as e:
                logger.error(f"Unexpected error: {e}")
                logger.error(traceback.format_exc())
                self.receipt.add_error(f"Unexpected error: {e}")
                self.receipt.set_target(self.target_repo, self.target_branch, "0" * 40)
                runtime = round(time.time() - start_time, 2)
                self.receipt.set_test_result(
                    self.command, -1, str(self.log_path),
                    runtime_seconds=runtime,
                    setup_command=self.setup_command
                )
                return self._finalize_receipt(logger, cleanup=True)

    def _clone_repo(self, logger: Logger) -> Optional[str]:
        """Clone repository fresh (workdir is unique per run). Returns commit SHA or None."""
        logger.info(f"Cloning repository...")
        ensure_dir(self.workdir)

        # Get authenticated URL if credentials available
        clone_url = get_authenticated_url(self.target_repo, self.credentials)

        # Log the public URL (never log tokens)
        exit_code, stdout, stderr = run_command(
            f"git clone --branch {self.target_branch} {clone_url} target",
            cwd=self.workdir
        )
        # Log with original URL to avoid exposing tokens
        logger.command(
            f"git clone --branch {self.target_branch} {self.target_repo} target",
            exit_code, stdout, stderr
        )
        if exit_code != 0:
            return None

        # Get commit SHA
        exit_code, stdout, stderr = run_command(
            "git rev-parse HEAD",
            cwd=self.target_dir
        )
        logger.command("git rev-parse HEAD", exit_code, stdout, stderr)
        if exit_code != 0:
            return None

        return stdout.strip()

    def _run_setup_command(self, logger: Logger) -> int:
        """Run the setup command (e.g., pip install). Returns exit code."""
        logger.info(f"Running setup command: {self.setup_command}")

        exit_code, stdout, stderr = run_command(
            self.setup_command,
            cwd=self.target_dir,
            timeout=600  # 10 minute timeout
        )
        logger.command(self.setup_command, exit_code, stdout, stderr)

        if exit_code != 0:
            logger.error(f"Setup command failed with exit code {exit_code}")
        else:
            logger.info(f"Setup command succeeded")

        return exit_code

    def _run_test_command(self, logger: Logger) -> Tuple[int, str]:
        """Run the test command. Returns (exit_code, combined_output)."""
        logger.info(f"Running test command: {self.command}")

        exit_code, stdout, stderr = run_command(
            self.command,
            cwd=self.target_dir,
            timeout=600  # 10 minute timeout
        )
        logger.command(self.command, exit_code, stdout, stderr)

        if exit_code != 0:
            logger.error(f"Test command failed with exit code {exit_code}")
        else:
            logger.info(f"Test command succeeded")

        # Return combined output for parsing
        combined_output = stdout + "\n" + stderr
        return exit_code, combined_output

    def _validate_constraints(self, logger: Logger, test_exit_code: int):
        """Phase 2: Validate run against constitutional constraints."""
        logger.info("Validating constitutional constraints...")

        # Check remote is quarantine (not production)
        if self.target_dir.exists():
            from openbot.utils import run_command
            exit_code, stdout, _ = run_command(
                "git remote get-url origin", cwd=self.target_dir
            )
            if exit_code == 0 and stdout.strip():
                allowed, violation = self.enforcer.check_remote(stdout.strip())
                if not allowed:
                    logger.error(f"CONSTRAINT VIOLATION: {violation.message}")
                    self.receipt.add_error(f"Constraint violation: {violation.message}")

        # Log enforcement summary
        summary = self.enforcer.get_violation_summary()
        if summary["total"] > 0:
            logger.warn(
                f"Constraint check: {summary['total']} violation(s) "
                f"(critical={summary['by_severity']['critical']})"
            )
        else:
            logger.info("Constraint check: PASS (0 violations)")

    def _run_health_check(self, logger: Logger):
        """Run optional health check."""
        logger.info(f"Running health check: {self.health_url}")

        try:
            req = urllib.request.Request(
                self.health_url,
                headers={"User-Agent": "Openbot/0.1"}
            )
            with urllib.request.urlopen(req, timeout=30) as response:
                status_code = response.getcode()
                body = response.read().decode("utf-8", errors="replace")
                body_snippet = truncate_string(body, 500)
                ok = 200 <= status_code < 300

                logger.info(f"Health check status: {status_code}, ok: {ok}")
                self.receipt.set_health_result(
                    url=self.health_url,
                    status_code=status_code,
                    body_snippet=body_snippet,
                    ok=ok
                )
        except urllib.error.HTTPError as e:
            logger.error(f"Health check HTTP error: {e.code}")
            self.receipt.set_health_result(
                url=self.health_url,
                status_code=e.code,
                body_snippet=str(e.reason),
                ok=False
            )
        except Exception as e:
            logger.error(f"Health check error: {e}")
            self.receipt.set_health_result(
                url=self.health_url,
                status_code=None,
                body_snippet=str(e),
                ok=False
            )

    def _cleanup_workdir(self, logger: Logger):
        """Remove the run-specific workdir after run completes."""
        if self.workdir.exists():
            logger.info(f"Cleaning up workdir: {self.workdir}")
            try:
                shutil.rmtree(self.workdir)
                logger.info(f"Workdir cleaned up successfully")
            except Exception as e:
                logger.warn(f"Failed to cleanup workdir: {e}")

    def _finalize_receipt(self, logger: Logger, cleanup: bool = False) -> Tuple[bool, str]:
        """Finalize and write the receipt, optionally cleanup workdir."""
        receipt_data = self.receipt.finalize()

        # Get schema for validation
        schema = self.policy_loader.get_receipt_schema()

        writer = ReceiptWriter(self.receipts_dir, schema)
        success, path = writer.write(receipt_data)

        if success:
            logger.info(f"Receipt written: {path}")
        else:
            logger.error(f"Receipt validation failed, quarantined: {path}")

        # Cleanup workdir after receipt is written
        if cleanup:
            self._cleanup_workdir(logger)

        return receipt_data["overall_status"] == "SUCCESS", path
