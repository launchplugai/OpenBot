#!/bin/bash
# entrypoint-gateway.sh — Patches config from env vars, then starts OpenClaw gateway
#
# This runs on every container start. It:
#   1. Checks EFS mount is present and writable
#   2. Injects secrets from env vars into config files (Pattern B: compatibility)
#   3. Clears stale sessions (they don't survive container restarts anyway)
#   4. Hardens memory if first boot
#   5. Starts the gateway
#
# Secrets are injected from env vars set by ECS task definition via Secrets Manager.
# The actual API keys never touch the filesystem permanently — they're patched at boot.

set -euo pipefail

CONFIG="/root/.openclaw/openclaw.json"
AUTH_PROFILES="/root/.openclaw/agents/main/agent/auth-profiles.json"
MEMORY_DIR="/root/.openclaw/memory"

echo "=== OpenClaw Gateway Entrypoint ==="
echo "Timestamp: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo ""

# ── 1. EFS Health ──────────────────────────────────────────────────────────

echo "--- EFS Mount Check ---"

if [ ! -d /root/.openclaw ]; then
    echo "FATAL: /root/.openclaw does not exist. Is EFS mounted?"
    echo "Check: task definition volume mounts, EFS access point, security groups."
    exit 1
fi

if [ ! -w /root/.openclaw ]; then
    echo "FATAL: /root/.openclaw is not writable."
    echo "Check: EFS access point POSIX permissions, mount options."
    exit 1
fi

echo "EFS mounted and writable: OK"

# Check if this is first boot (no config yet)
FIRST_BOOT=false
if [ ! -f "$CONFIG" ]; then
    echo "No openclaw.json found — this is first boot or EFS was just hydrated."
    FIRST_BOOT=true
fi

echo ""

# ── 2. Ensure directory structure ─────────────────────────────────────────

mkdir -p /root/.openclaw/memory/daily \
         /root/.openclaw/memory/metrics/session-reports \
         /root/.openclaw/agents/main/agent \
         /root/.openclaw/hooks/transforms \
         /root/.openclaw/config-profiles \
         /root/.openclaw/workspace

# ── 3. Inject secrets from env into config ────────────────────────────────

echo "--- Secret Injection ---"

if [ -f "$CONFIG" ]; then
    python3 << 'PYEOF'
import json, os

config_path = '/root/.openclaw/openclaw.json'
with open(config_path) as f:
    config = json.load(f)

injected = 0

# Inject ANTHROPIC_API_KEY into env section
if os.environ.get('ANTHROPIC_API_KEY'):
    config.setdefault('env', {})
    config['env']['ANTHROPIC_API_KEY'] = os.environ['ANTHROPIC_API_KEY']
    injected += 1
    print("  Injected: ANTHROPIC_API_KEY → openclaw.json env")

# Inject TELEGRAM_BOT_TOKEN
# Walk config looking for telegram-related token fields
if os.environ.get('TELEGRAM_BOT_TOKEN'):
    def inject_telegram(obj, path=''):
        if isinstance(obj, dict):
            for k, v in obj.items():
                key_lower = k.lower()
                if 'token' in key_lower and ('telegram' in path.lower() or 'bot' in key_lower):
                    if isinstance(v, str):
                        obj[k] = os.environ['TELEGRAM_BOT_TOKEN']
                        print(f"  Injected: TELEGRAM_BOT_TOKEN → {path}.{k}")
                        return True
                if inject_telegram(v, f'{path}.{k}'):
                    return True
        return False

    if not inject_telegram(config):
        print("  WARNING: Could not find telegram token field in config.")
        print("  You may need to set it manually in openclaw.json.")
    else:
        injected += 1

# Inject MOONSHOT_API_KEY into env (some OpenClaw versions read from env)
if os.environ.get('MOONSHOT_API_KEY'):
    config.setdefault('env', {})
    config['env']['MOONSHOT_API_KEY'] = os.environ['MOONSHOT_API_KEY']
    injected += 1
    print("  Injected: MOONSHOT_API_KEY → openclaw.json env")

with open(config_path, 'w') as f:
    json.dump(config, f, indent=2, ensure_ascii=False)
    f.write('\n')

print(f"  Total injected into openclaw.json: {injected}")
PYEOF

else
    echo "  No openclaw.json to patch — skipping (first boot?)"
fi

# Inject into auth-profiles.json
if [ -f "$AUTH_PROFILES" ]; then
    python3 << 'PYEOF'
import json, os

auth_path = '/root/.openclaw/agents/main/agent/auth-profiles.json'
with open(auth_path) as f:
    auth = json.load(f)

injected = 0

