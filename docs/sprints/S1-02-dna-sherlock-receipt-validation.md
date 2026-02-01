# SPRINT 1 — TICKET S1-02: DNA SHERLOCK RECEIPT VALIDATION

## Goal
Validate that Openbot receipts for DNA Sherlock runs are:
- Schema-compliant (v1 receipt schema)
- Complete (all required fields present)
- Accurate (commit SHA matches, timestamps valid)
- Queryable (can extract key metrics)

This ticket ensures **proof artifacts are trustworthy**.

---

## Non-Negotiable Constraints
- Receipts MUST validate against `policies/receipt_schema_v1.json`
- Invalid receipts MUST be quarantined (not silently accepted)
- All validation must be automated (no manual inspection)

---

## Prerequisites
- [ ] S1-01 complete (at least one successful DNA Sherlock run)
- [ ] At least one receipt exists in `/var/lib/openbot/receipts/`

---

## Implementation Steps

### Part A — Run Openbot Self-Tests
```bash
cd /opt/openbot
/opt/openbot/venv/bin/python -m openbot.selftest
```

**Expected output**: `Results: 13 passed, 0 failed`

Key tests that validate receipts:
- `test_receipt_creation`
- `test_receipt_validation_valid`
- `test_receipt_validation_invalid`
- `test_receipt_writer`
- `test_quarantine_invalid_receipt`

### Part B — Validate Existing Receipt
```bash
# Get latest receipt
RECEIPT=$(ls -t /var/lib/openbot/receipts/*.json | head -1)
echo "Validating: $RECEIPT"

# Check it's valid JSON
cat "$RECEIPT" | jq . > /dev/null && echo "✓ Valid JSON"

# Check required fields exist
cat "$RECEIPT" | jq -e '.receipt_version' > /dev/null && echo "✓ Has receipt_version"
cat "$RECEIPT" | jq -e '.timestamp' > /dev/null && echo "✓ Has timestamp"
cat "$RECEIPT" | jq -e '.run_id' > /dev/null && echo "✓ Has run_id"
cat "$RECEIPT" | jq -e '.target_repo' > /dev/null && echo "✓ Has target_repo"
cat "$RECEIPT" | jq -e '.target_branch' > /dev/null && echo "✓ Has target_branch"
cat "$RECEIPT" | jq -e '.commit_sha' > /dev/null && echo "✓ Has commit_sha"
cat "$RECEIPT" | jq -e '.test.command' > /dev/null && echo "✓ Has test.command"
cat "$RECEIPT" | jq -e '.test.exit_code' > /dev/null && echo "✓ Has test.exit_code"
cat "$RECEIPT" | jq -e '.overall_status' > /dev/null && echo "✓ Has overall_status"
```

### Part C — Validate Commit SHA Format
```bash
RECEIPT=$(ls -t /var/lib/openbot/receipts/*.json | head -1)
SHA=$(cat "$RECEIPT" | jq -r '.commit_sha')

# Must be 40 hex characters
if [[ "$SHA" =~ ^[0-9a-f]{40}$ ]]; then
  echo "✓ Commit SHA is valid 40-char hex: $SHA"
else
  echo "✗ Invalid commit SHA format: $SHA"
  exit 1
fi
```

### Part D — Cross-Reference with Git
```bash
# Verify the commit SHA matches what's actually in the cloned repo
cd /var/lib/openbot/workdir/target
ACTUAL_SHA=$(git rev-parse HEAD)
RECEIPT_SHA=$(cat $(ls -t /var/lib/openbot/receipts/*.json | head -1) | jq -r '.commit_sha')

if [[ "$ACTUAL_SHA" == "$RECEIPT_SHA" ]]; then
  echo "✓ Commit SHA matches: $ACTUAL_SHA"
else
  echo "✗ SHA mismatch! Receipt: $RECEIPT_SHA, Actual: $ACTUAL_SHA"
  exit 1
fi
```

### Part E — Check for Quarantine (Negative Test)
```bash
# Verify no receipts are quarantined (if any exist, investigate)
QUARANTINE_DIR="/var/lib/openbot/receipts/quarantine"
if [[ -d "$QUARANTINE_DIR" ]] && [[ -n "$(ls -A $QUARANTINE_DIR 2>/dev/null)" ]]; then
  echo "⚠ WARNING: Quarantined receipts found!"
  ls -la "$QUARANTINE_DIR"
  cat "$QUARANTINE_DIR"/*.json | jq '.validation_errors'
else
  echo "✓ No quarantined receipts"
fi
```

---

## Acceptance Criteria (Hard Pass/Fail)

- [ ] Openbot self-tests pass (13/13)
- [ ] Latest receipt is valid JSON
- [ ] Receipt contains all required fields
- [ ] `receipt_version` is `"v1"`
- [ ] `commit_sha` is 40-character hex
- [ ] `commit_sha` matches actual git HEAD in workdir
- [ ] `overall_status` is `"SUCCESS"` or `"FAILED"` (not null)
- [ ] No quarantined receipts (unless investigating a bug)

---

## Out of Scope
- Modifying receipt schema
- Adding new receipt fields
- Receipt encryption/signing

---

## Post-Task Report Format (Mandatory)

```
=== S1-02 COMPLETION REPORT ===

## Self-Test Results
Total: 13
Passed: 13
Failed: 0

## Receipt Validation
Receipt path: /var/lib/openbot/receipts/<run_id>.json
Valid JSON: YES
All required fields: YES

## Field Checks
- receipt_version: v1 ✓
- timestamp: 2026-02-01T19:30:00Z ✓
- run_id: <uuid> ✓
- target_repo: https://github.com/launchplugai/DNA ✓
- target_branch: main ✓
- commit_sha: <40-char> ✓
- test.exit_code: 0 ✓
- overall_status: SUCCESS ✓

## Commit SHA Cross-Reference
Receipt SHA: <sha>
Git HEAD SHA: <sha>
Match: YES ✓

## Quarantine Check
Quarantined receipts: 0

## Issues Encountered
<any issues and resolutions>
```

---

## Troubleshooting

### Self-Tests Fail
1. Check Python path: `which python3`
2. Run from repo root: `cd /opt/openbot`
3. Use venv Python: `/opt/openbot/venv/bin/python -m openbot.selftest`

### Receipt Missing Fields
1. Check Openbot version matches latest
2. Re-run `openbot run` and check new receipt

### SHA Mismatch
1. Workdir may be stale — run a fresh `openbot run`
2. Check if workdir was manually modified
