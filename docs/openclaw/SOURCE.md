# OpenClaw Source Code Reference

All source code lives in the `openbot/` package. Zero external dependencies (stdlib only).

---

## Module Overview

| Module | File | Purpose |
|--------|------|---------|
| Package | `openbot/__init__.py` | Package init, exports Receipt, ReceiptWriter, Runner, PolicyLoader |
| CLI | `openbot/cli.py` | Argument parsing, command dispatch, doctor report |
| Runner | `openbot/runner.py` | Full run lifecycle: clone, setup, test, health, receipt |
| Receipts | `openbot/receipts.py` | Receipt builder, schema validation, quarantine |
| Policy | `openbot/policy.py` | Load protected_paths, escalation_rules, receipt_schema |
| Utils | `openbot/utils.py` | Commands, logging, SSM helpers, file ops |
| Self-test | `openbot/selftest.py` | 15 self-tests covering receipts, validation, parsing |

---

## openbot/__init__.py

```python
"""
Openbot - Automation Platform Runtime

A minimal automation runtime for running tests, capturing logs,
and producing machine-readable receipt JSON files.
"""

__version__ = "0.1.0"
__author__ = "Openbot Team"

from openbot.receipts import Receipt, ReceiptWriter
from openbot.runner import Runner
from openbot.policy import PolicyLoader

__all__ = ["Receipt", "ReceiptWriter", "Runner", "PolicyLoader", "__version__"]
```

---

## openbot/cli.py

CLI entry point with commands:

- **`openbot doctor [--local]`** - Environment health checks (binaries, directories, policies, liveness)
- **`openbot run`** - Execute test run against target repository
- **`openbot ssm verify`** - Check AWS SSM prerequisites
- **`openbot ssm connect`** - Generate SSM session command
- **`openbot ssm run`** - Execute remote command via SSM

### Doctor Command

Checks:
1. Required binaries (`git`, `python3`)
2. Writable directories (logs, receipts, workdir)
3. Policy loading (protected_paths, escalation_rules, receipt_schema)
4. Liveness diagnostics:
   - Stale workdirs (older than 2 hours)
   - Disk space (< 100MB = UNHEALTHY, < 500MB = warning)
   - Running openbot processes
   - Systemd service status

Status levels: `HEALTHY` | `DEGRADED` | `UNHEALTHY`

Exit codes: `0` (HEALTHY), `1` (DEGRADED), `2` (UNHEALTHY)

### Run Command

Arguments:
- `--target-repo` (required) - Git repository URL
- `--target-branch` (required) - Branch to checkout
- `--command` (required) - Test command to execute
- `--setup-command` (optional) - Run before tests
- `--health-url` (optional) - Health check URL
- `--local` - Use local paths (./logs, ./receipts, ./workdir)
- `--workdir`, `--logs-dir`, `--receipts-dir` - Override paths

### SSM Commands

- `openbot ssm verify [--instance-id ID] [--region REGION]`
- `openbot ssm connect INSTANCE_ID [--region REGION] [--skip-verify]`
- `openbot ssm run INSTANCE_ID -c "COMMAND" [--region REGION] [--timeout SECS] [--json]`

---

## openbot/runner.py

Full run lifecycle:

```
1. git clone --branch <branch> <repo> target
2. Run setup_command (optional, 600s timeout)
3. Run test command (600s timeout)
4. Parse pytest output for pass/fail counts
5. Health check URL (optional, 30s timeout)
6. Validate receipt against schema
7. Write receipt JSON (or quarantine if invalid)
8. Cleanup workdir
```

Key classes:
- `Runner` - Orchestrates the full run
- `parse_pytest_output()` - Extracts pass/fail counts from pytest output
- `load_credentials()` - Loads credentials from `/etc/openbot/credentials`
- `get_authenticated_url()` - Converts GitHub URL to authenticated URL

Credential handling:
- Credentials loaded from `/etc/openbot/credentials` (KEY=VALUE format)
- Supports `DNA_REPO_TOKEN` for private repo access
- **Never logs token URLs** - always logs the public URL

---

## openbot/receipts.py

Receipt creation and validation:

### Receipt class (builder)

```python
receipt = Receipt()
receipt.set_target(repo, branch, commit_sha)
receipt.set_test_result(command, exit_code, log_path, passed=831, failed=9, runtime_seconds=5.23)
receipt.set_health_result(url, status_code, body_snippet, ok)
receipt.add_error("error message")
receipt.set_policies_loaded(["protected_paths", "escalation_rules", "receipt_schema"])
data = receipt.finalize()  # Returns dict, sets timestamp and overall_status
```

