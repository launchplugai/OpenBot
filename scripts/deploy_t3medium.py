#!/usr/bin/env python3
"""
deploy_t3medium.py - Post-resize deployment script for t3.medium EC2 instance.

This script is designed to be base64-encoded and sent to the EC2 instance via SSM.
It configures the instance after an upgrade from t3.small to t3.medium:
  - Verifies RAM, expands swap, relaxes systemd/context limits
  - Deploys onboarding docs, clears stale sessions, restarts gateway

Usage (on EC2 directly):
    python3 deploy_t3medium.py

Usage (via SSM from local):
    Encode with base64 and send via ssm_send_command.
"""

import json
import shutil
import subprocess
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

OPENCLAW_CONFIG = Path("/root/.openclaw/openclaw.json")
HARDENING_CONF = Path("/etc/systemd/system/openclaw-gateway.service.d/hardening.conf")
MEMORY_MD = Path("/root/.openclaw/memory/MEMORY.md")
ONBOARDING_DIR = Path("/root/.openclaw/memory/onboarding")
ONBOARDING_FILE = ONBOARDING_DIR / "OPENCLAW_ONBOARDING.md"
SESSIONS_DIR = Path("/root/.openclaw/agents/main/sessions")
SWAPFILE = Path("/swapfile")

EXPECTED_MIN_RAM_MB = 3900
SWAP_SIZE_MB = 4096
MEMORY_MAX = "3072M"

# Placeholder: replace with actual onboarding content before deployment.
ONBOARDING_CONTENT = """\
# OpenClaw Onboarding

Welcome to the OpenClaw agent environment.

## Instance Details
- **Instance type**: t3.medium (4 GB RAM, 4 GB swap)
- **Region**: us-east-2
- **Gateway service**: openclaw-gateway (systemd)

## Key Paths
- Config: /root/.openclaw/openclaw.json
- Memory: /root/.openclaw/memory/
- Sessions: /root/.openclaw/agents/main/sessions/

## Quick Commands
- `systemctl status openclaw-gateway` - check gateway
- `journalctl -u openclaw-gateway -f` - tail logs
- `openbot doctor --local` - verify environment

## Notes
- Gateway takes ~50s to start; don't probe the port immediately after restart.
- Config file is self-modified by the agent during conversations; do not chattr +i.
"""

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

total_steps = 9
critical_failures: list = []


def run(cmd: str, check: bool = True, capture: bool = True) -> subprocess.CompletedProcess:
    """Run a shell command, returning the CompletedProcess."""
    return subprocess.run(
        cmd,
        shell=True,
        check=check,
        capture_output=capture,
        text=True,
    )


def step_banner(num: int, description: str) -> None:
    print(f"\nStep {num}/{total_steps}: {description}...", flush=True)


def ok(msg: str = "") -> None:
    suffix = f" ({msg})" if msg else ""
    print(f"  OK{suffix}", flush=True)


def fail(msg: str, critical: bool = False) -> None:
    print(f"  FAILED: {msg}", flush=True)
    if critical:
        critical_failures.append(msg)


# ---------------------------------------------------------------------------
# Steps
# ---------------------------------------------------------------------------

def step_1_verify_ram() -> None:
    """Verify that the instance has ~4 GB RAM (t3.medium)."""
    step_banner(1, "Verifying RAM")
    try:
        result = run("free -m")
        for line in result.stdout.splitlines():
            if line.startswith("Mem:"):
                parts = line.split()
                total_mb = int(parts[1])
                if total_mb >= EXPECTED_MIN_RAM_MB:
                    ok(f"{total_mb} MB")
                else:
                    fail(
                        f"Expected >= {EXPECTED_MIN_RAM_MB} MB, got {total_mb} MB. "
                        "Is this really t3.medium?",
                        critical=True,
                    )
                return
        fail("Could not parse 'free -m' output", critical=True)
    except Exception as exc:
        fail(str(exc), critical=True)


