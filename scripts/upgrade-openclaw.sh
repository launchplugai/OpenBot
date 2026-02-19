#!/bin/bash
# upgrade-openclaw.sh — Upgrade OpenClaw from 2026.2.2-3 to latest (2026.2.17+)
#
# This upgrade crosses a 40-vulnerability security patch (2026.2.12),
# a hooks fix (2026.2.17), and several breaking changes. Handle with care.
#
# What this script does:
#   1. Full backup of configs, memory, and current binary
#   2. Pre-flight checks (disk, node version, current health)
#   3. Stop the gateway cleanly
#   4. Upgrade via npm
#   5. Apply post-upgrade fixes for breaking changes
#   6. Restart and verify
#
# Run via SSM:
#   aws ssm send-command --instance-id i-0dd3b26129b0681ce \
#     --document-name AWS-RunShellScript \
#     --parameters 'commands=["bash /opt/openbot/scripts/upgrade-openclaw.sh"]' \
#     --region us-east-2
#
# Modes:
#   (no args)       Full upgrade
#   --dry-run       Pre-flight checks only, no changes
#   --rollback      Restore from backup

set -euo pipefail

MODE="${1:-upgrade}"
BACKUP_ROOT="/root/.openclaw/backups"
BACKUP_DIR="$BACKUP_ROOT/pre-upgrade-$(date +%Y%m%d-%H%M%S)"
GATEWAY_PORT=18789
STARTUP_WAIT=60

echo "=== OpenClaw Upgrade ==="
echo "Timestamp: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo "Mode: $MODE"
echo ""

# ── Rollback ──────────────────────────────────────────────────────────

if [ "$MODE" = "--rollback" ]; then
    echo "=== Rollback Mode ==="
    LATEST_BACKUP=$(ls -td "$BACKUP_ROOT"/pre-upgrade-* 2>/dev/null | head -1)
    if [ -z "$LATEST_BACKUP" ]; then
        echo "ERROR: No backup found in $BACKUP_ROOT"
        exit 1
    fi
    echo "Restoring from: $LATEST_BACKUP"

    echo "Stopping gateway..."
    systemctl stop openclaw-gateway 2>/dev/null || true
    sleep 5

    # Restore configs
    if [ -d "$LATEST_BACKUP/openclaw-config" ]; then
        echo "Restoring configs..."
        cp -a "$LATEST_BACKUP/openclaw-config/openclaw.json" /root/.openclaw/openclaw.json 2>/dev/null || true
        cp -a "$LATEST_BACKUP/openclaw-config/agents" /root/.openclaw/agents 2>/dev/null || true
    fi

    # Restore npm package
    if [ -f "$LATEST_BACKUP/openclaw-version.txt" ]; then
        OLD_VERSION=$(cat "$LATEST_BACKUP/openclaw-version.txt")
        echo "Reinstalling OpenClaw $OLD_VERSION..."
        npm install -g "openclaw@$OLD_VERSION" 2>&1 || true
    fi

    echo "Restarting gateway..."
    systemctl start openclaw-gateway
    sleep "$STARTUP_WAIT"

    systemctl is-active openclaw-gateway && echo "Service: ACTIVE" || echo "Service: FAILED"
    echo "=== Rollback Complete ==="
    exit 0
fi

# ── Pre-flight Checks ────────────────────────────────────────────────

echo "--- Pre-flight Checks ---"

# Current version
CURRENT_VERSION=$(openclaw --version 2>/dev/null || echo "unknown")
echo "Current version: $CURRENT_VERSION"

# Node.js version (need >= 22)
NODE_VERSION=$(node --version 2>/dev/null || echo "none")
echo "Node.js:         $NODE_VERSION"
if [ "$NODE_VERSION" = "none" ]; then
    echo "CRITICAL: Node.js not installed. OpenClaw requires Node >= 22."
    echo "Install: curl -fsSL https://deb.nodesource.com/setup_22.x | bash - && apt-get install -y nodejs"
    exit 1
