# SPRINT 1 — TICKET S1-03: DNA SHERLOCK HEALTH CHECK INTEGRATION

## Goal
Extend the Openbot run for DNA Sherlock to include health endpoint verification:
- Start the DNA Matrix server after tests pass
- Hit the `/health` endpoint
- Record health status in receipt
- Gracefully handle health check failures

This ticket adds **runtime health verification** to the automation.

---

## Non-Negotiable Constraints
- Health check is **OPTIONAL** — test run should still succeed if health check is skipped
- Health check failure should be **recorded** but not necessarily fail the overall run
- Server must be started and stopped cleanly (no orphan processes)

---

## Prerequisites
- [ ] S1-01 complete (DNA Sherlock clone-and-test works)
- [ ] S1-02 complete (receipts validate correctly)

---

## DNA Matrix Health Endpoint

| Field | Value |
|-------|-------|
| URL | `http://localhost:8000/health` |
| Method | GET |
| Success Status | 200 |
| Success Response | `{"status": "healthy", ...}` |

Alternative endpoint:
| Field | Value |
|-------|-------|
| URL | `http://localhost:8000/build` |
| Method | GET |
| Success Status | 200 |

---

## Implementation Steps

### Part A — Update Config with Health URL
```bash
sudo vim /etc/openbot/config.yaml
```

Update to:
```yaml
target_repo: "https://github.com/launchplugai/DNA"
target_branch: "main"
command: "pip install -r requirements.txt && pytest app/tests -v"
health_url: "http://localhost:8000/health"
```

### Part B — Manual Health Check Test
Before automating, verify the health endpoint works:

```bash
cd /var/lib/openbot/workdir/target

# Install deps if not already
pip install -r requirements.txt

# Start server in background
uvicorn app.main:app --host 0.0.0.0 --port 8000 &
SERVER_PID=$!
sleep 3

# Check health
curl -s http://localhost:8000/health | jq .

# Stop server
kill $SERVER_PID
```

**Expected response:**
```json
{
  "status": "healthy",
  "service": "dna-matrix",
  "version": "0.1.0",
  "environment": "development",
  "git_sha": "...",
  "started_at": "..."
}
```

### Part C — Create Health Check Wrapper Script
Since Openbot's current `--health-url` expects the server to already be running, we need a compound command:

```bash
# Option 1: Compound command in config
command: "pip install -r requirements.txt && pytest app/tests -v && (uvicorn app.main:app --port 8000 & sleep 3 && curl -sf http://localhost:8000/health && pkill -f uvicorn)"
```

**OR** create a test script in the DNA repo (preferred for future):
```bash
# scripts/ci-health-check.sh
#!/bin/bash
uvicorn app.main:app --port 8000 &
PID=$!
sleep 3
curl -sf http://localhost:8000/health
EXIT=$?
kill $PID 2>/dev/null
exit $EXIT
```

### Part D — Run with Health Check
```bash
sudo systemctl start openbot-run
```

OR manual:
```bash
openbot run \
  --target-repo https://github.com/launchplugai/DNA \
  --target-branch main \
  --command "pip install -r requirements.txt && pytest app/tests -v" \
  --health-url "http://localhost:8000/health"
```

**Note:** The current Openbot implementation will attempt to hit the health URL after the command completes. If the server isn't running, it will record the failure but still produce a receipt.

### Part E — Verify Health in Receipt
```bash
RECEIPT=$(ls -t /var/lib/openbot/receipts/*.json | head -1)
cat "$RECEIPT" | jq '.health'
```

**If health check ran:**
```json
{
  "url": "http://localhost:8000/health",
  "status_code": 200,
  "body_snippet": "{\"status\": \"healthy\", ...",
  "ok": true,
  "log_path": null
}
```

**If health check failed/skipped:**
```json
null
```

---

## Acceptance Criteria (Hard Pass/Fail)

### Minimum (Health Check Optional)
- [ ] Openbot run completes successfully (tests pass)
- [ ] Receipt is written with `overall_status: "SUCCESS"`
- [ ] Receipt `health` field is present (even if null)

### Full (Health Check Enabled)
- [ ] Server starts successfully
- [ ] `/health` endpoint returns 200
- [ ] Receipt `health.ok` is `true`
- [ ] Receipt `health.status_code` is `200`
- [ ] Receipt `health.body_snippet` contains `"healthy"`
- [ ] Server process is terminated after check

---

## Out of Scope
- Keeping server running after tests
- Load testing
- Multiple health endpoints
- Health check retry logic

---

## Post-Task Report Format (Mandatory)

```
=== S1-03 COMPLETION REPORT ===

## Configuration
target_repo: https://github.com/launchplugai/DNA
target_branch: main
command: <command>
health_url: http://localhost:8000/health

## Test Results
Overall status: SUCCESS
Test exit code: 0

## Health Check Results
URL: http://localhost:8000/health
Status code: 200
Response: {"status": "healthy", ...}
Health OK: true

## Receipt Health Section
{
  "health": {
    "url": "http://localhost:8000/health",
    "status_code": 200,
    "body_snippet": "...",
    "ok": true
  }
}

## Issues Encountered
<any issues and resolutions>
```

---

## Troubleshooting

### Health Check Times Out
1. Server may not have started — increase sleep time
2. Port may be in use — check `lsof -i :8000`

### Server Won't Start
1. Check dependencies: `pip install uvicorn`
2. Check for import errors: `python -c "from app.main import app"`

### Health Returns Non-200
1. Check server logs
2. Verify endpoint exists: `curl -v http://localhost:8000/health`

### Orphan Server Process
1. Kill manually: `pkill -f uvicorn`
2. Check for process: `ps aux | grep uvicorn`

---

## Future Enhancements (Not This Sprint)
- Dedicated `openbot health` command
- Health check retry with backoff
- Multiple endpoint support
- Health trend tracking
