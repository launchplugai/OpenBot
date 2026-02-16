# OpenClaw Configuration Reference

## Configuration Files

OpenClaw uses YAML configuration files stored at `/etc/openbot/`.

---

## config.template.yaml

Full template with documentation for all options:

```yaml
# =============================================================================
# Openbot/Clawedbot Configuration Template
# =============================================================================
#
# This file configures the openbot-run service.
#
# Installation:
#   sudo cp /opt/openbot/runtime/config.template.yaml /etc/openbot/config.yaml
#   sudo chown root:openbot /etc/openbot/config.yaml
#   sudo chmod 640 /etc/openbot/config.yaml
#   sudo vim /etc/openbot/config.yaml  # Edit values below
#
# Usage:
#   sudo systemctl start openbot-run
#   journalctl -u openbot-run --no-pager
#
# =============================================================================

# -----------------------------------------------------------------------------
# REQUIRED: Target Repository
# -----------------------------------------------------------------------------

# Git repository URL to clone and test
# Examples:
#   - Public repo:  https://github.com/org/repo
#   - Private repo: https://github.com/org/private-repo
#     (requires credentials in /etc/openbot/credentials.yaml)
target_repo: "https://github.com/CHANGE_ME/CHANGE_ME"

# Git branch to checkout
target_branch: "main"

# -----------------------------------------------------------------------------
# REQUIRED: Test Command
# -----------------------------------------------------------------------------

# Command to execute after cloning the repository
# This runs in the cloned repo's root directory
#
# Examples:
#   - Python:   /var/lib/openbot/venv/bin/python -m pytest tests -v
#   - Node:     npm test
#   - Make:     make test
#   - Shell:    ./run_tests.sh
command: "echo 'CHANGE_ME: Set your test command here'"

# -----------------------------------------------------------------------------
# OPTIONAL: Setup Command
# -----------------------------------------------------------------------------

# Command to run before the test command (e.g., install dependencies)
# Runs in the cloned repo's root directory
#
# Examples:
#   - Python:   /var/lib/openbot/venv/bin/pip install -r requirements.txt
#   - Node:     npm install
#   - Make:     make setup
#
# Uncomment and edit:
# setup_command: "/var/lib/openbot/venv/bin/pip install -r requirements.txt"

# -----------------------------------------------------------------------------
# OPTIONAL: Health Check URL
# -----------------------------------------------------------------------------

# URL to check after tests complete (e.g., verify service is running)
# The test passes if this URL returns HTTP 200
#
# Examples:
#   - Local:    http://localhost:8080/health
#   - Remote:   https://api.example.com/status
#
# Uncomment and edit:
# health_url: "http://localhost:8080/health"

# -----------------------------------------------------------------------------
# NOTES
# -----------------------------------------------------------------------------
#
# Credentials:
#   For private repositories, create /etc/openbot/credentials.yaml:
#
#     github_token: "ghp_your_personal_access_token"
#
#   Then set permissions:
#     sudo chown root:openbot /etc/openbot/credentials.yaml
#     sudo chmod 640 /etc/openbot/credentials.yaml
#
# Data Directories:
#   - Logs:     /var/lib/openbot/logs/<run_id>.log
#   - Receipts: /var/lib/openbot/receipts/<run_id>.json
#   - Workdir:  /var/lib/openbot/workdir/<run_id>/target/
#
# Testing your config:
#   # Dry run (check config syntax)
#   sudo -u openbot /usr/local/bin/openbot doctor
#
#   # Manual run
#   sudo systemctl start openbot-run
#   journalctl -u openbot-run --no-pager
#
#   # Check latest receipt
#   ls -t /var/lib/openbot/receipts/*.json | head -1 | xargs cat
#
# =============================================================================
```

---

## config.example.yaml

Minimal example:

```yaml
# Required: Git repository URL to clone
target_repo: "https://github.com/octocat/Hello-World"

# Required: Git branch to checkout
target_branch: "master"

# Optional: Setup command (e.g., install dependencies)
# setup_command: "npm install"

# Required: Test command to execute
command: "ls -la"

# Optional: Health check URL (uncomment to enable)
# health_url: "http://localhost:8080/health"
```

---

## config.dna-sherlock.yaml

DNA Matrix (Sherlock) specific configuration:

```yaml
# Repository to clone (READ-ONLY - Openbot never pushes)
target_repo: "https://github.com/launchplugai/DNA"

# Branch to checkout
target_branch: "main"

# Setup command (install dependencies + editable dna-matrix package)
setup_command: "pip install -r requirements.txt && pip install -e ./dna-matrix"

# Test command to execute
# Note: pytest app/tests -v avoids dormant module errors
command: "pytest app/tests -v"

# Optional: Health check URL (uncomment to enable)
# The server must be running for this to work
# See docs/sprints/S1-03 for health check setup
# health_url: "http://localhost:8000/health"
```

---

## Fixed Paths (EC2 Deployment)

```
/opt/openbot                         # Git repo
/var/lib/openbot/venv                # Python virtualenv
/var/lib/openbot/{logs,receipts,workdir}  # Runtime data
/etc/openbot/config.yaml             # Run configuration
/etc/openbot/credentials             # Auth tokens (never logged)
/usr/local/bin/openbot               # CLI wrapper
/usr/local/bin/openbot-run           # Config-driven run script
```

## Credentials

**The installer does NOT create or modify credentials.**

Create `/etc/openbot/credentials.yaml` manually:

```yaml
# /etc/openbot/credentials.yaml
github_token: "ghp_your_token_here"
```

Set permissions:

```bash
sudo chown root:openbot /etc/openbot/credentials.yaml
sudo chmod 640 /etc/openbot/credentials.yaml
```