def step_2_expand_swap() -> None:
    """Expand the swap file to 4 GB."""
    step_banner(2, "Expanding swap to 4 GB")
    try:
        # Turn off existing swap (ignore errors if not active)
        if SWAPFILE.exists():
            run("swapoff /swapfile", check=False)

        run(f"dd if=/dev/zero of=/swapfile bs=1M count={SWAP_SIZE_MB}")
        run("chmod 600 /swapfile")
        run("mkswap /swapfile")
        run("swapon /swapfile")

        # Verify
        result = run("swapon --show")
        if "/swapfile" in result.stdout:
            # Parse size from swapon output
            for line in result.stdout.splitlines():
                if "/swapfile" in line:
                    ok(line.strip())
                    return
        ok("swap enabled")
    except Exception as exc:
        fail(str(exc), critical=True)


def step_3_update_systemd_memory() -> None:
    """Update the systemd memory limit to 3072M."""
    step_banner(3, "Updating systemd memory limit")
    try:
        conf_dir = HARDENING_CONF.parent
        conf_dir.mkdir(parents=True, exist_ok=True)

        # Read existing content (if any) to preserve non-memory directives
        existing_lines: list = []
        if HARDENING_CONF.exists():
            existing_text = HARDENING_CONF.read_text()
            for line in existing_text.splitlines():
                stripped = line.strip()
                # Drop old MemoryMax lines and section headers (we re-add them)
                if stripped.startswith("MemoryMax=") or stripped == "[Service]":
                    continue
                existing_lines.append(line)

        content_parts = ["[Service]", f"MemoryMax={MEMORY_MAX}"]
        # Append any preserved directives after the section header
        for extra in existing_lines:
            if extra.strip():
                content_parts.append(extra)

        HARDENING_CONF.write_text("\n".join(content_parts) + "\n")
        run("systemctl daemon-reload")
        ok(f"MemoryMax={MEMORY_MAX}")
    except Exception as exc:
        fail(str(exc), critical=True)


def step_4_relax_context_pruning() -> None:
    """Relax context pruning settings in openclaw.json."""
    step_banner(4, "Relaxing context pruning in openclaw.json")
    try:
        if not OPENCLAW_CONFIG.exists():
            fail(f"{OPENCLAW_CONFIG} not found", critical=False)
            return

        config = json.loads(OPENCLAW_CONFIG.read_text())

        # Navigate to or create contextPruning section
        cp = config.setdefault("contextPruning", {})
        cp["ttl"] = "30m"
        cp["keepLast"] = 6
        cp["softTrim"] = 0.7

        OPENCLAW_CONFIG.write_text(json.dumps(config, indent=2) + "\n")
        ok("ttl=30m, keepLast=6, softTrim=0.7")
    except Exception as exc:
        fail(str(exc), critical=False)


def step_5_deploy_onboarding() -> None:
    """Deploy the onboarding documentation."""
    step_banner(5, "Deploying onboarding doc")
    try:
        ONBOARDING_DIR.mkdir(parents=True, exist_ok=True)
        ONBOARDING_FILE.write_text(ONBOARDING_CONTENT)
        ok(str(ONBOARDING_FILE))
    except Exception as exc:
        fail(str(exc), critical=False)


def step_6_update_memory_md() -> None:
    """Update MEMORY.md with t3.medium upgrade note."""
    step_banner(6, "Updating MEMORY.md")
    try:
        if not MEMORY_MD.exists():
            fail(f"{MEMORY_MD} not found, skipping", critical=False)
            return

        text = MEMORY_MD.read_text()

        # Add upgrade note if not already present
        upgrade_note = "- **2026-02-15**: Upgraded instance from t3.small to t3.medium (4 GB RAM, 4 GB swap)"
        if "t3.medium" not in text and "2026-02-15" not in text:
            # Append to the end
            text = text.rstrip() + "\n\n## Instance Upgrade Log\n" + upgrade_note + "\n"

        # Replace t3.small references with t3.medium
        text = text.replace("t3.small", "t3.medium")

        MEMORY_MD.write_text(text)
        ok("added upgrade note, updated instance type references")
    except Exception as exc:
        fail(str(exc), critical=False)