fi
NODE_MAJOR=$(echo "$NODE_VERSION" | sed 's/v//' | cut -d. -f1)
if [ "$NODE_MAJOR" -lt 22 ]; then
    echo "WARNING: Node $NODE_VERSION is below required v22."
    echo "Upgrade: curl -fsSL https://deb.nodesource.com/setup_22.x | bash - && apt-get install -y nodejs"
    if [ "$MODE" = "--dry-run" ]; then
        echo "Would need Node upgrade before proceeding."
    else
        echo "Attempting Node upgrade..."
        curl -fsSL https://deb.nodesource.com/setup_22.x | bash - 2>&1
        apt-get install -y nodejs 2>&1
        echo "Node upgraded to: $(node --version)"
    fi
fi

# Disk space
AVAIL_MB=$(df -m /root | tail -1 | awk '{print $4}')
echo "Disk available:  ${AVAIL_MB}MB"
if [ "$AVAIL_MB" -lt 500 ]; then
    echo "CRITICAL: Less than 500MB free. Clean up before upgrading."
    exit 1
fi

# Gateway health
echo "Gateway status:  $(systemctl is-active openclaw-gateway 2>/dev/null || echo 'not running')"
if ss -tlnp | grep -q "$GATEWAY_PORT"; then
    echo "Port $GATEWAY_PORT:     LISTENING"
else
    echo "Port $GATEWAY_PORT:     NOT LISTENING"
fi

# npm available
NPM_VERSION=$(npm --version 2>/dev/null || echo "none")
echo "npm:             $NPM_VERSION"

# Config files exist
for f in /root/.openclaw/openclaw.json /root/.openclaw/agents/main/agent/models.json; do
    if [ -f "$f" ]; then
        echo "Config:          $f exists"
    else
        echo "WARNING:         $f MISSING"
    fi
done

# Check latest available version
LATEST=$(npm show openclaw version 2>/dev/null || echo "unknown")
echo "Latest available: $LATEST"
echo ""

if [ "$MODE" = "--dry-run" ]; then
    echo "=== Dry Run Complete ==="
    echo "Would upgrade: $CURRENT_VERSION → $LATEST"
    echo ""
    echo "Breaking changes to handle:"
    echo "  1. Hooks path restricted to ~/.openclaw/hooks/transforms (2026.2.12)"
    echo "  2. Canvas IP auth tightened to RFC1918 only (2026.2.12)"
    echo "  3. tsdown hook fix landed (2026.2.17)"
    echo "  4. maxTokens now clamped to contextWindow (2026.2.17)"
    echo "  5. Run 'openclaw doctor --fix' after upgrade"
    exit 0
fi

# ── Backup ────────────────────────────────────────────────────────────

echo "--- Backup ---"
mkdir -p "$BACKUP_DIR"

# Save current version
echo "$CURRENT_VERSION" > "$BACKUP_DIR/openclaw-version.txt"

# Backup configs
echo "Backing up configs..."
cp -a /root/.openclaw/openclaw.json "$BACKUP_DIR/" 2>/dev/null || true
cp -a /root/.openclaw/agents "$BACKUP_DIR/openclaw-config-agents" 2>/dev/null || true

# Backup the entire config dir (excluding sessions which can be huge)
mkdir -p "$BACKUP_DIR/openclaw-config"
rsync -a --exclude='sessions' --exclude='backups' /root/.openclaw/ "$BACKUP_DIR/openclaw-config/" 2>/dev/null || \
    cp -a /root/.openclaw/openclaw.json "$BACKUP_DIR/openclaw-config/" 2>/dev/null || true

# Backup memory (CRITICAL — this is the org brain)
echo "Backing up memory..."
cp -a /root/.openclaw/memory "$BACKUP_DIR/memory" 2>/dev/null || true

