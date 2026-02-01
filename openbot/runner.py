"""
Runner module - executes test runs against target repositories.
"""

import os
import traceback
import urllib.request
import urllib.error
from pathlib import Path
from typing import Optional, Tuple

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
    ):
        self.target_repo = target_repo
        self.target_branch = target_branch
        self.workdir = Path(workdir)
        self.command = command
        self.logs_dir = Path(logs_dir)
        self.receipts_dir = Path(receipts_dir)
        self.health_url = health_url

        self.run_id = generate_run_id()
        self.target_dir = self.workdir / "target"
        self.log_path = self.logs_dir / f"{self.run_id}.log"

        # Load policies
        self.policy_loader = PolicyLoader(policies_dir)
        self.policy_loader.load_all()

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

        with Logger(self.log_path, also_stdout=True) as logger:
            try:
                logger.info(f"=== Openbot Run Started ===")
                logger.info(f"Run ID: {self.run_id}")
                logger.info(f"Target repo: {self.target_repo}")
                logger.info(f"Target branch: {self.target_branch}")
                logger.info(f"Workdir: {self.workdir}")
                logger.info(f"Command: {self.command}")

                # Step 1: Clone or fetch repository
                commit_sha = self._clone_or_fetch(logger)
                if not commit_sha:
                    self.receipt.add_error("Failed to clone/fetch repository")
                    self.receipt.set_target(self.target_repo, self.target_branch, "0" * 40)
                    self.receipt.set_test_result(self.command, -1, str(self.log_path))
                    return self._finalize_receipt(logger)

                self.receipt.set_target(self.target_repo, self.target_branch, commit_sha)
                logger.info(f"Commit SHA: {commit_sha}")

                # Step 2: Run test command
                test_exit_code = self._run_test_command(logger)
                self.receipt.set_test_result(self.command, test_exit_code, str(self.log_path))

                # Step 3: Optional health check
                if self.health_url:
                    self._run_health_check(logger)

                logger.info(f"=== Openbot Run Completed ===")
                return self._finalize_receipt(logger)

            except Exception as e:
                logger.error(f"Unexpected error: {e}")
                logger.error(traceback.format_exc())
                self.receipt.add_error(f"Unexpected error: {e}")
                self.receipt.set_target(self.target_repo, self.target_branch, "0" * 40)
                self.receipt.set_test_result(self.command, -1, str(self.log_path))
                return self._finalize_receipt(logger)

    def _clone_or_fetch(self, logger: Logger) -> Optional[str]:
        """Clone repository or fetch if already exists. Returns commit SHA or None."""
        if self.target_dir.exists():
            # Fetch and checkout
            logger.info(f"Target directory exists, fetching updates...")

            # Fetch
            exit_code, stdout, stderr = run_command(
                f"git fetch origin {self.target_branch}",
                cwd=self.target_dir
            )
            logger.command(f"git fetch origin {self.target_branch}", exit_code, stdout, stderr)
            if exit_code != 0:
                return None

            # Checkout
            exit_code, stdout, stderr = run_command(
                f"git checkout {self.target_branch}",
                cwd=self.target_dir
            )
            logger.command(f"git checkout {self.target_branch}", exit_code, stdout, stderr)
            if exit_code != 0:
                return None

            # Reset to origin
            exit_code, stdout, stderr = run_command(
                f"git reset --hard origin/{self.target_branch}",
                cwd=self.target_dir
            )
            logger.command(f"git reset --hard origin/{self.target_branch}", exit_code, stdout, stderr)
            if exit_code != 0:
                return None
        else:
            # Clone fresh
            logger.info(f"Cloning repository...")
            ensure_dir(self.workdir)

            exit_code, stdout, stderr = run_command(
                f"git clone --branch {self.target_branch} {self.target_repo} target",
                cwd=self.workdir
            )
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

    def _run_test_command(self, logger: Logger) -> int:
        """Run the test command. Returns exit code."""
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

        return exit_code

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

    def _finalize_receipt(self, logger: Logger) -> Tuple[bool, str]:
        """Finalize and write the receipt."""
        receipt_data = self.receipt.finalize()

        # Get schema for validation
        schema = self.policy_loader.get_receipt_schema()

        writer = ReceiptWriter(self.receipts_dir, schema)
        success, path = writer.write(receipt_data)

        if success:
            logger.info(f"Receipt written: {path}")
        else:
            logger.error(f"Receipt validation failed, quarantined: {path}")

        return receipt_data["overall_status"] == "SUCCESS", path