def step_7_clear_sessions() -> None:
    """Clear old session data to prevent bloat."""
    step_banner(7, "Clearing old sessions")
    try:
        if not SESSIONS_DIR.exists():
            ok("sessions directory does not exist, nothing to clear")
            return

        entries = list(SESSIONS_DIR.iterdir())
        count = len(entries)
        for entry in entries:
            if entry.is_dir():
                shutil.rmtree(entry)
            else:
                entry.unlink()
        ok(f"removed {count} entries from {SESSIONS_DIR}")
    except Exception as exc:
        fail(str(exc), critical=False)


def step_8_restart_gateway() -> None:
    """Restart the openclaw-gateway service."""
    step_banner(8, "Restarting gateway")
    try:
        run("systemctl restart openclaw-gateway")
        ok("restart command sent (gateway takes ~50s to fully start)")
    except Exception as exc:
        fail(str(exc), critical=True)


def _get_metadata_instance_type() -> str:
    """Fetch instance type from EC2 instance metadata (IMDSv2)."""
    try:
        token_result = run(
            "curl -sf -X PUT "
            '"http://169.254.169.254/latest/api/token" '
            '-H "X-aws-ec2-metadata-token-ttl-seconds: 60"',
            check=True,
        )
        token = token_result.stdout.strip()
        type_result = run(
            "curl -sf "
            '"http://169.254.169.254/latest/meta-data/instance-type" '
            f'-H "X-aws-ec2-metadata-token: {token}"',
            check=True,
        )
        return type_result.stdout.strip()
    except Exception:
        return "unknown"


def step_9_status_report() -> None:
    """Print a summary status report."""
    step_banner(9, "Status report")
    try:
        # RAM
        mem_result = run("free -m", check=False)
        ram_total = ram_avail = "?"
        for line in mem_result.stdout.splitlines():
            if line.startswith("Mem:"):
                parts = line.split()
                ram_total = parts[1]
                ram_avail = parts[6] if len(parts) > 6 else parts[3]

        # Swap
        swap_total = swap_used = "?"
        for line in mem_result.stdout.splitlines():
            if line.startswith("Swap:"):
                parts = line.split()
                swap_total = parts[1]
                swap_used = parts[2]

        # Instance type
        instance_type = _get_metadata_instance_type()

        # Gateway status
        gw_result = run("systemctl is-active openclaw-gateway", check=False)
        gw_status = gw_result.stdout.strip() if gw_result.stdout else "unknown"

        # Config profile
        config_profile = "unknown"
        if OPENCLAW_CONFIG.exists():
            try:
                cfg = json.loads(OPENCLAW_CONFIG.read_text())
                config_profile = cfg.get("profile", cfg.get("name", "default"))
            except Exception:
                config_profile = "parse-error"

        print()
        print("=" * 60)
        print("  DEPLOYMENT STATUS REPORT")
        print("=" * 60)
        print(f"  RAM total:       {ram_total} MB")
        print(f"  RAM available:   {ram_avail} MB")
        print(f"  Swap total:      {swap_total} MB")
        print(f"  Swap used:       {swap_used} MB")
        print(f"  Instance type:   {instance_type}")
        print(f"  Gateway status:  {gw_status}")
        print(f"  Config profile:  {config_profile}")
        print("=" * 60)

        if critical_failures:
            print()
            print("  CRITICAL FAILURES:")
            for cf in critical_failures:
                print(f"    - {cf}")
            print()
        else:
            print("  All critical steps passed.")
        print()

    except Exception as exc:
        fail(str(exc), critical=False)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    print("=" * 60)
    print("  deploy_t3medium.py - Post-resize deployment")
    print("=" * 60)

    step_1_verify_ram()
    step_2_expand_swap()
    step_3_update_systemd_memory()
    step_4_relax_context_pruning()
    step_5_deploy_onboarding()
    step_6_update_memory_md()
    step_7_clear_sessions()
    step_8_restart_gateway()
    step_9_status_report()

    if critical_failures:
        print(f"RESULT: FAILED ({len(critical_failures)} critical failure(s))")
        return 1

    print("RESULT: SUCCESS - deployment complete")
    return 0


if __name__ == "__main__":
    sys.exit(main())
