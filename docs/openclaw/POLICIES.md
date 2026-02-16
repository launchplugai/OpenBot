# OpenClaw Policies Reference

Policies are loaded at runtime and included in receipts. In Phase 1 they are loaded but not enforced. Full enforcement comes in Phase 2.

---

## protected_paths.yaml

Controls which paths should not be modified by automated runs.

```yaml
# Openbot Protected Paths - Phase 1
# These paths should not be modified by automated runs

version: v1

# Protected path patterns (glob syntax)
protected_globs:
  # Core runtime - never modify
  - "runtime/**"
  - "openbot/**"
  - "policies/**"

  # Scripts - manual changes only
  - "scripts/**"

  # Documentation - human-authored
  - "docs/**"
  - "PRD.md"
  - "README.md"

  # Configuration files
  - "*.yaml"
  - "*.json"
  - "requirements.txt"
  - "setup.py"
  - "pyproject.toml"

  # Git internals
  - ".git/**"
  - ".gitignore"

# Paths that are explicitly allowed for write
allowed_write_paths:
  - "logs/**"
  - "receipts/**"
  - "workdir/**"

# Note: In Phase 1, these are loaded but not enforced.
# Full enforcement comes in Phase 2 with the deploy loop.
```

---

## escalation_rules.yaml

Defines when and how to escalate failures.

```yaml
# Openbot Escalation Rules - Phase 1

version: v1

rules:
  - id: test_failure
    description: "Tests failed with non-zero exit code"
    trigger:
      condition: test.exit_code != 0
    severity: high
    action:
      type: log_and_fail
      message: "Test execution failed"
    phase: 1

  - id: missing_permissions
    description: "Required directories not writable"
    trigger:
      condition: doctor.writable_dirs == false
    severity: critical
    action:
      type: abort
      message: "Cannot write to required directories"
    phase: 1

  - id: receipt_validation_failed
    description: "Receipt JSON failed schema validation"
    trigger:
      condition: receipt.valid == false
    severity: critical
    action:
      type: quarantine
      message: "Receipt failed validation, quarantined"
    phase: 1

  - id: git_clone_failed
    description: "Failed to clone target repository"
    trigger:
      condition: git.clone_exit_code != 0
    severity: high
    action:
      type: log_and_fail
      message: "Git clone failed"
    phase: 1

  - id: git_checkout_failed
    description: "Failed to checkout target branch"
    trigger:
      condition: git.checkout_exit_code != 0
    severity: high
    action:
      type: log_and_fail
      message: "Git checkout failed"
    phase: 1

  - id: health_check_failed
    description: "Health check URL returned non-2xx status"
    trigger:
      condition: health.ok == false
    severity: medium
    action:
      type: log_and_continue
      message: "Health check failed but run continues"
    phase: 1

  - id: stale_workdir_detected
    description: "Workdir older than 2 hours found (possible hung run)"
    trigger:
      condition: doctor.liveness.stale_workdirs > 0
    severity: medium
    action:
      type: log_and_continue
      message: "Stale workdirs detected - possible hung or abandoned run"
    phase: 1

  - id: disk_space_critical
    description: "Less than 100MB disk space available"
    trigger:
      condition: doctor.liveness.disk.free_mb < 100
    severity: critical
    action:
      type: abort
      message: "Critically low disk space"
    phase: 1

  - id: instance_unresponsive
    description: "SSM instance ping status is not Online"
    trigger:
      condition: ssm.ping_status != Online
    severity: high
    action:
      type: log_and_fail
      message: "Instance is unresponsive"
    phase: 1

# Future phases will add:
# - Notification rules (Phase 2)
# - Auto-retry rules (Phase 2)
# - Claude escalation (Phase 3)
```

---

## receipt_schema_v1.json

JSON Schema for receipt validation:

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "$id": "https://openbot.local/schemas/receipt_v1.json",
  "title": "Openbot Receipt v1",
  "description": "Schema for Openbot run receipts",
  "type": "object",
  "required": [
    "receipt_version",
    "timestamp",
    "run_id",
    "target_repo",
    "target_branch",
    "commit_sha",
    "test",
    "overall_status",
    "errors"
  ],
  "properties": {
    "receipt_version": {
      "type": "string",
      "const": "v1"
    },
    "timestamp": {
      "type": "string",
      "format": "date-time"
    },
    "run_id": {
      "type": "string",
      "pattern": "^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
    },
    "target_repo": { "type": "string" },
    "target_branch": { "type": "string" },
    "commit_sha": {
      "type": "string",
      "pattern": "^[0-9a-f]{40}$"
    },
    "test": {
      "type": "object",
      "required": ["command", "exit_code", "summary", "log_path"],
      "properties": {
        "command": { "type": "string" },
        "exit_code": { "type": "integer" },
        "summary": { "type": "string", "enum": ["passed", "failed"] },
        "log_path": { "type": "string" },
        "passed": { "type": ["integer", "null"] },
        "failed": { "type": ["integer", "null"] },
        "runtime_seconds": { "type": ["number", "null"] },
        "setup_command": { "type": ["string", "null"] }
      },
      "additionalProperties": false
    },
    "health": {
      "type": ["object", "null"],
      "properties": {
        "url": { "type": "string", "format": "uri" },
        "status_code": { "type": ["integer", "null"] },
        "body_snippet": { "type": ["string", "null"], "maxLength": 500 },
        "ok": { "type": "boolean" },
        "log_path": { "type": ["string", "null"] }
      },
      "required": ["url", "status_code", "ok"],
      "additionalProperties": false
    },
    "overall_status": {
      "type": "string",
      "enum": ["SUCCESS", "FAILED"]
    },
    "errors": {
      "type": "array",
      "items": { "type": "string" }
    },
    "policies_loaded": {
      "type": "array",
      "items": { "type": "string" }
    }
  },
  "additionalProperties": false
}
```

---

## Escalation Summary

| Rule | Trigger | Severity | Action |
|------|---------|----------|--------|
| test_failure | exit_code != 0 | high | log_and_fail |
| missing_permissions | dirs not writable | critical | abort |
| receipt_validation_failed | schema invalid | critical | quarantine |
| git_clone_failed | clone fails | high | log_and_fail |
| health_check_failed | non-2xx | medium | log_and_continue |
| stale_workdir_detected | workdir > 2hrs | medium | log_and_continue |
| disk_space_critical | < 100MB free | critical | abort |
| instance_unresponsive | SSM ping != Online | high | log_and_fail |
