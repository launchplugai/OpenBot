# Openbot Operations Guide

## Overview

This document describes how to operate Openbot in Phase 1 (manual execution mode).

## Prerequisites

- Ubuntu EC2 instance (tested on Ubuntu 20.04+)
- SSM access configured (no SSH required)
- Git installed
- Python 3.8+ installed

## Installation

### On EC2 via SSM

```bash
# Connect via SSM
aws ssm start-session --target i-xxxxxxxxxxxx

# Clone the openbot repo
cd /opt
sudo git clone https://github.com/launchplugai/openbot.git
cd openbot

# Run installation
sudo ./scripts/install.sh
```

### Local Development

```bash
# Clone repo
git clone https://github.com/launchplugai/openbot.git
cd openbot

# No installation needed - run directly
python -m openbot.cli doctor --local
```

## Commands

### Doctor Command

Checks runtime environment health.

```bash
# System paths (requires installation)
openbot doctor

# Local paths (development)
python -m openbot.cli doctor --local
```

**Output**: JSON report to stdout + log file

**Exit codes**:
- `0`: HEALTHY - all checks passed
- `1`: DEGRADED - some non-critical issues
- `2`: UNHEALTHY - critical issues found

**Example output**:
```json
{
  "report_type": "doctor",
  "timestamp": "2024-01-15T10:30:00Z",
  "run_id": "abc123...",
  "checks": {
    "binaries": {
      "git": {"found": true, "path": "/usr/bin/git"},
      "python3": {"found": true, "path": "/usr/bin/python3"}
    },
    "directories": {
      "logs": {"path": "./logs", "writable": true, "exists": true},
      "receipts": {"path": "./receipts", "writable": true, "exists": true},
      "workdir": {"path": "./workdir", "writable": true, "exists": true}
    },
    "policies": {
      "loaded": ["protected_paths", "escalation_rules", "receipt_schema"],
      "errors": []
    }
  },
  "errors": [],
  "overall_status": "HEALTHY"
}
```

### Run Command

Executes a test run against a target repository.

```bash
# Full syntax
python -m openbot.cli run \
  --target-repo https://github.com/org/repo \
  --target-branch main \
  --command "npm test" \
  --health-url http://localhost:8080/health \
  --local

# Minimal (local development)
python -m openbot.cli run \
  --target-repo https://github.com/org/repo \
  --target-branch main \
  --command "echo hello" \
  --local
```

**Arguments**:
- `--target-repo` (required): Git repository URL
- `--target-branch` (required): Branch to checkout
- `--command` (required): Test command to execute
- `--health-url` (optional): Health check URL
- `--workdir` (optional): Override working directory
- `--logs-dir` (optional): Override logs directory
- `--receipts-dir` (optional): Override receipts directory
- `--local`: Use local paths (./logs, ./receipts, ./workdir)

**Exit codes**:
- `0`: SUCCESS - tests passed
- `1`: FAILED - tests failed or error occurred

### Using run_once.sh Wrapper

```bash
# Basic usage
./scripts/run_once.sh https://github.com/org/repo main "npm test"

# With health check
./scripts/run_once.sh https://github.com/org/repo main "pytest" "http://localhost:8080/health"

# With custom directories (via environment)
OPENBOT_HOME=/tmp/openbot ./scripts/run_once.sh https://github.com/org/repo main "make test"
```

## Output Locations

### Default Paths (System Installation)

| Type | Path |
|------|------|
| Logs | `/var/lib/openbot/logs/` |
| Receipts | `/var/lib/openbot/receipts/` |
| Workdir | `/var/lib/openbot/workdir/` |

### Local Development Paths

| Type | Path |
|------|------|
| Logs | `./logs/` |
| Receipts | `./receipts/` |
| Workdir | `./workdir/` |

## Reading Receipts

Receipts are JSON files that document every run.

### Receipt Location

```bash
# List recent receipts
ls -lt receipts/ | head -10

# Read a specific receipt
cat receipts/<run-id>.json | jq .
```

### Receipt Structure

```json
{
  "receipt_version": "v1",
  "timestamp": "2024-01-15T10:30:00Z",
  "run_id": "550e8400-e29b-41d4-a716-446655440000",
  "target_repo": "https://github.com/org/repo",
  "target_branch": "main",
  "commit_sha": "abc123def456...",
  "test": {
    "command": "npm test",
    "exit_code": 0,
    "summary": "passed",
    "log_path": "./logs/550e8400-e29b-41d4-a716-446655440000.log"
  },
  "health": null,
  "overall_status": "SUCCESS",
  "errors": [],
  "policies_loaded": ["protected_paths", "escalation_rules", "receipt_schema"]
}
```

### Key Fields

| Field | Description |
|-------|-------------|
| `overall_status` | SUCCESS or FAILED |
| `test.exit_code` | Exit code of test command |
| `test.summary` | "passed" or "failed" |
| `test.log_path` | Path to full log file |
| `errors` | Array of error messages (empty on success) |
| `commit_sha` | Exact commit tested |

### Quarantined Receipts

If a receipt fails schema validation, it's written to `receipts/quarantine/`:

```bash
ls receipts/quarantine/
cat receipts/quarantine/<run-id>_quarantine.json | jq .
```

## Reading Logs

Logs contain detailed execution information.

```bash
# View recent log
cat logs/<run-id>.log

# Follow log format
# [timestamp] [level] message
# Levels: INFO, WARN, ERROR, CMD

# Filter for commands only
grep "\[CMD\]" logs/<run-id>.log

# Filter for errors
grep "\[ERROR\]" logs/<run-id>.log
```

## Troubleshooting

### Doctor Reports UNHEALTHY

1. Check binaries exist:
   ```bash
   which git python3
   ```

2. Check directory permissions:
   ```bash
   ls -la /var/lib/openbot/
   ```

3. Fix permissions:
   ```bash
   sudo chown -R openbot:openbot /var/lib/openbot
   ```

### Git Clone Fails

1. Check network connectivity
2. Verify repository URL is correct
3. Check if repo requires authentication (not supported in Phase 1)

### Test Command Fails

1. Check the log file for details:
   ```bash
   cat logs/<run-id>.log | grep -A 10 "COMMAND:"
   ```

2. Verify command works manually in the workdir:
   ```bash
   cd workdir/target
   <your-command>
   ```

### Receipt Validation Fails

1. Check quarantine directory:
   ```bash
   cat receipts/quarantine/<run-id>_quarantine.json | jq .validation_errors
   ```

2. This indicates a bug in Openbot - please report it.
