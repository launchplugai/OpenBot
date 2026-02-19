#!/bin/bash
# enable-browser.sh — Enable full browser automation for OpenClaw Gateway (Phase 2)
#
# Two modes:
#   --sandbox    Docker sidecar browser on EC2 (self-contained, ~500MB-1GB RAM)
#   --byoc       Kimi Claw cloud browser via BYOC (zero EC2 RAM, needs Kimi membership)
#
# Run via SSM:
#   aws ssm send-command --instance-id i-0dd3b26129b0681ce \
#     --document-name AWS-RunShellScript \
#     --parameters 'commands=["bash /opt/openbot/scripts/enable-browser.sh --sandbox"]' \
#     --region us-east-2
#
# Or paste into an SSM Session Manager terminal.

set -euo pipefail

CONFIG="/root/.openclaw/openclaw.json"
MODELS_CONFIG="/root/.openclaw/agents/main/agent/models.json"
SYSTEM_PROMPT="/root/.openclaw/agents/main/agent/system.md"
BACKUP_DIR="/root/.openclaw/config-profiles/pre-browser-backup"

MODE="${1:---help}"
BROWSER_CONTAINER="ghcr.io/canyugs/openclaw-sandbox-browser:main"
BROWSER_NAME="openclaw-sandbox-browser"
CDP_PORT=9222
MEMORY_LIMIT="1g"
SHM_SIZE="1g"

usage() {
    echo "Usage: $0 [--sandbox|--byoc|--status|--stop|--help]"
    echo ""
    echo "  --sandbox   Deploy sandbox browser container on EC2 (headless, ~500MB-1GB RAM)"
    echo "  --byoc      Configure BYOC bridge to Kimi Claw cloud browser (zero EC2 RAM)"
    echo "  --status    Check browser container status and config"
    echo "  --stop      Stop and remove sandbox browser container"
    echo "  --help      Show this help"
    exit 0
}

# ── Common Functions ──────────────────────────────────────────────────────

backup_configs() {
    echo "--- Backup ---"
    mkdir -p "$BACKUP_DIR"
    cp "$CONFIG" "$BACKUP_DIR/openclaw.json.$(date +%s)"
    [ -f "$SYSTEM_PROMPT" ] && cp "$SYSTEM_PROMPT" "$BACKUP_DIR/system.md.$(date +%s)"
    [ -f "$MODELS_CONFIG" ] && cp "$MODELS_CONFIG" "$BACKUP_DIR/models.json.$(date +%s)"
    echo "Backed up to $BACKUP_DIR"
    echo ""
}

patch_openclaw_config() {
    local CDP_URL="$1"
    local PROFILE_NAME="$2"

    echo "--- Patching openclaw.json (browser: $PROFILE_NAME) ---"

    python3 -c "
import json

config_path = '$CONFIG'
cdp_url = '$CDP_URL'
profile = '$PROFILE_NAME'

with open(config_path) as f:
    config = json.load(f)

# Enable browser
config['browser'] = config.get('browser', {})
config['browser']['enabled'] = True
config['browser']['headless'] = True
config['browser']['attachOnly'] = True
config['browser']['defaultProfile'] = profile
config['browser']['remoteCdpTimeoutMs'] = 1500
config['browser']['remoteCdpHandshakeTimeoutMs'] = 3000

# Set up profile with CDP URL
if 'profiles' not in config['browser']:
    config['browser']['profiles'] = {}
config['browser']['profiles'][profile] = {
    'cdpUrl': cdp_url
}

# Enable browser tool in allow list
if 'tools' not in config:
    config['tools'] = {}
also_allow = config['tools'].get('alsoAllow', [])
for tool in ['browser', 'web_search', 'web_fetch']:
    if tool not in also_allow:
        also_allow.append(tool)
config['tools']['alsoAllow'] = also_allow

with open(config_path, 'w') as f:
    json.dump(config, f, indent=2, ensure_ascii=False)
    f.write('\n')

print(f'openclaw.json patched: browser enabled, profile={profile}, cdp={cdp_url}')
"
    echo ""
}

