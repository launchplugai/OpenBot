#!/bin/bash
# fix-openclaw-gateway.sh — Diagnose and fix the OpenClaw gateway
#
# Modes:
#   (no args)     Full diagnostics + restart
#   --diagnose    Diagnostics only, no restart
#   --restart     Clear sessions + restart only (skip diagnostics)
#
# Run via SSM:
#   aws ssm send-command --instance-id i-0dd3b26129b0681ce \
#     --document-name AWS-RunShellScript \
#     --parameters 'commands=["bash /opt/openbot/scripts/fix-openclaw-gateway.sh"]' \
#     --region us-east-2
# Or paste into an SSM Session Manager terminal.

set -euo pipefail

MODE="${1:-full}"
CONFIG="/root/.openclaw/openclaw.json"
MODELS_CONFIG="/root/.openclaw/agents/main/agent/models.json"
AUTH_PROFILES="/root/.openclaw/agents/main/agent/auth-profiles.json"
MEMORY_DIR="/root/.openclaw/memory"
GATEWAY_PORT=18789
STARTUP_WAIT=60

echo "=== OpenClaw Gateway Diagnostics ==="
echo "Timestamp: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo "Mode: $MODE"
echo ""

# ── Diagnostics ───────────────────────────────────────────────────────────

if [ "$MODE" != "--restart" ]; then

    # 1. Service status
    echo "--- Service Status ---"
    systemctl status openclaw-gateway --no-pager 2>&1 || true
    echo ""

    # 2. Port check
    echo "--- Port Check ---"
    if ss -tlnp | grep -q "$GATEWAY_PORT"; then
        echo "Port $GATEWAY_PORT: LISTENING"
        ss -tlnp | grep "$GATEWAY_PORT"
    else
        echo "Port $GATEWAY_PORT: NOT LISTENING"
    fi
    echo ""

    # 3. Memory
    echo "--- Memory ---"
    free -m
    AVAIL_MB=$(free -m | awk '/^Mem:/{print $7}')
    if [ "$AVAIL_MB" -lt 500 ]; then
        echo "WARNING: Low memory (${AVAIL_MB}MB available). Gateway may be unstable."
    fi
    echo ""

    # 4. Disk space
    echo "--- Disk ---"
    df -h /tmp /root 2>/dev/null || df -h
    echo ""

    # 5. Session bloat (known issue — ONBOARDING lesson #3)
    echo "--- Sessions ---"
    if [ -d /tmp/openclaw/sessions ]; then
        SESSION_COUNT=$(ls /tmp/openclaw/sessions/ 2>/dev/null | wc -l)
        SESSION_SIZE=$(du -sh /tmp/openclaw/sessions/ 2>/dev/null | cut -f1)
        echo "Count: $SESSION_COUNT"
        echo "Size:  $SESSION_SIZE"
        if [ "$SESSION_COUNT" -gt 40 ]; then
            echo "WARNING: $SESSION_COUNT sessions — likely causing context bloat and timeouts."
        fi
    else
        echo "No sessions directory"
    fi
    echo ""

    # 6. Config validation
    echo "--- Config Validation ---"
    if [ -f "$CONFIG" ]; then
        if python3 -c "import json; json.load(open('$CONFIG'))" 2>/dev/null; then
            echo "openclaw.json: valid JSON"
        else
            echo "CRITICAL: openclaw.json is INVALID JSON"
        fi
        # Check writable (lesson #2)
        if [ -w "$CONFIG" ]; then
            echo "openclaw.json: writable (good)"
        else
            echo "CRITICAL: openclaw.json NOT writable — gateway will crash (EPERM)"
        fi
    else
        echo "CRITICAL: openclaw.json NOT FOUND at $CONFIG"
    fi

    if [ -f "$MODELS_CONFIG" ]; then
        if python3 -c "import json; json.load(open('$MODELS_CONFIG'))" 2>/dev/null; then
            echo "models.json:   valid JSON"
        else
            echo "WARNING: models.json is INVALID JSON"
        fi
    else
        echo "WARNING: models.json not found"
    fi

    if [ -f "$AUTH_PROFILES" ]; then
        if python3 -c "import json; json.load(open('$AUTH_PROFILES'))" 2>/dev/null; then
            echo "auth-profiles: valid JSON"
        else
            echo "WARNING: auth-profiles.json is INVALID JSON"
        fi
    fi
    echo ""

    # 7. Model chain check
    echo "--- Model Chain ---"
    if [ -f "$CONFIG" ]; then
        python3 -c "
import json
with open('$CONFIG') as f:
    c = json.load(f)

# Check agents/models section
agents = c.get('agents', {})
defaults = agents.get('defaults', {})
model = defaults.get('model', {})
primary = model.get('primary', 'not set')
fallbacks = model.get('fallbacks', [])

print(f'Primary:   {primary}')
print(f'Fallbacks: {fallbacks}')

