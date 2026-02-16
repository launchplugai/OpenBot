# OpenClaw Scripts Reference

All scripts live in the `scripts/` directory.

---

## clawedbot-install.sh

Safe, auditable installer for OpenBot runtime on EC2. Requires explicit `--yes` flag for any mutating operations.

**Pattern:** READ -> PLAN -> CONFIRM -> EXECUTE

### Usage

```bash
# Check current state (read-only)
./clawedbot-install.sh --print-plan

# Full install
sudo ./clawedbot-install.sh --yes

# Verify only
sudo ./clawedbot-install.sh --doctor-only

# Install without git pull
sudo ./clawedbot-install.sh --yes --no-pull

# Install and enable services
sudo ./clawedbot-install.sh --yes --enable-services
```

### Options

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

### Phases

1. **Preflight Checks** (always runs) - Verifies state without modifying
2. **Mutating Steps** (only with `--yes`) - Creates/fixes user, dirs, venv, wrapper, config, services
3. **Verification** - Runs `openbot doctor` as the openbot user
4. **Services** (only with `--enable-services --yes`) - Enables systemd services
5. **Receipt** - Writes installation receipt

See [INSTALLER.md](INSTALLER.md) for full documentation.

---

## install.sh

Simpler installation script for initial setup:

```bash
sudo ./scripts/install.sh
```

Steps:
1. Install system dependencies (git, python3, python3-pip, curl)
2. Create `openbot` system user
3. Create directories (`/var/lib/openbot/{logs,receipts,workdir}`)
4. Sync repo to `/opt/openbot`
5. Create venv and install openbot package
6. Create `/usr/local/bin/openbot` wrapper
7. Install systemd services
8. Set up config at `/etc/openbot/config.yaml`

---

## openbot-run

Config-driven run wrapper for systemd. Reads `/etc/openbot/config.yaml` and executes `openbot run`.

```bash
/usr/local/bin/openbot-run
```

Parses these config keys:
- `target_repo` (required)
- `target_branch` (required)
- `command` (required)
- `setup_command` (optional)
- `health_url` (optional)

Includes `parse_yaml_value()` function for simple YAML parsing (handles quoted values, whitespace).

Environment variable `OPENBOT_CONFIG` can override the config file path (default: `/etc/openbot/config.yaml`).

---

## run_once.sh

Manual run wrapper for quick one-off executions:

```bash
# Basic usage
./scripts/run_once.sh <target-repo> <target-branch> "<command>"

# With health check
./scripts/run_once.sh https://github.com/org/repo main "pytest" "http://localhost:8080/health"

# With custom directories
OPENBOT_HOME=/tmp/openbot ./scripts/run_once.sh https://github.com/org/repo main "make test"
```

Environment variables:
- `OPENBOT_HOME` - Base directory (default: `/var/lib/openbot`)
- `LOGS_DIR` - Logs directory
- `RECEIPTS_DIR` - Receipts directory
- `WORKDIR` - Work directory
