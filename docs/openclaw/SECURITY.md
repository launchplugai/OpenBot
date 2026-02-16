# Openbot Security Model

## Overview

Openbot is designed with security as a primary concern. This document describes the security model and guarantees.

## Access Model

### SSM-Only Access

Openbot instances are accessed exclusively via AWS Systems Manager (SSM) Session Manager.

**Why SSM?**
- No open inbound ports required
- No SSH keys to manage or rotate
- All sessions are logged to CloudTrail
- IAM-based access control
- Encrypted communication

**SSH is explicitly NOT supported**:
- Port 22 should be closed in security groups
- No SSH keys should be present on instances
- No `authorized_keys` files

### IAM Role-Based Access

Instances run with an IAM instance profile that provides:
- Minimal permissions required for operation
- No long-lived AWS credentials
- Automatic credential rotation

**Required IAM permissions**:
```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "ssm:UpdateInstanceInformation",
        "ssmmessages:CreateControlChannel",
        "ssmmessages:CreateDataChannel",
        "ssmmessages:OpenControlChannel",
        "ssmmessages:OpenDataChannel"
      ],
      "Resource": "*"
    }
  ]
}
```

## What Openbot WILL NOT Do

### Phase 1 Explicit Non-Goals

1. **Will NOT deploy to production**
   - Openbot only runs tests and produces reports
   - No deployment commands will be executed
   - No infrastructure changes will be made

2. **Will NOT store secrets**
   - No AWS keys in files or environment
   - No database credentials
   - No API tokens
   - Secrets management is out of scope for Phase 1

3. **Will NOT access the internet beyond git clone**
   - Only outbound traffic is to clone repositories
   - Optional health checks to specified URLs
   - No arbitrary network access

4. **Will NOT modify protected paths**
   - `policies/` directory is protected
   - `openbot/` source is protected
   - `runtime/` configuration is protected
   - See `policies/protected_paths.yaml` for full list

5. **Will NOT run with elevated privileges**
   - Runs as unprivileged `openbot` user
   - No sudo access
   - No capability escalation

6. **Will NOT auto-trigger**
   - Phase 1 is manual execution only
   - No webhooks, no cron, no external triggers
   - All runs are explicitly initiated

## Safe Defaults

### Fail Closed

When in doubt, Openbot fails safely:
- Missing permissions → abort
- Invalid receipt → quarantine
- Network timeout → fail with clear error
- Unknown error → fail and log stack trace

### Minimal Dependencies

- Only Python standard library used
- No external PyPI packages
- Reduces supply chain attack surface

### Isolated Execution

- Each run gets a unique run_id
- Workdir is isolated per run
- Logs and receipts are immutable after write

## Credential Handling

### Do NOT

- Store AWS credentials in files
- Pass credentials as command arguments
- Log credentials in any form
- Use long-lived access keys

### Do

- Rely on IAM instance profiles
- Use SSM for secure access
- Rotate any temporary credentials
- Audit all access via CloudTrail

## Audit Trail

Every run produces:
1. **Log file** - detailed execution log
2. **Receipt JSON** - structured run summary
3. **CloudTrail entries** - SSM session logs (AWS-managed)

Receipt fields for audit:
- `run_id` - unique identifier
- `timestamp` - when run completed
- `commit_sha` - exact code version tested
- `test.command` - exact command executed
- `test.exit_code` - execution result

## Network Security

### Recommended Security Group

```
Inbound: NONE (all ports closed)
Outbound:
  - 443 (HTTPS) - for SSM, git clone
  - 80 (HTTP) - optional, for health checks
```

### No Public IP Required

Instances can run in private subnets with:
- VPC endpoints for SSM
- NAT gateway for git clone (if needed)
- No direct internet exposure

## Incident Response

### If Compromise Suspected

1. Terminate the instance immediately
2. Preserve logs:
   ```bash
   aws s3 cp /var/lib/openbot/logs/ s3://backup-bucket/incident/
   aws s3 cp /var/lib/openbot/receipts/ s3://backup-bucket/incident/
   ```
3. Review CloudTrail for SSM session history
4. Rotate any credentials that may have been exposed

### Receipt Integrity

If receipts are suspected of tampering:
1. Check quarantine directory for validation failures
2. Compare timestamps across log files
3. Review for any gaps in run_id sequence

## Future Security Enhancements (Phase 2+)

- Receipt signing with AWS KMS
- Automated security scanning of test outputs
- Integration with AWS Security Hub
- Anomaly detection for unusual runs
