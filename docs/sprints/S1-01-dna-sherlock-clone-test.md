# SPRINT 1 — TICKET S1-01: DNA SHERLOCK CLONE-AND-TEST RUNNER

## Goal
Implement a deterministic Openbot run that:
- Safely clones the DNA Sherlock repo
- Installs dependencies
- Runs tests in isolation
- Captures proof artifacts (logs + receipt)
- Never modifies the origin repo

This sprint produces the **FIRST real automation behavior**.

---

## Non-Negotiable Constraints
- Openbot MUST treat the origin repo as **READ-ONLY**
- All work happens in a **disposable work directory**
- No SSH, no manual intervention
- No heuristics, no retries, no guessing
- If proof is missing, the run is a **failure**

---

## Authoritative Automation Contract (LOCKED)

| Field | Value |
|-------|-------|
| Repository | https://github.com/launchplugai/DNA |
| Branch | main |
| Setup Command | `pip install -r requirements.txt` |
| Test Command | `pytest app/tests -v` |
| Expected Pass | 831 |
| Expected Fail | 9 (known — test_debug.py) |
| Expected Runtime | ~5 seconds |
| Health Endpoint | `/health` (optional for S1-01) |

---

## Prerequisites
- [ ] S0-01 complete (EC2 + SSM foundation)
- [ ] Openbot installed on EC2 instance (`/opt/openbot`)
- [ ] `/var/lib/openbot/` directories exist with correct permissions

---

## Implementation Steps

### Part A — Install Openbot on EC2
Connect via SSM and run:
```bash
# Clone Openbot repo
sudo git clone https://github.com/launchplugai/openbot.git /opt/openbot
cd /opt/openbot

# Run installer
sudo ./scripts/install.sh

# Verify installation
openbot doctor
```

**Expected output**: JSON report with `overall_status: "HEALTHY"`

### Part B — Configure DNA Sherlock Target
Edit the config file:
```bash
sudo vim /etc/openbot/config.yaml
```

Set contents to:
```yaml
target_repo: "https://github.com/launchplugai/DNA"
target_branch: "main"
command: "pip install -r requirements.txt && pytest app/tests -v"
```

### Part C — Execute First Run
```bash
sudo systemctl start openbot-run
```

OR manual CLI:
```bash
openbot run \
  --target-repo https://github.com/launchplugai/DNA \
  --target-branch main \
  --command "pip install -r requirements.txt && pytest app/tests -v"
```

### Part D — Verify Proof Artifacts

**Check receipt exists:**
```bash
ls -t /var/lib/openbot/receipts/*.json | head -1
cat $(ls -t /var/lib/openbot/receipts/*.json | head -1) | jq .
```

**Check log exists:**
```bash
RECEIPT=$(ls -t /var/lib/openbot/receipts/*.json | head -1)
RUN_ID=$(basename "$RECEIPT" .json)
cat /var/lib/openbot/logs/${RUN_ID}.log | tail -50
```

**Verify receipt contents:**
```bash
cat $(ls -t /var/lib/openbot/receipts/*.json | head -1) | jq '{
  status: .overall_status,
  repo: .target_repo,
  branch: .target_branch,
  exit_code: .test.exit_code,
  commit: .commit_sha
}'
```

### Part E — Verify Origin Not Modified
```bash
# The workdir should contain the clone
ls /var/lib/openbot/workdir/target/

# Origin repo should have no changes (we only clone, never push)
# Verify by checking git remote -v in workdir shows origin as DNA repo
cd /var/lib/openbot/workdir/target && git remote -v
```

---

## Acceptance Criteria (Hard Pass/Fail)

- [ ] `openbot doctor` returns HEALTHY
- [ ] DNA repo cloned to `/var/lib/openbot/workdir/target/`
- [ ] `pip install -r requirements.txt` succeeds
- [ ] `pytest app/tests -v` runs and completes
- [ ] Receipt JSON exists in `/var/lib/openbot/receipts/`
- [ ] Receipt contains:
  - `receipt_version: "v1"`
  - `target_repo: "https://github.com/launchplugai/DNA"`
  - `target_branch: "main"`
  - `commit_sha: "<40-char hex>"`
  - `test.exit_code: 0`
  - `overall_status: "SUCCESS"`
- [ ] Log file exists in `/var/lib/openbot/logs/`
- [ ] Origin repo is **unchanged** (read-only relationship)

---

## Out of Scope
- Health endpoint checking (see S1-03)
- Receipt schema validation testing (see S1-02)
- Automated scheduling
- Alerts or notifications
- Deploying DNA Matrix

---

## Post-Task Report Format (Mandatory)

```
=== S1-01 COMPLETION REPORT ===

## Openbot Installation
- Install path: /opt/openbot
- Doctor status: HEALTHY

## Config
target_repo: https://github.com/launchplugai/DNA
target_branch: main
command: pip install -r requirements.txt && pytest app/tests -v

## Run Results
- Run ID: <uuid>
- Commit SHA: <sha>
- Test exit code: <0|1>
- Overall status: <SUCCESS|FAILED>

## Proof Artifacts
- Receipt: /var/lib/openbot/receipts/<run_id>.json
- Log: /var/lib/openbot/logs/<run_id>.log

## Receipt Contents
{
  "receipt_version": "v1",
  "overall_status": "SUCCESS",
  "target_repo": "https://github.com/launchplugai/DNA",
  "target_branch": "main",
  "commit_sha": "...",
  "test": {
    "command": "...",
    "exit_code": 0,
    "summary": "passed"
  }
}

## Test Output Summary
<last 20 lines of pytest output>

## Issues Encountered
<any issues and resolutions>
```

---

## Troubleshooting

### Git Clone Fails
1. Check network connectivity: `curl -I https://github.com`
2. Verify outbound HTTPS allowed in security group

### pip install Fails
1. Check Python version: `python3 --version` (need 3.10+)
2. Check pip: `/opt/openbot/venv/bin/pip --version`

### pytest Fails with Import Errors
1. Ensure you're running `pytest app/tests -v` (not full suite)
2. Dormant modules will error — this is expected

### Receipt Not Written
1. Check permissions: `ls -la /var/lib/openbot/receipts/`
2. Check openbot user owns directory

---

## Notes
- The 9 failing tests in `test_debug.py` are **expected**
- pytest exits 0 even with expected failures
- `conftest.py` auto-sets `ENV=test` and `DNA_RATE_LIMIT_MODE=ci`