# Check for env vars
env = c.get('env', {})
keys = [k for k in env.keys() if 'API_KEY' in k or 'KEY' in k.upper()]
masked = {k: f'{v[:4]}...{v[-4:]}' if len(v) > 8 else '***' for k, v in env.items() if k in keys}
print(f'API keys in env: {list(masked.keys())}')

# Check for Anthropic leak
if 'ANTHROPIC_API_KEY' in env:
    print('Anthropic: in openclaw.json env (correct location)')
" 2>/dev/null || echo "Could not parse config"
    fi

    # Check shell env leak
    if [ -n "${ANTHROPIC_API_KEY:-}" ]; then
        echo "WARNING: ANTHROPIC_API_KEY in shell env — forces Anthropic auto-discovery"
        echo "Fix:     bash /opt/openbot/scripts/fix-anthropic-env.sh"
    fi
    echo ""

    # 8. Web search + browser status
    echo "--- Capabilities ---"
    if [ -f "$CONFIG" ]; then
        python3 -c "
import json
with open('$CONFIG') as f:
    c = json.load(f)

tools = c.get('tools', {})
also = tools.get('alsoAllow', [])
web = tools.get('web', {})
ws = web.get('search', {}).get('enabled', False)
wf = web.get('fetch', {}).get('enabled', False)
print(f'Web search: {\"enabled\" if ws else \"disabled\"} (alsoAllow: {also})')
print(f'Web fetch:  {\"enabled\" if wf else \"disabled\"}')

browser = c.get('browser', {})
be = browser.get('enabled', False)
bp = browser.get('defaultProfile', 'none')
print(f'Browser:    {\"enabled\" if be else \"disabled\"} (profile: {bp})')
" 2>/dev/null || echo "Could not parse config"
    fi
    echo ""

    # 9. Memory system health
    echo "--- Memory System ---"
    for f in MEMORY.md current-work.json taskboard.json lessons.json decisions.md; do
        path="$MEMORY_DIR/$f"
        if [ -f "$path" ]; then
            echo "  $f: exists ($(wc -l < "$path") lines)"
        else
            echo "  $f: MISSING"
        fi
    done
    if [ -d "$MEMORY_DIR/daily" ]; then
        DAILY_COUNT=$(ls "$MEMORY_DIR/daily/" 2>/dev/null | wc -l)
        LATEST=$(ls -t "$MEMORY_DIR/daily/" 2>/dev/null | head -1)
        echo "  daily notes: $DAILY_COUNT files (latest: ${LATEST:-none})"
    else
        echo "  daily/: MISSING"
    fi
    echo ""

    # 10. Recent logs (errors only)
    echo "--- Recent Errors (last 100 log lines) ---"
    journalctl -u openclaw-gateway --no-pager -n 100 2>/dev/null \
        | grep -iE "(error|fatal|exception|timeout|EPERM|refused|denied)" \
        | tail -10 || echo "No recent errors"
    echo ""

fi  # end diagnostics

# ── Fix ───────────────────────────────────────────────────────────────────

if [ "$MODE" != "--diagnose" ]; then

    echo "=== Applying Fix ==="

    # Clear stale sessions
    echo "Clearing stale sessions..."
    rm -rf /tmp/openclaw/sessions/*
    echo "Cleared."

    # Restart gateway
    echo "Restarting openclaw-gateway..."
    systemctl restart openclaw-gateway
    echo "Gateway restarting (50s startup, waiting ${STARTUP_WAIT}s)..."
    sleep "$STARTUP_WAIT"

    # Verify
    echo ""
    echo "--- Post-fix Status ---"
    if systemctl is-active openclaw-gateway &>/dev/null; then
        echo "Service: ACTIVE"
    else
        echo "Service: FAILED"
        echo "Recent logs:"
        journalctl -u openclaw-gateway --no-pager -n 20 2>&1 || true
    fi

    if ss -tlnp | grep -q "$GATEWAY_PORT"; then
        echo "Port:    $GATEWAY_PORT LISTENING"
    else
        echo "Port:    $GATEWAY_PORT NOT LISTENING"
    fi

    HEALTH=$(curl -s --connect-timeout 10 http://localhost:$GATEWAY_PORT/ 2>&1 | head -5)
    if [ -n "$HEALTH" ]; then
        echo "Health:  RESPONDING"
    else
        echo "Health:  NOT RESPONDING (may need more time — try again in 30s)"
    fi
    echo ""

fi

echo "=== Done ==="
echo ""
echo "Other scripts:"
echo "  fix-anthropic-env.sh     — Fix Anthropic provider leak from shell env"
echo "  enable-web-search.sh     — Enable Kimi \$web_search (Phase 1)"
echo "  enable-browser.sh        — Enable browser automation (Phase 2)"
echo "  harden-memory.sh         — Initialize and validate memory system"
