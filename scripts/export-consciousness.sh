#!/bin/bash
# export-consciousness.sh — Export OpenClaw memory, config, and system prompt
#
# Dumps everything the crow needs to reconstitute on a fresh host:
#   - Memory (MEMORY.md, lessons, daily notes, taskboard, decisions, metrics)
#   - Config profiles (backup/normal mode switchers)
#   - Agent config (system.md, models.json, auth-profiles.json structure)
#   - Main gateway config (openclaw.json)
#   - Systemd unit + overrides
#
# Secrets are SCRUBBED from the export. API keys become CHANGE_ME placeholders.
#
# Output: /tmp/openclaw-transplant-<timestamp>.tar.gz
#
# Works on any host (VPS, EC2, local). No AWS dependencies.
#
# Usage:
#   bash /opt/openbot/scripts/export-consciousness.sh
#   bash /opt/openbot/scripts/export-consciousness.sh --dry-run
#   bash /opt/openbot/scripts/export-consciousness.sh --to-repo
#
# Modes:
#   (no args)      Full export to tarball
#   --dry-run      Show what would be exported, no tarball
#   --to-repo      Export into /opt/openbot/transplant/ (for git commit)

set -euo pipefail

MODE="${1:-export}"
TIMESTAMP=$(date +%Y%m%d-%H%M%S)
STAGING_DIR="/tmp/openclaw-transplant-staging-$$"
TARBALL="/tmp/openclaw-transplant-${TIMESTAMP}.tar.gz"
REPO_TRANSPLANT="/opt/openbot/transplant"

# Source paths
OPENCLAW_ROOT="/root/.openclaw"
CONFIG="$OPENCLAW_ROOT/openclaw.json"
MEMORY_DIR="$OPENCLAW_ROOT/memory"
AGENTS_DIR="$OPENCLAW_ROOT/agents/main/agent"
PROFILES_DIR="$OPENCLAW_ROOT/config-profiles"
SYSTEMD_UNIT="/etc/systemd/system/openclaw-gateway.service"
SYSTEMD_OVERRIDE="/etc/systemd/system/openclaw-gateway.service.d"

echo "=== OpenClaw Consciousness Export ==="
echo "Timestamp: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo "Mode: $MODE"
echo ""

# ── Inventory ──────────────────────────────────────────────────────────────

echo "--- Inventory ---"

FILES_FOUND=0
FILES_MISSING=0

check_exists() {
    local path="$1"
    local label="$2"
    if [ -e "$path" ]; then
        if [ -d "$path" ]; then
            local count
            count=$(find "$path" -type f 2>/dev/null | wc -l)
            echo "  FOUND: $label ($count files)"
        else
            local size
            size=$(du -h "$path" 2>/dev/null | cut -f1)
            echo "  FOUND: $label ($size)"
        fi
        ((FILES_FOUND++)) || true
    else
        echo "  MISS:  $label"
        ((FILES_MISSING++)) || true
    fi
}

check_exists "$CONFIG" "openclaw.json (gateway config)"
check_exists "$AGENTS_DIR/models.json" "models.json (model chain)"
check_exists "$AGENTS_DIR/auth-profiles.json" "auth-profiles.json (provider auth)"
check_exists "$AGENTS_DIR/system.md" "system.md (system prompt)"
check_exists "$MEMORY_DIR/MEMORY.md" "MEMORY.md (long-term knowledge)"
check_exists "$MEMORY_DIR/lessons.json" "lessons.json (learned lessons)"
check_exists "$MEMORY_DIR/current-work.json" "current-work.json (active tasks)"
check_exists "$MEMORY_DIR/taskboard.json" "taskboard.json (task queue)"
check_exists "$MEMORY_DIR/decisions.md" "decisions.md (arch decisions)"
check_exists "$MEMORY_DIR/conflicts.json" "conflicts.json (conflict tracker)"
check_exists "$MEMORY_DIR/daily" "daily/ (daily notes)"
check_exists "$MEMORY_DIR/metrics" "metrics/ (cost + worker scores)"
check_exists "$PROFILES_DIR" "config-profiles/ (switchable configs)"
check_exists "$SYSTEMD_UNIT" "openclaw-gateway.service"
check_exists "$SYSTEMD_OVERRIDE" "systemd overrides"