update_system_prompt() {
    echo "--- Updating system prompt (browser capability) ---"

    if [ -f "$SYSTEM_PROMPT" ]; then
        if grep -q "Browser Capability" "$SYSTEM_PROMPT" 2>/dev/null; then
            echo "System prompt already has Browser Capability section — skipping."
        else
            cat >> "$SYSTEM_PROMPT" << 'PROMPT_EOF'

---

## Browser Capability

You have access to a full browser. When the user needs you to:
- Visit and read web pages in full (not just search snippets)
- Interact with web applications (click, type, fill forms)
- Take screenshots of pages
- Extract data from JavaScript-rendered content
- Monitor dashboards or web UIs

Use the `browser` tool with these actions:
- `navigate` — go to a URL
- `snapshot` — get the page content as structured text with interactive element refs
- `screenshot` — capture a visual screenshot
- `click` / `type` / `select` — interact with page elements using refs from snapshot
- `wait` — wait for page load or specific elements

Always take a snapshot after navigating to understand what's on the page before interacting. Refs are ephemeral — refresh them after any navigation or interaction that changes the page.

Browser runs in headless mode. No visual UI. Work from snapshots and structured content.
PROMPT_EOF
            echo "Appended Browser Capability section to system prompt."
        fi
    else
        echo "WARNING: System prompt not found at $SYSTEM_PROMPT"
    fi
    echo ""
}