### ReceiptWriter

```python
writer = ReceiptWriter(receipts_dir, schema)
success, path = writer.write(receipt_data)
# If validation fails: (False, quarantine_path)
# If validation passes: (True, receipt_path)
```

### validate_receipt()

Simplified JSON schema validator (no external deps). Checks:
- Required fields present
- `receipt_version` matches `"v1"`
- `run_id` is valid UUID
- `commit_sha` is 40-char hex
- `overall_status` is `"SUCCESS"` or `"FAILED"`
- `test` object has required fields
- `health` object (if present) has required fields
- `errors` is array of strings

---

## openbot/policy.py

Policy loading (Phase 1: loaded but not enforced):

```python
loader = PolicyLoader(policies_dir)  # defaults to ../policies/
loader.load_all()  # Returns True if all loaded

# Access
loader.get_protected_globs()       # ["runtime/**", "openbot/**", ...]
loader.get_escalation_rules()      # List of rule dicts
loader.get_receipt_schema()        # JSON schema dict
loader.get_loaded_policy_names()   # ["protected_paths", "escalation_rules", "receipt_schema"]
loader.get_load_errors()           # List of error strings
```

Includes a simple YAML parser (`_parse_simple_yaml`) for our known formats - no PyYAML dependency needed.

---

## openbot/utils.py

Utility functions:

| Function | Purpose |
|----------|---------|
| `get_timestamp()` | UTC ISO8601 timestamp |
| `generate_run_id()` | UUID4 string |
| `ensure_dir(path)` | mkdir -p, returns bool |
| `is_writable(path)` | Check writability, never raises |
| `safe_path_exists(path)` | Check existence, never raises |
| `find_binary(name)` | `shutil.which()` |
| `run_command(cmd, cwd, timeout)` | subprocess.run with capture |
| `load_json(path)` | Load JSON, returns None on error |
| `save_json(path, data)` | Save JSON, returns bool |
| `truncate_string(s, max_len)` | Truncate to max length |
| `check_aws_cli()` | Check AWS CLI availability |
| `check_ssm_plugin()` | Check Session Manager plugin |
| `ssm_describe_instance()` | Get SSM instance info |
| `ssm_send_command()` | Send command via SSM Run Command |
| `ssm_get_command_output()` | Wait for SSM command output |
| `ssm_start_session_command()` | Generate SSM session CLI command |
| `check_stale_workdirs()` | Find workdirs older than N hours |
| `check_disk_space()` | Get disk usage stats |
| `check_openbot_processes()` | Find running openbot processes |
| `check_systemd_service()` | Check systemd service status |

### Logger class

```python
with Logger(log_path, also_stdout=True) as logger:
    logger.info("message")
    logger.error("message")
    logger.warn("message")
    logger.command(cmd, exit_code, stdout, stderr)
```

Log format: `[timestamp] [LEVEL] message`

Levels: `INFO`, `ERROR`, `WARN`, `CMD`

---

## openbot/selftest.py

15 self-tests:

| Test | What it verifies |
|------|------------------|
| test_receipt_creation | Receipts created with correct fields |
| test_receipt_with_errors | Failed receipts marked FAILED |
| test_schema_loading | Receipt schema loads from policies/ |
| test_receipt_validation_valid | Valid receipts pass validation |
| test_receipt_validation_invalid | Invalid receipts fail validation |
| test_receipt_writer | Receipts written to disk correctly |
| test_quarantine_invalid_receipt | Invalid receipts quarantined |
| test_policy_loading | All 3 policy files load |
| test_protected_paths | Protected globs readable |
| test_doctor_permission_error | Doctor handles PermissionError gracefully |
| test_is_writable_permission_error | is_writable never crashes |
| test_config_example_has_required_keys | Config example has required keys |
| test_config_yaml_parsing | YAML parsing handles quotes/whitespace |
| test_pytest_output_parsing | Pytest output parsed for counts |
| test_receipt_with_pytest_counts | Receipts store pytest counts |

Run with: `python -m openbot.selftest`

---

## pyproject.toml

```toml
[build-system]
requires = ["setuptools>=45", "wheel"]
build-backend = "setuptools.build_meta"

[project]
name = "openbot"
version = "0.1.0"
description = "Openbot Automation Runtime"
readme = "PRD.md"
requires-python = ">=3.8"
license = {text = "MIT"}
dependencies = []  # No runtime dependencies - stdlib only

[project.scripts]
openbot = "openbot.cli:main"
```
