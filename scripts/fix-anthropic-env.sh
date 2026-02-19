#!/bin/bash
# fix-anthropic-env.sh — Remove ANTHROPIC_API_KEY from env to stop provider leak
#
# Problem: ANTHROPIC_API_KEY in shell env causes OpenClaw to auto-discover
# and use Anthropic as a provider even when not in the model chain.
# This burns Anthropic credits silently and bypasses the intended
# Kimi -> GPT model hierarchy.
#
# Fix: Remove from shell env, systemd env, .bashrc, .profile.
# Keep ONLY in openclaw.json env section (where it belongs)
# and in auth-profiles.json (for Claude CLI workers).
#
# Run via SSM:
#   aws ssm send-command --instance-id i-0dd3b26129b0681ce \
#     --document-name AWS-RunShellScript \
#     --parameters 'commands=["bash /opt/openbot/scripts/fix-anthropic-env.sh"]' \
#     --region us-east-2

set -euo pipefail

CONFIG="/root/.openclaw/openclaw.json"
AUTH_PROFILES="/root/.openclaw/agents/main/agent/auth-profiles.json"
BACKUP_DIR="/root/.openclaw/config-profiles/pre-env-fix-backup"

echo "=== Anthropic API Key Environment Fix ==="
echo "Timestamp: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo ""

# ── 1. Audit current state ───────────────────────────────────────────────

echo "--- Audit ---"

# Check shell env
if [ -n "${ANTHROPIC_API_KEY:-}" ]; then
    # Show first/last 4 chars only
    KEY="${ANTHROPIC_API_KEY}"
    MASKED="${KEY:0:4}...${KEY: -4}"
    echo "Shell env:       SET ($MASKED)"
else
    echo "Shell env:       not set (good)"
fi

# Check .bashrc
if grep -q "ANTHROPIC_API_KEY" /root/.bashrc 2>/dev/null; then
    echo ".bashrc:         CONTAINS export (will remove)"
else
    echo ".bashrc:         clean"
fi

# Check .profile
if grep -q "ANTHROPIC_API_KEY" /root/.profile 2>/dev/null; then
    echo ".profile:        CONTAINS export (will remove)"
else
    echo ".profile:        clean"
fi

# Check .env files
for envfile in /root/.env /root/.openclaw/.env; do
    if [ -f "$envfile" ] && grep -q "ANTHROPIC_API_KEY" "$envfile" 2>/dev/null; then
        echo "$envfile:  CONTAINS key (will remove)"
    fi
done

# Check systemd override
SYSTEMD_OVERRIDE="/etc/systemd/system/openclaw-gateway.service.d/override.conf"
if [ -f "$SYSTEMD_OVERRIDE" ] && grep -q "ANTHROPIC_API_KEY" "$SYSTEMD_OVERRIDE" 2>/dev/null; then
    echo "systemd override: CONTAINS key (will remove)"
else
    echo "systemd override: clean"
fi

