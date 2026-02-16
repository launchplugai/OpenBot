# OpenClaw Sprint Tickets

---

## S0-01: EC2 + SSM Trust Foundation (No SSH)

**Goal:** Stand up a single AWS EC2 instance administered via SSM Session Manager with zero SSH.

### Deliverables
1. One EC2 instance running (Ubuntu 22.04 LTS or Amazon Linux 2023)
2. Instance visible in AWS Systems Manager as a Managed Instance
3. Session Manager session works (shell access)
4. Auditable session record in AWS
5. Bootstrap verification script runs

### Implementation
- **Part A:** Create IAM Role (`openbot-ec2-ssm-role`) with `AmazonSSMManagedInstanceCore`
- **Part B:** Launch EC2 (t3.micro, no inbound ports, HTTPS outbound only)
- **Part C:** Verify SSM connectivity in Fleet Manager
- **Part D:** Connect via Session Manager, run proof commands
- **Part E:** Produce Sprint 0 receipt

### Acceptance Criteria
- Instance accessible via Session Manager
- No SSH inbound open
- Instance appears as "Managed" in SSM
- Proof commands run successfully
- Receipt produced

---

## S1-01: DNA Sherlock Clone-and-Test Runner

**Goal:** Implement a deterministic Openbot run that safely clones DNA Sherlock repo, installs deps, runs tests, captures proof artifacts, and never modifies origin.

### Automation Contract (LOCKED)

| Field | Value |
|-------|-------|
| Repository | https://github.com/launchplugai/DNA |
| Branch | main |
| Setup Command | `pip install -r requirements.txt` |
| Test Command | `pytest app/tests -v` |
| Expected Pass | 831 |
| Expected Fail | 9 (known - test_debug.py) |
| Expected Runtime | ~5 seconds |

### Implementation
- **Part A:** Install Openbot on EC2 (`sudo ./scripts/install.sh`)
- **Part B:** Configure DNA Sherlock target in `/etc/openbot/config.yaml`
- **Part C:** Execute first run (`sudo systemctl start openbot-run`)
- **Part D:** Verify proof artifacts (receipt + log)
- **Part E:** Verify origin not modified

### Acceptance Criteria
- `openbot doctor` returns HEALTHY
- DNA repo cloned to workdir
- `pip install -r requirements.txt` succeeds
- `pytest app/tests -v` runs and completes
- Receipt JSON exists with all required fields
- Log file exists
- Origin repo unchanged

---

## S1-02: DNA Sherlock Receipt Validation

**Goal:** Validate that receipts are schema-compliant, complete, accurate, and queryable.

### Implementation
- **Part A:** Run self-tests (`python -m openbot.selftest`) - expect 13/13 passed
- **Part B:** Validate existing receipt (JSON, required fields)
- **Part C:** Validate commit SHA format (40-char hex)
- **Part D:** Cross-reference SHA with git HEAD
- **Part E:** Check quarantine directory

### Acceptance Criteria
- Self-tests pass (13/13)
- Latest receipt is valid JSON with all required fields
- `receipt_version` is `"v1"`
- `commit_sha` is 40-char hex matching git HEAD
- `overall_status` is `"SUCCESS"` or `"FAILED"`
- No quarantined receipts

---

## S1-03: DNA Sherlock Health Check Integration

**Goal:** Extend Openbot run to include health endpoint verification after tests pass.

### DNA Matrix Health Endpoint

| Field | Value |
|-------|-------|
| URL | `http://localhost:8000/health` |
| Method | GET |
| Success Status | 200 |
| Response | `{"status": "healthy", ...}` |

### Implementation
- **Part A:** Update config with `health_url: "http://localhost:8000/health"`
- **Part B:** Manual health check test (start uvicorn, curl /health, stop)
- **Part C:** Create health check wrapper (compound command or script)
- **Part D:** Run with health check enabled
- **Part E:** Verify health data in receipt

### Acceptance Criteria (Minimum)
- Run completes successfully
- Receipt written with `overall_status: "SUCCESS"`
- Receipt `health` field is present (even if null)

### Acceptance Criteria (Full)
- `/health` returns 200
- Receipt `health.ok` is `true`
- Receipt `health.status_code` is `200`
- Receipt `health.body_snippet` contains `"healthy"`
- Server process terminated after check