def inject_keys(obj, path=''):
    global injected
    if isinstance(obj, dict):
        for k, v in obj.items():
            key_lower = k.lower()
            # Replace CHANGE_ME with actual key based on context
            if v == 'CHANGE_ME' and key_lower in ('apikey', 'api_key', 'key', 'token'):
                # Try to match by parent context
                path_lower = path.lower()
                if 'moonshot' in path_lower or 'kimi' in path_lower:
                    env_key = os.environ.get('MOONSHOT_API_KEY', '')
                elif 'openai' in path_lower or 'gpt' in path_lower:
                    env_key = os.environ.get('OPENAI_API_KEY', '')
                elif 'anthropic' in path_lower or 'claude' in path_lower:
                    env_key = os.environ.get('ANTHROPIC_API_KEY', '')
                else:
                    env_key = ''

                if env_key:
                    obj[k] = env_key
                    injected += 1
                    print(f"  Injected: {path}.{k} (from env)")
                else:
                    print(f"  SKIPPED: {path}.{k} (no matching env var)")
            else:
                inject_keys(v, f'{path}.{k}')
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            inject_keys(v, f'{path}[{i}]')

inject_keys(auth)

with open(auth_path, 'w') as f:
    json.dump(auth, f, indent=2, ensure_ascii=False)
    f.write('\n')

print(f"  Total injected into auth-profiles.json: {injected}")
PYEOF

else
    echo "  No auth-profiles.json to patch."
fi

echo ""

# ── 4. Clear stale sessions ──────────────────────────────────────────────

echo "--- Session Cleanup ---"
rm -rf /tmp/openclaw/sessions/* 2>/dev/null || true
echo "Cleared /tmp/openclaw/sessions/"

# CRITICAL: Do NOT persist sessions on EFS. They cause bloat.
# Sessions stay in /tmp (ephemeral container storage).
# If sessions were accidentally written to EFS, clean them:
rm -rf /root/.openclaw/sessions 2>/dev/null || true

echo ""

# ── 5. Harden memory (first boot) ────────────────────────────────────────

if [ "$FIRST_BOOT" = "true" ] || [ ! -f "$MEMORY_DIR/MEMORY.md" ]; then
    echo "--- Memory Hardening (first boot) ---"
    if [ -f /opt/openbot/scripts/harden-memory.sh ]; then
        bash /opt/openbot/scripts/harden-memory.sh 2>&1 | tail -15
    else
        echo "harden-memory.sh not found — creating minimal structure"
        [ ! -f "$MEMORY_DIR/MEMORY.md" ] && echo "# OpenClaw Memory" > "$MEMORY_DIR/MEMORY.md"
        [ ! -f "$MEMORY_DIR/lessons.json" ] && echo "[]" > "$MEMORY_DIR/lessons.json"
        [ ! -f "$MEMORY_DIR/current-work.json" ] && echo '{"active_tasks":[],"recently_completed":[],"blocked":[]}' > "$MEMORY_DIR/current-work.json"
        [ ! -f "$MEMORY_DIR/taskboard.json" ] && echo '{"pending":[],"claimed":[],"done":[]}' > "$MEMORY_DIR/taskboard.json"
    fi
    echo ""
fi

# ── 6. Verify config ─────────────────────────────────────────────────────

echo "--- Pre-Start Verification ---"

READY=true

if [ -f "$CONFIG" ]; then
    if python3 -c "import json; json.load(open('$CONFIG'))" 2>/dev/null; then
        echo "openclaw.json:     valid JSON"
    else
        echo "FATAL: openclaw.json is invalid JSON"
        READY=false
    fi

    # Check for remaining CHANGE_ME
    CM=$(grep -c "CHANGE_ME" "$CONFIG" 2>/dev/null || echo "0")
    if [ "$CM" -gt 0 ]; then
        echo "WARNING: $CM CHANGE_ME values remain in openclaw.json"
        echo "Some credentials may not have been injected from env."
        # Not fatal — some optional fields may be CHANGE_ME
    fi
else
    echo "FATAL: No openclaw.json found."
    echo "EFS may not be hydrated. Run the hydration task first."
    READY=false
fi

if [ -f "$MEMORY_DIR/MEMORY.md" ]; then
    echo "MEMORY.md:         present ($(wc -l < "$MEMORY_DIR/MEMORY.md") lines)"
else
    echo "WARNING: MEMORY.md missing"
fi

echo "Node.js:           $(node --version)"
echo "OpenClaw:          $(openclaw --version 2>/dev/null || echo 'not found')"
echo ""

if [ "$READY" = "false" ]; then
    echo "FATAL: Pre-start checks failed. Exiting."
    exit 1
fi

# ── 7. Start gateway ─────────────────────────────────────────────────────

echo "=== Starting OpenClaw Gateway ==="
echo "Port: 18789"
echo "Config: $CONFIG"
echo ""

# Exec replaces shell with gateway process (PID 1 for signal handling)
exec openclaw gateway
