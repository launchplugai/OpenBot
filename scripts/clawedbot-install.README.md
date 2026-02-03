# Clawedbot/Openbot Installer

Safe, auditable installer for OpenBot runtime on EC2 instances.

## Overview

This installer follows a **READ → PLAN → CONFIRM → EXECUTE** pattern:

- **Without `--yes`**: Only runs checks and prints what would be done
- **With `--yes`**: Executes mutating operations
- **With `--print-plan`**: Shows planned actions and exits

## Quick Start

```bash
# 1. Check current state (read-only)
./clawedbot-install.sh --print-plan

# 2. Run full install
sudo ./clawedbot-install.sh --yes

# 3. Verify
sudo ./clawedbot-install.sh --doctor-only
```

## Fixed Paths

The installer uses these canonical paths (not configurable):

| Component    | Path                                    |
|--------------|----------------------------------------|
| Repo         | `/opt/openbot`                         |
| Venv         | `/var/lib/openbot/venv`                |
| Config       | `/etc/openbot/config.yaml`             |
| Credentials  | `/etc/openbot/credentials.yaml`        |
| Logs         | `/var/lib/openbot/logs`                |
| Receipts     | `/var/lib/openbot/receipts`            |
| Workdir      | `/var/lib/openbot/workdir`             |
| Wrapper      | `/usr/local/bin/openbot`               |
| Run Wrapper  | `/usr/local/bin/openbot-run`           |

## Command-Line Options

```
--help              Show help message
--print-plan        Print planned actions and exit (no changes)
--yes               Execute mutating steps (REQUIRED for changes)
--no-pull           Skip git fetch/pull
--doctor-only       Only run doctor check, no installs
--enable-services   Enable and start systemd services (requires --yes)
--config PATH       Config file path (default: /etc/openbot/config.yaml)
--credentials PATH  Credentials file path (default: /etc/openbot/credentials.yaml)
```

## Installation Phases

### Phase 1: Preflight Checks (always runs)

Verifies without modifying:

- `/opt/openbot` exists and is a git repo
- `/var/lib/openbot` directory exists
- `/var/lib/openbot/venv` exists with working Python
- `/usr/local/bin/openbot` wrapper has correct content
- `/etc/openbot/` directory exists
- Config and credentials files exist
- `openbot` system user exists
- `openbot` package is installed in venv

### Phase 2: Mutating Steps (only with `--yes`)

Creates/fixes as needed:

1. Creates `openbot` user if missing
2. Creates directories with correct ownership:
   - `/var/lib/openbot/{logs,receipts,workdir}`
   - `/etc/openbot/`
3. Creates venv at `/var/lib/openbot/venv` if missing
4. Runs `git pull --ff-only` (unless `--no-pull`)
5. Installs openbot package: `pip install -e /opt/openbot`
6. Writes/fixes wrapper at `/usr/local/bin/openbot`
7. Copies config template if missing (NOT credentials)
8. Installs systemd service files

### Phase 3: Verification

Runs after mutating steps:

- Executes `openbot doctor` as the `openbot` user
- Verifies wrapper uses correct venv path
- Confirms all paths are absolute (no `--local` mode)

### Phase 4: Services (only with `--enable-services --yes`)

If explicitly requested:

- `systemctl daemon-reload`
- `systemctl enable openbot.service openbot-run.service`
- Shows service status

**Note:** Services are NOT enabled by default. They are oneshot services
that should be triggered manually or via cron/scheduler.

### Phase 5: Receipt

Writes installation receipt to `/var/lib/openbot/receipts/install_*.json`
containing timestamp, flags used, and paths configured.

## Usage Examples

### Check Current State

```bash
# Non-root is fine for checks
./clawedbot-install.sh --print-plan
```

Output shows what's configured correctly and what needs fixing.

### Fresh Install on New EC2

```bash
# Prerequisites: Clone repo first
sudo git clone https://github.com/launchplugai/openbot /opt/openbot

# Run installer
sudo /opt/openbot/scripts/clawedbot-install.sh --yes

# Edit config
sudo vim /etc/openbot/config.yaml

# Create credentials (if needed for private repos)
sudo vim /etc/openbot/credentials.yaml

# Test
sudo systemctl start openbot-run
journalctl -u openbot-run --no-pager
```

### Update Existing Installation

```bash
# Pull latest and reinstall
sudo /opt/openbot/scripts/clawedbot-install.sh --yes

# Skip git pull (use current code)
sudo /opt/openbot/scripts/clawedbot-install.sh --yes --no-pull
```

### Just Verify Doctor

```bash
sudo /opt/openbot/scripts/clawedbot-install.sh --doctor-only
```

### Enable Services (use with caution)

```bash
# Services run tests automatically - only enable if intended
sudo /opt/openbot/scripts/clawedbot-install.sh --yes --enable-services
```

## Wrapper Script Content

The `/usr/local/bin/openbot` wrapper MUST contain exactly:

```bash
#!/bin/bash
exec /var/lib/openbot/venv/bin/python -m openbot.cli "$@"
```

If the wrapper has different content (e.g., pointing to wrong venv),
the installer will backup the old version and write the correct one.

## Credentials

**The installer does NOT create or modify credentials.**

You must manually create `/etc/openbot/credentials.yaml` with your tokens:

```yaml
# /etc/openbot/credentials.yaml
github_token: "ghp_your_token_here"
```

Set proper permissions:

```bash
sudo chown root:openbot /etc/openbot/credentials.yaml
sudo chmod 640 /etc/openbot/credentials.yaml
```

## Troubleshooting

### "Not running as root"

Mutating operations require root:

```bash
sudo ./clawedbot-install.sh --yes
```

### "Repo missing or not a git repo"

Clone the repo first:

```bash
sudo git clone https://github.com/launchplugai/openbot /opt/openbot
```

### "Wrapper content incorrect"

The installer will fix this automatically with `--yes`:

```bash
sudo ./clawedbot-install.sh --yes
```

### "Doctor check failed"

Check the doctor output for specific issues:

```bash
sudo -u openbot /usr/local/bin/openbot doctor
```

Common issues:
- Directories not writable by openbot user
- Missing Python dependencies
- Broken venv

### Services won't start

Check journal:

```bash
journalctl -u openbot-run -n 50 --no-pager
```

Common issues:
- Config file not edited (still has example values)
- Credentials missing or wrong
- Target repo authentication failed

## Security Notes

1. **Services are disabled by default** - Enable only when ready
2. **Credentials are never auto-created** - User must provide
3. **Config template has no secrets** - Safe to commit
4. **Wrapper is root-owned** - Prevents tampering
5. **Data dirs are openbot-owned** - Least privilege
6. **Config is root:openbot 640** - Only openbot can read

## File Permissions Summary

```
/opt/openbot/              root:root     755  (repo)
/var/lib/openbot/          openbot:openbot 750  (data)
/var/lib/openbot/venv/     openbot:openbot 755  (venv)
/var/lib/openbot/logs/     openbot:openbot 755  (logs)
/var/lib/openbot/receipts/ openbot:openbot 755  (receipts)
/var/lib/openbot/workdir/  openbot:openbot 755  (workdir)
/etc/openbot/              root:openbot  750  (config dir)
/etc/openbot/config.yaml   root:openbot  640  (config)
/etc/openbot/credentials.yaml root:openbot 640  (credentials)
/usr/local/bin/openbot     root:root     755  (wrapper)
```