# Check openclaw.json env section
if [ -f "$CONFIG" ]; then
    IN_CONFIG=$(python3 -c "
import json
with open('$CONFIG') as f:
    c = json.load(f)
env = c.get('env', {})
if 'ANTHROPIC_API_KEY' in env:
    k = env['ANTHROPIC_API_KEY']
    print(f'SET ({k[:4]}...{k[-4:]})')
else:
    print('not set')
" 2>/dev/null || echo "parse error")
    echo "openclaw.json:   $IN_CONFIG (this is where it SHOULD live)"
fi

# Check auth-profiles.json
if [ -f "$AUTH_PROFILES" ]; then
    IN_AUTH=$(python3 -c "
import json
with open('$AUTH_PROFILES') as f:
    a = json.load(f)
s = json.dumps(a)
if 'anthropic' in s.lower() or 'ANTHROPIC' in s:
    print('has Anthropic entry (correct — for Claude CLI workers)')
else:
    print('no Anthropic entry')
" 2>/dev/null || echo "parse error")
    echo "auth-profiles:   $IN_AUTH"
fi
echo ""

# ── 2. Backup ────────────────────────────────────────────────────────────

echo "--- Backup ---"
mkdir -p "$BACKUP_DIR"
for f in /root/.bashrc /root/.profile "$CONFIG" "$AUTH_PROFILES"; do
    [ -f "$f" ] && cp "$f" "$BACKUP_DIR/$(basename "$f").$(date +%s)"
done
echo "Backed up to $BACKUP_DIR"
echo ""

# ── 3. Remove from shell profiles ────────────────────────────────────────

echo "--- Cleaning shell profiles ---"

for profile in /root/.bashrc /root/.profile /root/.bash_profile; do
    if [ -f "$profile" ] && grep -q "ANTHROPIC_API_KEY" "$profile"; then
        # Remove lines containing ANTHROPIC_API_KEY
        sed -i '/ANTHROPIC_API_KEY/d' "$profile"
        echo "Removed from $profile"
    fi
done

# Remove from .env files
for envfile in /root/.env /root/.openclaw/.env; do
    if [ -f "$envfile" ] && grep -q "ANTHROPIC_API_KEY" "$envfile"; then
        sed -i '/ANTHROPIC_API_KEY/d' "$envfile"
        echo "Removed from $envfile"
    fi
done

echo ""

# ── 4. Remove from systemd override ──────────────────────────────────────

echo "--- Cleaning systemd ---"

if [ -f "$SYSTEMD_OVERRIDE" ] && grep -q "ANTHROPIC_API_KEY" "$SYSTEMD_OVERRIDE"; then
    sed -i '/ANTHROPIC_API_KEY/d' "$SYSTEMD_OVERRIDE"
    systemctl daemon-reload
    echo "Removed from systemd override, daemon reloaded."
else
    echo "systemd clean — no changes needed."
fi
echo ""

# ── 5. Ensure key is in openclaw.json env (where it belongs) ─────────────

echo "--- Verifying openclaw.json ---"

python3 -c "
import json

config_path = '$CONFIG'
with open(config_path) as f:
    config = json.load(f)

env = config.get('env', {})
if 'ANTHROPIC_API_KEY' in env and env['ANTHROPIC_API_KEY']:
    print('ANTHROPIC_API_KEY is in openclaw.json env section (correct)')
    print('This is the ONLY place it should be for gateway model access.')
else:
    print('WARNING: ANTHROPIC_API_KEY not found in openclaw.json env section.')
    print('If you need Anthropic models in the chat chain, add it:')
    print('  \"env\": { \"ANTHROPIC_API_KEY\": \"sk-ant-...\" }')
    print('If running backup profile (Kimi-only), this is fine — no key needed.')
"
echo ""

# ── 6. Verify model chain doesn't force Anthropic ────────────────────────

echo "--- Model Chain Check ---"

if [ -f "$CONFIG" ]; then
    python3 -c "
import json

with open('$CONFIG') as f:
    config = json.load(f)

# Check if Anthropic is in the model chain
s = json.dumps(config.get('agents', {})).lower()
models_s = json.dumps(config.get('models', {})).lower() if 'models' in config else ''

anthropic_in_chain = 'anthropic' in s or 'anthropic' in models_s or 'claude' in s

if anthropic_in_chain:
    print('Anthropic IS in the model chain (normal profile)')
    print('Key in openclaw.json env is required.')
else:
    print('Anthropic NOT in model chain (backup profile)')
    print('No Anthropic key needed. Provider auto-discovery is now blocked.')
"
fi
echo ""

# ── 7. Unset from current shell (won't persist across sessions) ──────────

unset ANTHROPIC_API_KEY 2>/dev/null || true
echo "Unset ANTHROPIC_API_KEY from current shell."
echo ""

echo "=== Fix Complete ==="
echo ""
echo "What was done:"
echo "  1. Removed ANTHROPIC_API_KEY from .bashrc, .profile, .env, systemd"
echo "  2. Key preserved in openclaw.json env (where OpenClaw reads it)"
echo "  3. Auth-profiles.json untouched (Claude CLI workers need it)"
echo "  4. Shell env unset for current session"
echo ""
echo "Why this matters:"
echo "  OpenClaw auto-discovers providers from env vars. Having"
echo "  ANTHROPIC_API_KEY in the shell env causes Anthropic to be used"
echo "  even when the model chain is Kimi -> GPT (backup profile)."
echo "  Moving it to openclaw.json env gives OpenClaw explicit control."
echo ""
echo "Rollback: cp $BACKUP_DIR/.bashrc.* /root/.bashrc"