# Backup systemd unit
cp /etc/systemd/system/openclaw-gateway.service "$BACKUP_DIR/" 2>/dev/null || true
cp -a /etc/systemd/system/openclaw-gateway.service.d "$BACKUP_DIR/systemd-override" 2>/dev/null || true

echo "Backup saved to: $BACKUP_DIR"
ls -la "$BACKUP_DIR/"
echo ""

# ── Stop Gateway ──────────────────────────────────────────────────────

echo "--- Stopping Gateway ---"
echo "Clearing stale sessions first..."
rm -rf /tmp/openclaw/sessions/* 2>/dev/null || true

systemctl stop openclaw-gateway 2>/dev/null || true
sleep 5

# Verify stopped
if systemctl is-active openclaw-gateway &>/dev/null; then
    echo "WARNING: Gateway still running. Force stopping..."
    systemctl kill openclaw-gateway 2>/dev/null || true
    sleep 3
fi
echo "Gateway stopped."
echo ""

# ── Upgrade ───────────────────────────────────────────────────────────

echo "--- Upgrading OpenClaw ---"
echo "Installing latest version..."

# Clear npm cache to avoid stale packages
npm cache clean --force 2>/dev/null || true

# Install latest
npm install -g openclaw@latest 2>&1

NEW_VERSION=$(openclaw --version 2>/dev/null || echo "unknown")
echo ""
echo "Upgraded: $CURRENT_VERSION → $NEW_VERSION"
echo ""

# ── Post-Upgrade Fixes ───────────────────────────────────────────────

echo "--- Post-Upgrade Fixes ---"

# Fix 1: Hooks path restriction (2026.2.12)
# Ensure hooks transforms dir exists at the required path
HOOKS_DIR="/root/.openclaw/hooks/transforms"
if [ ! -d "$HOOKS_DIR" ]; then
    mkdir -p "$HOOKS_DIR"
    echo "Created hooks transforms dir: $HOOKS_DIR"
fi

# Check if any hooks config references an old path
if [ -f /root/.openclaw/openclaw.json ]; then
    python3 -c "
import json
with open('/root/.openclaw/openclaw.json') as f:
    config = json.load(f)

hooks = config.get('hooks', {})
transforms_dir = hooks.get('transformsDir', '')
if transforms_dir and '/root/.openclaw/hooks/transforms' not in transforms_dir:
    print(f'WARNING: hooks.transformsDir is \"{transforms_dir}\"')
    print('Must be within ~/.openclaw/hooks/transforms (2026.2.12 security fix)')
    print('Updating...')
    hooks['transformsDir'] = '/root/.openclaw/hooks/transforms'
    config['hooks'] = hooks
    with open('/root/.openclaw/openclaw.json', 'w') as f:
        json.dump(config, f, indent=2)
    print('Updated hooks.transformsDir')
else:
    print('Hooks config: OK')
" 2>/dev/null || echo "Hooks check: skipped (no python3 or no config)"
fi

# Fix 2: maxTokens clamp (2026.2.17)
# Ensure maxTokens doesn't exceed contextWindow for any model
if [ -f /root/.openclaw/openclaw.json ]; then
    python3 -c "
import json
with open('/root/.openclaw/openclaw.json') as f:
    config = json.load(f)

# Check if any model config has maxTokens > contextWindow
# The new version clamps this automatically, but log if we see it
models = config.get('models', {})
for name, model in models.items() if isinstance(models, dict) else []:
    mt = model.get('maxTokens', 0)
    cw = model.get('contextWindow', 200000)
    if mt > cw:
        print(f'WARNING: Model {name} has maxTokens ({mt}) > contextWindow ({cw})')
        print(f'  The new version will auto-clamp this.')

print('maxTokens check: OK')
" 2>/dev/null || echo "maxTokens check: skipped"
fi

# Fix 3: Run openclaw doctor
echo ""
echo "Running openclaw doctor..."
openclaw doctor --fix 2>&1 || echo "openclaw doctor not available or failed (non-critical)"
echo ""

# Fix 4: Ensure ANTHROPIC_API_KEY is NOT in shell env (our previous fix)
if [ -n "${ANTHROPIC_API_KEY:-}" ]; then
    echo "WARNING: ANTHROPIC_API_KEY still in shell env."
    echo "Run: bash /opt/openbot/scripts/fix-anthropic-env.sh"
fi

echo ""

# ── Restart Gateway ───────────────────────────────────────────────────

echo "--- Restarting Gateway ---"
systemctl daemon-reload
systemctl start openclaw-gateway
echo "Gateway starting (waiting ${STARTUP_WAIT}s for startup)..."
sleep "$STARTUP_WAIT"
echo ""

# ── Verify ────────────────────────────────────────────────────────────

echo "--- Post-Upgrade Verification ---"

# Service status
if systemctl is-active openclaw-gateway &>/dev/null; then
    echo "Service:   ACTIVE"
else
    echo "Service:   FAILED"
    echo "Recent logs:"
    journalctl -u openclaw-gateway --no-pager -n 20 2>&1 || true
    echo ""
    echo "UPGRADE MAY HAVE FAILED. Check logs above."
    echo "Rollback: bash /opt/openbot/scripts/upgrade-openclaw.sh --rollback"
    exit 1
fi

# Port
if ss -tlnp | grep -q "$GATEWAY_PORT"; then
    echo "Port:      $GATEWAY_PORT LISTENING"
else
    echo "Port:      $GATEWAY_PORT NOT LISTENING"
    echo "WARNING: Gateway is active but port isn't listening yet. May need more time."
fi

# Health check
HEALTH=$(curl -s --connect-timeout 10 http://localhost:$GATEWAY_PORT/ 2>&1 | head -5)
if [ -n "$HEALTH" ]; then
    echo "Health:    RESPONDING"
else
    echo "Health:    NOT RESPONDING (may need 30s more)"
fi

# Version confirm
FINAL_VERSION=$(openclaw --version 2>/dev/null || echo "unknown")
echo "Version:   $FINAL_VERSION"

# Config validation
if [ -f /root/.openclaw/openclaw.json ]; then
    if python3 -c "import json; json.load(open('/root/.openclaw/openclaw.json'))" 2>/dev/null; then
        echo "Config:    valid JSON"
    else
        echo "Config:    INVALID JSON — check for corruption"
    fi
fi

# Memory intact
if [ -f /root/.openclaw/memory/MEMORY.md ]; then
    echo "Memory:    intact ($(wc -l < /root/.openclaw/memory/MEMORY.md) lines)"
else
    echo "Memory:    MISSING — restore from backup"
fi

echo ""
echo "=== Upgrade Complete ==="
echo ""
echo "Summary:"
echo "  From:    $CURRENT_VERSION"
echo "  To:      $FINAL_VERSION"
echo "  Backup:  $BACKUP_DIR"
echo ""
echo "Key changes in this upgrade:"
echo "  - 40 security vulnerabilities patched (2026.2.12)"
echo "  - Bundled hooks fixed (were broken since 2026.2.2)"
echo "  - Sonnet 4.6 model support added"
echo "  - 1M context opt-in available (params.context1m: true)"
echo "  - Browser automation 'unbrowse' added"
echo "  - Memory persistence improved"
echo ""
echo "Post-upgrade steps:"
echo "  1. Run: fixit heartbeat --once --plugin openbot"
echo "  2. Run: bash /opt/openbot/scripts/fix-openclaw-gateway.sh --diagnose"
echo "  3. Test Telegram bot responsiveness"
echo "  4. Check: fixit pool --stats"
echo ""
echo "If anything is wrong:"
echo "  Rollback: bash /opt/openbot/scripts/upgrade-openclaw.sh --rollback"
