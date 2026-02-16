# OpenClaw / OpenBot - SOUL

## What This Is

OpenBot (deployed as **Clawedbot** / **OpenClaw** on EC2) is a minimal automation runtime that clones repositories, runs test commands, performs optional health checks, and produces machine-readable receipt JSON files. Every run is auditable, every failure is recorded.

## Architecture

```
CLI (openbot)
  |
  +-- doctor        # Environment health diagnostics
  +-- run            # Clone repo -> setup -> test -> health check -> receipt
  +-- ssm verify     # Check AWS SSM prerequisites
  +-- ssm connect    # Generate SSM session command
  +-- ssm run        # Execute remote command via SSM
```

### Core Modules

| Module | File | Purpose |
|--------|------|---------|
| CLI | `openbot/cli.py` | Argument parsing, command dispatch, doctor report |
| Runner | `openbot/runner.py` | Full run lifecycle: clone, setup, test, health, receipt |
| Receipts | `openbot/receipts.py` | Receipt builder, schema validation, quarantine |
| Policy | `openbot/policy.py` | Load protected_paths, escalation_rules, receipt_schema |
| Utils | `openbot/utils.py` | Commands, logging, SSM helpers, file ops |
| Self-test | `openbot/selftest.py` | 15 self-tests covering receipts, validation, parsing |
| Installer | `scripts/clawedbot-install.sh` | EC2 deployment: user, venv, wrapper, systemd |
| Run wrapper | `scripts/openbot-run` | Config-driven wrapper for systemd oneshot |

### Fixed Paths (EC2 Deployment)

```
/opt/openbot                         # Git repo
/var/lib/openbot/venv                # Python virtualenv
/var/lib/openbot/{logs,receipts,workdir}  # Runtime data
/etc/openbot/config.yaml             # Run configuration
/etc/openbot/credentials             # Auth tokens (never logged)
/usr/local/bin/openbot               # CLI wrapper
/usr/local/bin/openbot-run           # Config-driven run script
```

### Policies (`policies/`)

- `protected_paths.yaml` - Globs that must not be modified
- `escalation_rules.yaml` - What to do on test failure, permission error, health fail
- `receipt_schema_v1.json` - JSON schema for receipt validation

## Data Flow

```
config.yaml -> openbot-run -> openbot run
  1. git clone --branch <branch> <repo>
  2. Run setup_command (optional, 600s timeout)
  3. Run test command (600s timeout)
  4. Parse pytest output for pass/fail counts
  5. Health check URL (optional, 30s timeout)
  6. Validate receipt against schema
  7. Write receipt JSON (or quarantine if invalid)
  8. Cleanup workdir
```

## Receipt Structure

Every run produces a receipt at `/var/lib/openbot/receipts/<run_id>.json`:

```json
{
  "receipt_version": "v1",
  "timestamp": "2026-02-16T00:00:00Z",
  "run_id": "uuid",
  "target_repo": "https://github.com/org/repo",
  "target_branch": "main",
  "commit_sha": "abc123...",
  "test": {
    "command": "pytest",
    "exit_code": 0,
    "summary": "passed",
    "log_path": "/var/lib/openbot/logs/<run_id>.log",
    "passed": 831,
    "failed": 9,
    "runtime_seconds": 5.23,
    "setup_command": "pip install -r requirements.txt"
  },
  "health": {
    "url": "http://localhost:8080/health",
    "status_code": 200,
    "body_snippet": "OK",
    "ok": true
  },
  "overall_status": "SUCCESS",
  "errors": [],
  "policies_loaded": ["protected_paths", "escalation_rules", "receipt_schema"]
}
```

## Diagnostics: `openbot doctor`

The doctor command checks environment health and outputs structured JSON:

```json
{
  "report_type": "doctor",
  "checks": {
    "binaries": { "git": {"found": true}, "python3": {"found": true} },
    "directories": { "logs": {"writable": true}, "receipts": {"writable": true} },
    "policies": { "loaded": ["protected_paths", "escalation_rules", "receipt_schema"] },
    "liveness": { "stale_workdirs": 0, "disk_available_mb": 5120 }
  },
  "overall_status": "HEALTHY | DEGRADED | UNHEALTHY"
}
```

**Status meanings:**
- `HEALTHY` - All checks pass
- `DEGRADED` - Policies failed to load or liveness warnings
- `UNHEALTHY` - Missing binaries, unwritable directories, or liveness failures

## Unresponsive Diagnostics

When OpenClaw becomes unresponsive, the doctor command checks:

1. **Stale workdirs** - Workdirs older than 2 hours indicate hung/abandoned runs
2. **Disk space** - Less than 100MB available triggers UNHEALTHY
3. **Process liveness** - Detects zombie openbot processes
4. **Service status** - Checks systemd unit state (when running as service)

Run diagnostics remotely via SSM:
```bash
openbot ssm run <instance-id> --command "openbot doctor"
openbot ssm verify --instance-id <instance-id>
```

## Timeouts

| Operation | Timeout | On Timeout |
|-----------|---------|------------|
| Setup command | 600s | exit_code=-1, receipt FAILED |
| Test command | 600s | exit_code=-1, receipt FAILED |
| Health check | 30s | health.ok=false, run continues |
| SSM send command | 30s | Error returned |
| SSM poll output | 60s (configurable) | Timeout error |
| AWS CLI version | 10s | Error returned |

## Error Handling Principles

- **Never crash silently.** Every failure is recorded in the receipt's `errors` array.
- **Never expose credentials.** Git clone logs the public URL, not the token URL.
- **Always produce a receipt.** Even on unexpected exceptions, a FAILED receipt is written.
- **Quarantine invalid receipts.** Schema validation failures go to `receipts/quarantine/`.
- **Safe path operations.** `is_writable()` and `safe_path_exists()` never raise exceptions.
- **Fallback log paths.** Doctor reports try primary dir, then `/tmp`, then `.`.

## Escalation Rules

| Rule | Trigger | Severity | Action |
|------|---------|----------|--------|
| test_failure | exit_code != 0 | high | log_and_fail |
| missing_permissions | dirs not writable | critical | abort |
| receipt_validation_failed | schema invalid | critical | quarantine |
| git_clone_failed | clone fails | high | log_and_fail |
| health_check_failed | non-2xx | medium | log_and_continue |

## Running

```bash
# Local development
openbot doctor --local
openbot run --target-repo <url> --target-branch <branch> --command "pytest" --local

# EC2 deployment
sudo clawedbot-install.sh --yes
sudo -u openbot openbot doctor
sudo systemctl start openbot-run

# Remote diagnostics
openbot ssm verify --instance-id i-abc123
openbot ssm run i-abc123 -c "openbot doctor"

# Self-tests
python -m openbot.selftest
```