restart_and_verify() {
    echo "--- Restarting Gateway ---"
    rm -rf /tmp/openclaw/sessions/*
    echo "Cleared stale sessions."

    systemctl restart openclaw-gateway
    echo "Gateway restarting... (50s startup, waiting 60s)"
    sleep 60

    echo "--- Verification ---"

    if systemctl is-active openclaw-gateway &>/dev/null; then
        echo "Service:  ACTIVE"
    else
        echo "Service:  FAILED"
        echo "Check: journalctl -u openclaw-gateway --no-pager -n 30"
    fi

    if ss -tlnp | grep -q 18789; then
        echo "Port:     18789 LISTENING"
    else
        echo "Port:     18789 NOT LISTENING"
    fi

    HEALTH=$(curl -s --connect-timeout 5 http://localhost:18789/ 2>&1 | head -5)
    if [ -n "$HEALTH" ]; then
        echo "Health:   RESPONDING"
    else
        echo "Health:   NOT RESPONDING (may need more time)"
    fi

    # Verify browser config
    python3 -c "
import json
with open('$CONFIG') as f:
    c = json.load(f)
b = c.get('browser', {})
print(f\"Browser:  enabled={b.get('enabled', False)}, profile={b.get('defaultProfile', 'none')}\")
profiles = b.get('profiles', {})
for name, p in profiles.items():
    print(f\"  {name}: cdp={p.get('cdpUrl', 'none')}\")
also = c.get('tools', {}).get('alsoAllow', [])
print(f\"Tools:    {also}\")
"
    echo ""
    free -m | head -2
    echo ""
}

# ── Mode: Sandbox Browser ────────────────────────────────────────────────

do_sandbox() {
    echo "=== OpenClaw Browser Enablement — Sandbox Mode ==="
    echo "Timestamp: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
    echo ""

    # Preflight
    echo "--- Preflight ---"
    if ! command -v docker &>/dev/null; then
        echo "FATAL: Docker not found. Install Docker first."
        echo "  curl -fsSL https://get.docker.com | sh"
        exit 1
    fi
    echo "Docker: $(docker --version)"

    # Check available RAM
    AVAIL_MB=$(free -m | awk '/^Mem:/{print $7}')
    echo "Available RAM: ${AVAIL_MB}MB"
    if [ "$AVAIL_MB" -lt 800 ]; then
        echo "WARNING: Less than 800MB available. Browser may be unstable."
        echo "Consider --byoc mode or upgrading to t3.large."
    fi
    echo ""

    # Check if container already running
    if docker ps --format '{{.Names}}' | grep -q "$BROWSER_NAME"; then
        echo "Sandbox browser container already running."
        docker ps --filter "name=$BROWSER_NAME" --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"
        echo ""
        echo "To restart: $0 --stop && $0 --sandbox"
        echo "Skipping container deployment. Will still patch config."
        echo ""
    else
        # Pull and start
        echo "--- Deploying Sandbox Browser ---"
        echo "Pulling $BROWSER_CONTAINER ..."
        docker pull "$BROWSER_CONTAINER"
        echo ""

        echo "Starting container (headless, memory=${MEMORY_LIMIT}, shm=${SHM_SIZE}) ..."
        docker run -d \
            --name "$BROWSER_NAME" \
            --restart unless-stopped \
            --memory="$MEMORY_LIMIT" \
            --shm-size="$SHM_SIZE" \
            -e OPENCLAW_BROWSER_HEADLESS=1 \
            -p "127.0.0.1:${CDP_PORT}:9222" \
            "$BROWSER_CONTAINER"

        echo "Container started."

        # Wait for CDP to be ready
        echo "Waiting for CDP endpoint..."
        for i in $(seq 1 15); do
            if curl -sf "http://127.0.0.1:${CDP_PORT}/json/version" &>/dev/null; then
                echo "CDP ready on port $CDP_PORT"
                break
            fi
            sleep 2
        done

        # Verify CDP
        CDP_CHECK=$(curl -sf "http://127.0.0.1:${CDP_PORT}/json/version" 2>/dev/null)
        if [ -n "$CDP_CHECK" ]; then
            echo "Browser: $(echo "$CDP_CHECK" | python3 -c 'import json,sys; d=json.load(sys.stdin); print(d.get("Browser","unknown"))' 2>/dev/null || echo 'running')"
        else
            echo "WARNING: CDP not responding yet. Container may need more time."
        fi
        echo ""
    fi

    backup_configs
    patch_openclaw_config "http://127.0.0.1:${CDP_PORT}" "remote"
    update_system_prompt
    restart_and_verify

    echo "=== Phase 2 Complete (Sandbox Mode) ==="
    echo ""
    echo "Browser container: $BROWSER_NAME"
    echo "CDP endpoint:      http://127.0.0.1:$CDP_PORT"
    echo "Memory limit:      $MEMORY_LIMIT"
    echo "RAM overhead:      ~500MB-1GB"
    echo ""
    echo "Test: message @MarvinAI_open_bot and ask"
    echo "  'Go to https://news.ycombinator.com and tell me the top 3 stories'"
    echo ""
    echo "Monitor: docker stats $BROWSER_NAME --no-stream"
    echo "Logs:    docker logs $BROWSER_NAME --tail 20"
    echo "Stop:    $0 --stop"
    echo ""
    echo "Rollback:"
    echo "  docker stop $BROWSER_NAME && docker rm $BROWSER_NAME"
    echo "  cp $BACKUP_DIR/openclaw.json.* $CONFIG"
    echo "  systemctl restart openclaw-gateway"
}

# ── Mode: BYOC (Kimi Claw Cloud Browser) ─────────────────────────────────

do_byoc() {
    echo "=== OpenClaw Browser Enablement — BYOC Mode ==="
    echo "Timestamp: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
    echo ""

    echo "--- Prerequisites ---"
    echo "BYOC requires:"
    echo "  1. Kimi Claw Allegretto membership (kimi.com)"
    echo "  2. Kimi plugin installed in your OpenClaw instance"
    echo "  3. MOONSHOT_API_KEY configured"
    echo ""

    # Check if Moonshot API key is configured
    if [ -f "$MODELS_CONFIG" ]; then
        HAS_MOONSHOT=$(python3 -c "
import json
with open('$MODELS_CONFIG') as f:
    m = json.load(f)
# Check if any moonshot/kimi entry exists
s = json.dumps(m).lower()
print('yes' if 'moonshot' in s or 'kimi' in s else 'no')
" 2>/dev/null || echo "unknown")
        echo "Moonshot/Kimi in models.json: $HAS_MOONSHOT"
    fi

    if [ -n "${MOONSHOT_API_KEY:-}" ]; then
        echo "MOONSHOT_API_KEY: set"
    else
        echo "MOONSHOT_API_KEY: NOT SET"
        echo ""
        echo "To set it, add to openclaw.json env section:"
        echo '  "env": { "MOONSHOT_API_KEY": "your-key-here" }'
        echo ""
        echo "Or export before running gateway:"
        echo '  export MOONSHOT_API_KEY="your-key-here"'
    fi
    echo ""

    backup_configs

    # BYOC config — browser runs on Kimi Claw cloud, not EC2
    # The gateway connects to Kimi's infrastructure for browser operations
    echo "--- Patching openclaw.json (BYOC browser via Kimi Claw) ---"

    python3 -c "
import json

config_path = '$CONFIG'

with open(config_path) as f:
    config = json.load(f)

# Enable browser pointing to Kimi Claw
config['browser'] = config.get('browser', {})
config['browser']['enabled'] = True
config['browser']['headless'] = True
config['browser']['defaultProfile'] = 'kimi-claw'

if 'profiles' not in config['browser']:
    config['browser']['profiles'] = {}

# Kimi Claw BYOC — browser operations route through Kimi's cloud
# The gateway handles this via the Kimi plugin node connection
config['browser']['profiles']['kimi-claw'] = {
    'type': 'node',
    'description': 'Kimi Claw cloud browser via BYOC'
}

# Enable browser + web tools
if 'tools' not in config:
    config['tools'] = {}
also_allow = config['tools'].get('alsoAllow', [])
for tool in ['browser', 'web_search', 'web_fetch']:
    if tool not in also_allow:
        also_allow.append(tool)
config['tools']['alsoAllow'] = also_allow

with open(config_path, 'w') as f:
    json.dump(config, f, indent=2, ensure_ascii=False)
    f.write('\n')

print('openclaw.json patched: BYOC browser via Kimi Claw')
"
    echo ""

    update_system_prompt
    restart_and_verify

    echo "=== Phase 2 Complete (BYOC Mode) ==="
    echo ""
    echo "Browser: Kimi Claw cloud (zero EC2 RAM)"
    echo "Profile: kimi-claw (node type, routed through Kimi plugin)"
    echo ""
    echo "Next steps:"
    echo "  1. Install Kimi plugin if not already: openclaw install kimi"
    echo "  2. Link to your Kimi Claw account via kimi.com/settings/claw"
    echo "  3. Verify: openclaw browser status"
    echo ""
    echo "Test: message @MarvinAI_open_bot and ask"
    echo "  'Go to https://news.ycombinator.com and tell me the top 3 stories'"
    echo ""
    echo "Rollback:"
    echo "  cp $BACKUP_DIR/openclaw.json.* $CONFIG"
    echo "  systemctl restart openclaw-gateway"
}

# ── Mode: Status ──────────────────────────────────────────────────────────

do_status() {
    echo "=== Browser Status ==="
    echo ""

    # Container status
    echo "--- Container ---"
    if docker ps --format '{{.Names}}' 2>/dev/null | grep -q "$BROWSER_NAME"; then
        docker ps --filter "name=$BROWSER_NAME" --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"
        echo ""
        docker stats "$BROWSER_NAME" --no-stream --format "table {{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}\t{{.PIDs}}"
    else
        echo "No sandbox browser container running."
    fi
    echo ""

    # CDP check
    echo "--- CDP ---"
    CDP_CHECK=$(curl -sf "http://127.0.0.1:${CDP_PORT}/json/version" 2>/dev/null)
    if [ -n "$CDP_CHECK" ]; then
        echo "CDP endpoint: http://127.0.0.1:$CDP_PORT — RESPONDING"
        echo "$CDP_CHECK" | python3 -c 'import json,sys; d=json.load(sys.stdin); print(f"Browser: {d.get(\"Browser\",\"?\")}"); print(f"Protocol: {d.get(\"Protocol-Version\",\"?\")}")' 2>/dev/null || true
    else
        echo "CDP endpoint: http://127.0.0.1:$CDP_PORT — NOT RESPONDING"
    fi
    echo ""

    # Config check
    echo "--- Config ---"
    python3 -c "
import json
with open('$CONFIG') as f:
    c = json.load(f)
b = c.get('browser', {})
print(f\"enabled: {b.get('enabled', False)}\")
print(f\"defaultProfile: {b.get('defaultProfile', 'none')}\")
print(f\"headless: {b.get('headless', 'unset')}\")
for name, p in b.get('profiles', {}).items():
    print(f\"profile '{name}': {p}\")
also = c.get('tools', {}).get('alsoAllow', [])
print(f\"tools.alsoAllow: {also}\")
" 2>/dev/null || echo "Could not read config"
    echo ""

    # Resources
    echo "--- Resources ---"
    free -m | head -2
}

# ── Mode: Stop ────────────────────────────────────────────────────────────

do_stop() {
    echo "=== Stopping Sandbox Browser ==="
    if docker ps -a --format '{{.Names}}' 2>/dev/null | grep -q "$BROWSER_NAME"; then
        docker stop "$BROWSER_NAME" 2>/dev/null || true
        docker rm "$BROWSER_NAME" 2>/dev/null || true
        echo "Container stopped and removed."
    else
        echo "No container named $BROWSER_NAME found."
    fi
}

# ── Dispatch ──────────────────────────────────────────────────────────────

case "$MODE" in
    --sandbox)  do_sandbox ;;
    --byoc)     do_byoc ;;
    --status)   do_status ;;
    --stop)     do_stop ;;
    --help|-h)  usage ;;
    *)
        echo "Unknown option: $MODE"
        usage
        ;;
esac
