# SPRINT 0 — TICKET S0-01: EC2 + SSM TRUST FOUNDATION (NO SSH)

## Goal
Stand up a single AWS EC2 instance that can be administered via AWS Systems Manager (SSM) Session Manager with **zero SSH**, minimal exposure, and auditable access.

This is the foundation for Openbot automation.

---

## Non-Negotiable Constraints
- NO inbound SSH (port 22 closed)
- Prefer NO inbound ports at all for Sprint 0
- All access via AWS SSM Session Manager
- IAM permissions must be least-privilege (start with AWS-managed policy, refine later)
- Success must be observable via console evidence + CLI proof

---

## Deliverables
1. One EC2 instance running (Ubuntu 22.04 LTS or Amazon Linux 2023)
2. Instance is visible in AWS Systems Manager as a **Managed Instance**
3. You can start a Session Manager session to the instance (shell access)
4. Session access produces an auditable record in AWS
5. A minimal bootstrap verification script can run (uname, disk, python, etc.)

---

## Implementation Steps

### Part A — Create IAM Role (Instance Profile)
Create an IAM Role for EC2 with:
- Trusted entity: EC2
- Attach AWS-managed policy: `AmazonSSMManagedInstanceCore`

Name suggestion: `openbot-ec2-ssm-role`

Attach this role as an **instance profile**.

### Part B — Launch EC2 Instance
Launch an instance with:
| Setting | Value |
|---------|-------|
| Type | t3.micro (or similar) |
| OS | Ubuntu 22.04 LTS OR Amazon Linux 2023 |
| Storage | Default (8GB) |
| Security Group Inbound | **NONE** |
| Security Group Outbound | HTTPS (443) |
| IAM Instance Profile | `openbot-ec2-ssm-role` |

Tagging:
```
Name: openbot-runner-01
Project: openbot
Environment: dev
```

### Part C — Verify SSM Connectivity
Verify the instance shows in:
- **AWS Systems Manager → Fleet Manager → Managed nodes**

Status should be: **Managed / Online**

If not online:
1. Confirm instance has outbound internet access (NAT/IGW)
2. Confirm SSM agent is installed/running (most AMIs include it)

### Part D — Connect via Session Manager
From AWS Console:
- EC2 → Instance → Connect → Session Manager

OR

- Systems Manager → Session Manager → Start session

**Proof required** — run and capture output:
```bash
whoami
uname -a
df -h
python3 --version
```

### Part E — Produce Sprint 0 Receipt
Create a receipt artifact containing:
- Instance ID
- Region
- AMI / OS
- Instance type
- Security group inbound rules (should show **none**)
- IAM role name
- Evidence that SSM session works (command outputs)

---

## Acceptance Criteria (Hard Pass/Fail)
- [ ] Instance accessible via Session Manager
- [ ] No SSH inbound open
- [ ] Instance appears as "Managed" in SSM
- [ ] Proof commands run successfully
- [ ] Receipt produced

---

## Out of Scope
- Installing Openbot
- Cloning repos
- Running tests
- Deploying services
- Any CI/CD wiring

---

## Post-Task Report Format (Mandatory)
```
=== S0-01 COMPLETION REPORT ===

## What Was Created
- IAM Role: <name>
- Instance ID: <id>
- Region: <region>
- AMI: <ami-id>
- Instance Type: <type>

## Security Group
Inbound Rules: NONE
Outbound Rules: HTTPS (443)

## SSM Status
Fleet Manager Status: <Managed/Online>

## Proof Commands
$ whoami
<output>

$ uname -a
<output>

$ df -h
<output>

$ python3 --version
<output>

## Issues Encountered
<any issues and resolutions>

## Receipt
{
  "ticket": "S0-01",
  "status": "COMPLETE",
  "instance_id": "i-xxx",
  "region": "us-east-1",
  "ssm_verified": true,
  "ssh_disabled": true
}
```

---

## Notes
If SSM fails to connect, **do NOT add SSH as a workaround**.
Fix networking/permissions instead.
