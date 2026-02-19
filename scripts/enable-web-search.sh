#!/bin/bash
# enable-web-search.sh — Enable web search for OpenClaw Gateway (Phase 1)
#
# Enables Kimi K2.5 native $web_search + OpenClaw web tools.
# No extra API keys needed — Kimi handles search server-side on Moonshot infra.
#
# Run via SSM:
#   aws ssm send-command --instance-id i-0dd3b26129b0681ce \
#     --document-name AWS-RunShellScript \
#     --parameters 'commands=["bash /opt/openbot/scripts/enable-web-search.sh"]' \
#     --region us-east-2
#
# Or paste into an SSM Session Manager terminal.

set -euo pipefail

CONFIG="/root/.openclaw/openclaw.json"
SYSTEM_PROMPT="/root/.openclaw/agents/main/agent/system.md"
MODELS_CONFIG="/root/.openclaw/agents/main/agent/models.json"
BACKUP_DIR="/root/.openclaw/config-profiles/pre-websearch-backup"

echo "=== OpenClaw Web Search Enablement (Phase 1) ==="
echo "Timestamp: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo ""

# ── 0. Preflight ──────────────────────────────────────────────────────────

echo "--- Preflight Checks ---"

if [ ! -f "$CONFIG" ]; then
    echo "FATAL: $CONFIG not found. Is OpenClaw installed?"
    exit 1
fi

if [ ! -w "$CONFIG" ]; then
    echo "FATAL: $CONFIG is not writable. Check permissions (no chattr +i!)."
    exit 1
fi

if ! command -v python3 &>/dev/null; then
    echo "FATAL: python3 not found."
    exit 1
fi

echo "Config:       $CONFIG (writable)"
echo "System prompt: $SYSTEM_PROMPT ($([ -f "$SYSTEM_PROMPT" ] && echo 'exists' || echo 'MISSING'))"
echo "Models config: $MODELS_CONFIG ($([ -f "$MODELS_CONFIG" ] && echo 'exists' || echo 'MISSING'))"
echo ""

# ── 1. Backup current config ─────────────────────────────────────────────

echo "--- Backup ---"
mkdir -p "$BACKUP_DIR"
cp "$CONFIG" "$BACKUP_DIR/openclaw.json.$(date +%s)"
[ -f "$SYSTEM_PROMPT" ] && cp "$SYSTEM_PROMPT" "$BACKUP_DIR/system.md.$(date +%s)"
[ -f "$MODELS_CONFIG" ] && cp "$MODELS_CONFIG" "$BACKUP_DIR/models.json.$(date +%s)"
echo "Backed up to $BACKUP_DIR"
echo ""

# ── 2. Patch openclaw.json ────────────────────────────────────────────────
# Uses base64-encoded Python (SSM heredocs break — ONBOARDING lesson #6)

echo "--- Patching openclaw.json ---"

