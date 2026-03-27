#!/bin/bash
#
# OpenClaw Diagnostic Script
#
# Checks gateway health, config, and common error patterns.
# Run via SSM or directly on the EC2 instance.
#
# Usage:
#   sudo ./scripts/openclaw-diag.sh
#   # Or via SSM from OpenBot repo:
#   aws ssm send-command --instance-ids i-0dd3b26129b0681ce ...
#

set -euo pipefail

readonly CONFIG="/root/.openclaw/openclaw.json"
readonly LOG_DIR="/tmp/openclaw"
readonly TODAY=$(date -u +%Y-%m-%d)
readonly LOG_FILE="${LOG_DIR}/openclaw-${TODAY}.log"

log_info()  { echo "[INFO]  $*"; }
log_ok()    { echo "[OK]    $*"; }
log_warn()  { echo "[WARN]  $*"; }
log_fail()  { echo "[FAIL]  $*"; }

echo "============================================================"
echo "  OpenClaw Diagnostic Report"
echo "  $(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo "============================================================"
echo ""

# 1. Gateway service status
echo "=== Service Status ==="
if systemctl is-active --quiet openclaw-gateway 2>/dev/null; then
    log_ok "openclaw-gateway is active"
    UPTIME=$(systemctl show openclaw-gateway --property=ActiveEnterTimestamp --value 2>/dev/null || echo "unknown")
    log_info "Started at: ${UPTIME}"
else
    log_fail "openclaw-gateway is NOT active"
fi
echo ""

# 2. Memory usage
echo "=== Memory ==="
GATEWAY_PID=$(pgrep -f "openclaw.*gateway" 2>/dev/null | head -1 || echo "")
if [[ -n "$GATEWAY_PID" ]]; then
    RSS=$(ps -o rss= -p "$GATEWAY_PID" 2>/dev/null || echo "0")
    RSS_MB=$((RSS / 1024))
    if [[ $RSS_MB -gt 500 ]]; then
        log_warn "Gateway RSS: ${RSS_MB}MB (high - consider restart)"
    else
        log_ok "Gateway RSS: ${RSS_MB}MB"
    fi
else
    log_warn "Gateway process not found"
fi
FREE_MEM=$(free -m | awk '/^Mem:/ {print $7}')
log_info "Available system memory: ${FREE_MEM}MB"
echo ""

# 3. Config validation
echo "=== Config ==="
if [[ -f "$CONFIG" ]]; then
    log_ok "Config exists: $CONFIG"

    # Check contextPruning
    PRUNING_MODE=$(python3 -c "
import json
with open('$CONFIG') as f:
    cfg = json.load(f)
print(cfg.get('agents',{}).get('defaults',{}).get('contextPruning',{}).get('mode','off'))
" 2>/dev/null || echo "error")
    if [[ "$PRUNING_MODE" == "cache-ttl" ]]; then
        log_ok "contextPruning.mode = cache-ttl (prevents tool_call_id orphans)"
    else
        log_warn "contextPruning.mode = $PRUNING_MODE (recommend: cache-ttl)"
    fi

    # Check compaction
    COMPACTION_MODE=$(python3 -c "
import json
with open('$CONFIG') as f:
    cfg = json.load(f)
print(cfg.get('agents',{}).get('defaults',{}).get('compaction',{}).get('mode','default'))
" 2>/dev/null || echo "error")
    if [[ "$COMPACTION_MODE" == "safeguard" ]]; then
        log_ok "compaction.mode = safeguard (prevents orphaned tool blocks)"
    else
        log_warn "compaction.mode = $COMPACTION_MODE (recommend: safeguard)"
    fi

    # Check primary model
    PRIMARY=$(python3 -c "
import json
with open('$CONFIG') as f:
    cfg = json.load(f)
print(cfg.get('agents',{}).get('defaults',{}).get('model',{}).get('primary','not set'))
" 2>/dev/null || echo "error")
    log_info "Primary model: $PRIMARY"
else
    log_fail "Config not found: $CONFIG"
fi
echo ""

# 4. Recent errors
echo "=== Recent Errors (last 24h) ==="
if [[ -f "$LOG_FILE" ]]; then
    TOOL_ID_ERRORS=$(grep -c "tool_use_id\|tool_call_id.*not found" "$LOG_FILE" 2>/dev/null || echo "0")
    TIMEOUT_ERRORS=$(grep -c "timed out" "$LOG_FILE" 2>/dev/null || echo "0")
    AUTH_ERRORS=$(grep -c "401\|Invalid Authentication\|Unauthorized" "$LOG_FILE" 2>/dev/null || echo "0")
    BILLING_ERRORS=$(grep -c "credit balance" "$LOG_FILE" 2>/dev/null || echo "0")
    COMPACTION_EVENTS=$(grep -c "compaction start" "$LOG_FILE" 2>/dev/null || echo "0")

    if [[ $TOOL_ID_ERRORS -gt 0 ]]; then
        log_fail "tool_call_id errors: $TOOL_ID_ERRORS (conversation history corruption)"
    else
        log_ok "tool_call_id errors: 0"
    fi

    if [[ $TIMEOUT_ERRORS -gt 0 ]]; then
        log_warn "Timeout errors: $TIMEOUT_ERRORS"
    else
        log_ok "Timeout errors: 0"
    fi

    if [[ $AUTH_ERRORS -gt 0 ]]; then
        log_warn "Auth errors: $AUTH_ERRORS"
    fi

    if [[ $BILLING_ERRORS -gt 0 ]]; then
        log_warn "Billing/credit errors: $BILLING_ERRORS"
    fi

    log_info "Compaction events: $COMPACTION_EVENTS"
else
    log_warn "No log file for today: $LOG_FILE"
fi
echo ""

# 5. Disk
echo "=== Disk ==="
DISK_USAGE=$(df -h / | awk 'NR==2 {print $5}')
log_info "Root disk usage: $DISK_USAGE"
echo ""

echo "============================================================"
echo "  Diagnostic complete"
echo "============================================================"