echo ""
echo "Found: $FILES_FOUND  Missing: $FILES_MISSING"
echo ""

if [ "$MODE" = "--dry-run" ]; then
    echo "=== Dry Run Complete ==="
    echo "Would export $FILES_FOUND items to: $TARBALL"
    exit 0
fi

# ── Stage ──────────────────────────────────────────────────────────────────

echo "--- Staging ---"

# Clean staging area
rm -rf "$STAGING_DIR"
mkdir -p "$STAGING_DIR"/{memory,agents,config-profiles,systemd}

# 1. Memory (the brain — most critical)
if [ -d "$MEMORY_DIR" ]; then
    cp -a "$MEMORY_DIR"/* "$STAGING_DIR/memory/" 2>/dev/null || true
    echo "  Staged: memory/"
fi

# 2. Agent config (system prompt + model definitions)
for f in models.json auth-profiles.json system.md; do
    if [ -f "$AGENTS_DIR/$f" ]; then
        cp -a "$AGENTS_DIR/$f" "$STAGING_DIR/agents/"
        echo "  Staged: agents/$f"
    fi
done

# 3. Gateway config
if [ -f "$CONFIG" ]; then
    cp -a "$CONFIG" "$STAGING_DIR/openclaw.json"
    echo "  Staged: openclaw.json"
fi

# 4. Config profiles (backup/normal mode configs)
if [ -d "$PROFILES_DIR" ]; then
    cp -a "$PROFILES_DIR"/* "$STAGING_DIR/config-profiles/" 2>/dev/null || true
    echo "  Staged: config-profiles/"
fi

# 5. Systemd unit
if [ -f "$SYSTEMD_UNIT" ]; then
    cp -a "$SYSTEMD_UNIT" "$STAGING_DIR/systemd/"
    echo "  Staged: openclaw-gateway.service"
fi
if [ -d "$SYSTEMD_OVERRIDE" ]; then
    cp -a "$SYSTEMD_OVERRIDE" "$STAGING_DIR/systemd/override.d"
    echo "  Staged: systemd overrides"
fi

# 6. Version info
echo "  Writing version manifest..."
cat > "$STAGING_DIR/manifest.json" << MANEOF
{
  "exported_at": "$(date -u +%Y-%m-%dT%H:%M:%SZ)",
  "source_instance": "$(curl -s --connect-timeout 2 http://169.254.169.254/latest/meta-data/instance-id 2>/dev/null || hostname -f 2>/dev/null || echo 'unknown')",
  "openclaw_version": "$(openclaw --version 2>/dev/null || echo 'unknown')",
  "node_version": "$(node --version 2>/dev/null || echo 'unknown')",
  "hostname": "$(hostname)",
  "files_found": $FILES_FOUND,
  "files_missing": $FILES_MISSING,
  "scrubbed": true
}
MANEOF

echo ""

# ── Scrub Secrets ──────────────────────────────────────────────────────────

echo "--- Scrubbing Secrets ---"

# Scrub openclaw.json: replace API key values with CHANGE_ME
if [ -f "$STAGING_DIR/openclaw.json" ]; then
    python3 -c "
import json, re, sys

with open('$STAGING_DIR/openclaw.json') as f:
    config = json.load(f)

def scrub(obj, path=''):
    if isinstance(obj, dict):
        for k, v in obj.items():
            key_lower = k.lower()
            if isinstance(v, str) and any(s in key_lower for s in ['key', 'token', 'secret', 'password', 'credential']):
                obj[k] = 'CHANGE_ME'
                print(f'  Scrubbed: {path}.{k}')
            else:
                scrub(v, f'{path}.{k}')
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            scrub(v, f'{path}[{i}]')

scrub(config)

with open('$STAGING_DIR/openclaw.json', 'w') as f:
    json.dump(config, f, indent=2)

print('  openclaw.json: scrubbed')
" 2>/dev/null || echo "  WARNING: Could not scrub openclaw.json (no python3?)"
fi

# Scrub auth-profiles.json
if [ -f "$STAGING_DIR/agents/auth-profiles.json" ]; then
    python3 -c "
import json

with open('$STAGING_DIR/agents/auth-profiles.json') as f:
    config = json.load(f)

def scrub(obj, path=''):
    if isinstance(obj, dict):
        for k, v in obj.items():
            key_lower = k.lower()
            if isinstance(v, str) and any(s in key_lower for s in ['key', 'token', 'secret', 'password', 'credential']):
                obj[k] = 'CHANGE_ME'
                print(f'  Scrubbed: {path}.{k}')
            elif isinstance(v, str) and key_lower in ['apikey', 'api_key']:
                obj[k] = 'CHANGE_ME'
                print(f'  Scrubbed: {path}.{k}')
            else:
                scrub(v, f'{path}.{k}')
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            scrub(v, f'{path}[{i}]')

scrub(config)

with open('$STAGING_DIR/agents/auth-profiles.json', 'w') as f:
    json.dump(config, f, indent=2)

print('  auth-profiles.json: scrubbed')
" 2>/dev/null || echo "  WARNING: Could not scrub auth-profiles.json"
fi

echo ""

# ── Exclude sessions (bloat) ──────────────────────────────────────────────

# Sessions are never exported — they cause the exact problems we're fixing
rm -rf "$STAGING_DIR"/memory/sessions 2>/dev/null || true
rm -rf "$STAGING_DIR"/config-profiles/*/sessions 2>/dev/null || true