PATCH_SCRIPT=$(python3 -c "
import base64
script = '''
import json, sys

config_path = '$CONFIG'

with open(config_path) as f:
    config = json.load(f)

# Ensure tools section exists
if 'tools' not in config:
    config['tools'] = {}
tools = config['tools']

# Add web tools to allow list (additive, never removes existing)
also_allow = tools.get('alsoAllow', [])
for tool in ['web_search', 'web_fetch']:
    if tool not in also_allow:
        also_allow.append(tool)
tools['alsoAllow'] = also_allow

# Enable web search and fetch
if 'web' not in tools:
    tools['web'] = {}
tools['web']['search'] = tools['web'].get('search', {})
tools['web']['search']['enabled'] = True
tools['web']['fetch'] = tools['web'].get('fetch', {})
tools['web']['fetch']['enabled'] = True

# Write back (preserve formatting)
with open(config_path, 'w') as f:
    json.dump(config, f, indent=2, ensure_ascii=False)
    f.write('\\\\n')

print('openclaw.json patched: web_search + web_fetch enabled')
'''
print(base64.b64encode(script.encode()).decode())
")

echo "$PATCH_SCRIPT" | base64 -d | python3
echo ""

# ── 3. Patch models.json — Add Kimi $web_search native tool ──────────────
# Kimi K2.5 has built-in $web_search. Runs on Moonshot infra, not EC2.
# We add it as a provider tool so OpenClaw passes it in API calls.

echo "--- Patching models.json (Kimi native search) ---"

if [ -f "$MODELS_CONFIG" ]; then
    MODELS_PATCH=$(python3 -c "
import base64
script = '''
import json, sys

models_path = '$MODELS_CONFIG'

with open(models_path) as f:
    models = json.load(f)

# models.json can be a dict or list depending on OpenClaw version
# Look for moonshot/kimi entries and add $web_search tool

def add_kimi_search(obj):
    \"\"\"Recursively find Kimi model entries and add native search tool.\"\"\"
    if isinstance(obj, dict):
        # Check if this is a model entry with moonshot/kimi provider
        provider = obj.get('provider', '')
        model = obj.get('model', '')
        model_id = obj.get('id', '')

        is_kimi = any(k in str(provider).lower() + str(model).lower() + str(model_id).lower()
                       for k in ['moonshot', 'kimi'])

        if is_kimi and ('model' in obj or 'provider' in obj):
            # Add native tools config
            if 'nativeTools' not in obj:
                obj['nativeTools'] = []
            web_search_tool = {
                'type': 'builtin_function',
                'function': {'name': '$web_search'}
            }
            # Check if already present
            existing = [t for t in obj['nativeTools']
                       if isinstance(t, dict) and
                       t.get('function', {}).get('name') == '$web_search']
            if not existing:
                obj['nativeTools'].append(web_search_tool)
                print(f'Added $web_search to Kimi entry: {model or model_id or provider}')

        # Recurse into all values
        for v in obj.values():
            add_kimi_search(v)
    elif isinstance(obj, list):
        for item in obj:
            add_kimi_search(item)

add_kimi_search(models)

with open(models_path, 'w') as f:
    json.dump(models, f, indent=2, ensure_ascii=False)
    f.write('\\\\n')

print('models.json patched')
'''
print(base64.b64encode(script.encode()).decode())
")
    echo "$MODELS_PATCH" | base64 -d | python3
else
    echo "models.json not found — skipping Kimi native tool config."
    echo "Web search will use OpenClaw framework tools instead."
fi
echo ""

# ── 4. Update system prompt ──────────────────────────────────────────────

echo "--- Updating system prompt ---"

if [ -f "$SYSTEM_PROMPT" ]; then
    # Check if web search section already exists
    if grep -q "Web Search" "$SYSTEM_PROMPT" 2>/dev/null; then
        echo "System prompt already has Web Search section — skipping."
    else
        cat >> "$SYSTEM_PROMPT" << 'PROMPT_EOF'

---

## Web Search Capability

You have access to web search. When the user asks questions that need current information — news, prices, docs, live data, recent events, anything beyond your training data:

1. Use `web_search` to find relevant information
2. Use `web_fetch` to retrieve full page content when a search result needs deeper reading
3. Cite your sources — include URLs
4. Synthesize clearly — don't dump raw results

Search proactively when the question clearly needs live data. Don't search for things you already know well. If search fails or returns nothing useful, say so honestly.
PROMPT_EOF
        echo "Appended Web Search section to system prompt."
    fi
else
    echo "WARNING: System prompt not found at $SYSTEM_PROMPT"
    echo "You may need to create it or update it manually."
fi
echo ""

# ── 5. Restart gateway ───────────────────────────────────────────────────

echo "--- Restarting Gateway ---"

# Clear stale sessions first (known issue — session bloat)
rm -rf /tmp/openclaw/sessions/*
echo "Cleared stale sessions."

systemctl restart openclaw-gateway
echo "Gateway restarting... (50s startup, waiting 60s)"
sleep 60

# ── 6. Verify ─────────────────────────────────────────────────────────────

echo "--- Verification ---"

# Service status
if systemctl is-active openclaw-gateway &>/dev/null; then
    echo "Service:  ACTIVE"
else
    echo "Service:  FAILED"
    echo "Check: journalctl -u openclaw-gateway --no-pager -n 30"
fi

# Port check
if ss -tlnp | grep -q 18789; then
    echo "Port:     18789 LISTENING"
else
    echo "Port:     18789 NOT LISTENING"
fi

# Health check
HEALTH=$(curl -s --connect-timeout 5 http://localhost:18789/ 2>&1 | head -5)
if [ -n "$HEALTH" ]; then
    echo "Health:   RESPONDING"
else
    echo "Health:   NOT RESPONDING (may need more time)"
fi

# Verify config has web search enabled
WEB_ENABLED=$(python3 -c "
import json
with open('$CONFIG') as f:
    c = json.load(f)
tools = c.get('tools', {})
also = tools.get('alsoAllow', [])
ws = tools.get('web', {}).get('search', {}).get('enabled', False)
wf = tools.get('web', {}).get('fetch', {}).get('enabled', False)
print(f'alsoAllow: {also}')
print(f'web_search: {ws}')
print(f'web_fetch: {wf}')
" 2>&1)
echo "Config:"
echo "  $WEB_ENABLED" | sed 's/^/  /'

# Memory check
echo ""
echo "--- Resources ---"
free -m | head -2
echo ""

echo "=== Phase 1 Complete ==="
echo ""
echo "What was done:"
echo "  1. Backed up configs to $BACKUP_DIR"
echo "  2. Enabled web_search + web_fetch in openclaw.json tools"
echo "  3. Added Kimi \$web_search native tool to models.json"
echo "  4. Updated system prompt with web search instructions"
echo "  5. Cleared stale sessions and restarted gateway"
echo ""
echo "Test it: message @MarvinAI_open_bot on Telegram and ask"
echo "  'What happened in the news today?'"
echo ""
echo "If search doesn't work, check:"
echo "  journalctl -u openclaw-gateway --no-pager -n 50"
echo "  cat $CONFIG | python3 -m json.tool | grep -A5 web"
echo ""
echo "Rollback: cp $BACKUP_DIR/openclaw.json.* $CONFIG && systemctl restart openclaw-gateway"