# ── Package ────────────────────────────────────────────────────────────────

if [ "$MODE" = "--to-repo" ]; then
    echo "--- Exporting to Repo ---"
    if [ -d "/opt/openbot" ]; then
        rm -rf "$REPO_TRANSPLANT"
        mkdir -p "$REPO_TRANSPLANT"
        cp -a "$STAGING_DIR"/* "$REPO_TRANSPLANT/"
        echo "  Exported to: $REPO_TRANSPLANT/"
        echo ""
        echo "  To commit:"
        echo "    cd /opt/openbot"
        echo "    git add transplant/"
        echo "    git commit -m 'chore: export consciousness for EC2 migration'"
        echo "    git push"
    else
        echo "  ERROR: /opt/openbot not found. Falling back to tarball."
        MODE="export"
    fi
fi

if [ "$MODE" = "export" ] || [ "$MODE" = "" ]; then
    echo "--- Creating Tarball ---"
    tar czf "$TARBALL" -C "$STAGING_DIR" .
    TARBALL_SIZE=$(du -h "$TARBALL" | cut -f1)
    echo "  Created: $TARBALL ($TARBALL_SIZE)"
    echo ""
    echo "  To extract on new box:"
    echo "    mkdir -p /root/.openclaw-transplant"
    echo "    tar xzf openclaw-transplant-*.tar.gz -C /root/.openclaw-transplant"
    echo ""
    echo "  Then bootstrap (pick one):"
    echo "    bash /opt/openbot/scripts/bootstrap-hostinger.sh --yes --from-transplant /root/.openclaw-transplant"
    echo "    bash /opt/openbot/scripts/bootstrap-new-ec2.sh --yes --from-transplant /root/.openclaw-transplant"
fi

# ── Cleanup ────────────────────────────────────────────────────────────────

rm -rf "$STAGING_DIR"

echo ""
echo "=== Export Complete ==="
echo ""
echo "Exported items:"
echo "  - Memory system (MEMORY.md, lessons, daily notes, taskboard, decisions)"
echo "  - Agent config (system prompt, model chain, auth structure)"
echo "  - Gateway config (openclaw.json with scrubbed secrets)"
echo "  - Config profiles (backup/normal mode switchers)"
echo "  - Systemd service files"
echo ""
echo "NOT exported (intentional):"
echo "  - API keys (scrubbed to CHANGE_ME)"
echo "  - Sessions (bloat — start fresh)"
echo "  - Node modules / npm cache"
echo ""
echo "After transplant, you need to manually set:"
echo "  1. ANTHROPIC_API_KEY in openclaw.json env section"
echo "  2. Moonshot/Kimi API key in auth-profiles.json"
echo "  3. OpenAI API key in auth-profiles.json (if used)"
echo "  4. GitHub PAT in /etc/openbot/credentials.yaml"
echo "  5. Telegram bot token in openclaw.json"
echo "  6. Tailscale auth key (for re-joining tailnet)"
