#!/bin/bash
# bootstrap-new-ec2.sh — Stand up a fresh EC2 as an OpenBot/OpenClaw agent
#
# This script takes a blank Amazon Linux 2 / Ubuntu EC2 and provisions it
# with OpenClaw gateway + OpenBot runtime, optionally restoring from a
# consciousness export (memory, config, system prompt).
#
# Phases:
#   1. System deps (Node 22, Python 3, git, jq, curl)
#   2. OpenClaw gateway (npm install, systemd service)
#   3. OpenBot runtime (clawedbot-install.sh --yes)
#   4. Tailscale (join tailnet)
#   5. Restore from transplant (if --from-transplant provided)
#   6. Harden memory system
#   7. Credential templating
#   8. Verification
#
# Run via SSM (on the NEW instance):
#   aws ssm send-command --instance-id i-NEW_INSTANCE_ID \
#     --document-name AWS-RunShellScript \
#     --parameters 'commands=["bash /opt/openbot/scripts/bootstrap-new-ec2.sh --yes"]' \
#     --region us-east-2
#
# Modes:
#   --dry-run                        Pre-flight only
#   --yes                            Execute all phases
#   --from-transplant <path>         Restore memory/config from export
#   --skip-tailscale                 Skip Tailscale setup
#   --openclaw-version <version>     Pin OpenClaw version (default: latest)

set -euo pipefail

# ── Args ───────────────────────────────────────────────────────────────────

FLAG_YES=false
FLAG_DRY_RUN=false
FLAG_SKIP_TAILSCALE=false
TRANSPLANT_DIR=""
OPENCLAW_VERSION="latest"

while [[ $# -gt 0 ]]; do
    case "$1" in
        --yes|-y)           FLAG_YES=true; shift ;;
        --dry-run)          FLAG_DRY_RUN=true; shift ;;
        --from-transplant)  TRANSPLANT_DIR="$2"; shift 2 ;;
        --skip-tailscale)   FLAG_SKIP_TAILSCALE=true; shift ;;
        --openclaw-version) OPENCLAW_VERSION="$2"; shift 2 ;;
        --help|-h)
            echo "Usage: $0 [--yes] [--dry-run] [--from-transplant <path>] [--skip-tailscale] [--openclaw-version <ver>]"
            exit 0
            ;;
        *) echo "Unknown flag: $1"; exit 1 ;;
    esac
done

# ── Constants ──────────────────────────────────────────────────────────────

OPENCLAW_ROOT="/root/.openclaw"
OPENCLAW_CONFIG="$OPENCLAW_ROOT/openclaw.json"
AGENTS_DIR="$OPENCLAW_ROOT/agents/main/agent"
MEMORY_DIR="$OPENCLAW_ROOT/memory"
GATEWAY_PORT=18789
STARTUP_WAIT=60

echo "============================================================"
echo "  OpenBot/OpenClaw EC2 Bootstrap"
echo "  Timestamp: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo "  OpenClaw version: $OPENCLAW_VERSION"
echo "  Transplant: ${TRANSPLANT_DIR:-none}"
echo "============================================================"
echo ""

# ── Phase 0: Pre-flight ───────────────────────────────────────────────────

echo "=== Phase 0: Pre-flight ==="

# Check root
if [[ $EUID -ne 0 ]]; then
    echo "ERROR: Must run as root (use sudo)"
    exit 1
fi
echo "  Running as root: OK"

# Detect OS
if [ -f /etc/os-release ]; then
    . /etc/os-release
    echo "  OS: $PRETTY_NAME"
else
    echo "  OS: unknown (proceeding anyway)"
fi

# Check disk
AVAIL_MB=$(df -m /root | tail -1 | awk '{print $4}')
echo "  Disk available: ${AVAIL_MB}MB"
if [ "$AVAIL_MB" -lt 1000 ]; then
    echo "  WARNING: Less than 1GB free. Recommend at least 2GB."
fi

# Check RAM
TOTAL_RAM=$(free -m | awk '/^Mem:/{print $2}')
echo "  RAM: ${TOTAL_RAM}MB"
if [ "$TOTAL_RAM" -lt 3500 ]; then
    echo "  WARNING: Less than 4GB RAM. OpenClaw + OpenBot need ~3GB minimum."
fi

# Check transplant dir if specified
if [ -n "$TRANSPLANT_DIR" ]; then
    if [ -d "$TRANSPLANT_DIR" ]; then
        echo "  Transplant dir: $TRANSPLANT_DIR (found)"
        if [ -f "$TRANSPLANT_DIR/manifest.json" ]; then
            echo "  Manifest: $(cat "$TRANSPLANT_DIR/manifest.json" | python3 -c "import json,sys; m=json.load(sys.stdin); print(f'exported {m[\"exported_at\"]} from {m[\"source_instance\"]}')" 2>/dev/null || echo 'present')"
        fi
    else
        echo "  ERROR: Transplant dir not found: $TRANSPLANT_DIR"
        exit 1
    fi
fi

echo ""

if $FLAG_DRY_RUN; then
    echo "=== Dry Run Complete ==="
    echo ""
    echo "Would execute:"
    echo "  Phase 1: Install system deps (Node 22, python3, git, jq, curl)"
    echo "  Phase 2: Install OpenClaw $OPENCLAW_VERSION + systemd service"
    echo "  Phase 3: Clone + install OpenBot (clawedbot-install.sh --yes)"
    if ! $FLAG_SKIP_TAILSCALE; then
        echo "  Phase 4: Install + configure Tailscale"
    fi
    if [ -n "$TRANSPLANT_DIR" ]; then
        echo "  Phase 5: Restore from transplant ($TRANSPLANT_DIR)"
    fi
    echo "  Phase 6: Harden memory system"
    echo "  Phase 7: Template credentials (CHANGE_ME placeholders)"
    echo "  Phase 8: Verify everything"
    exit 0
fi

if ! $FLAG_YES; then
    echo "No --yes flag provided. Run with --yes to execute, or --dry-run to preview."
    exit 0
fi

# ── Phase 1: System Dependencies ──────────────────────────────────────────

echo "=== Phase 1: System Dependencies ==="

# Detect package manager
if command -v apt-get &>/dev/null; then
    PKG_MGR="apt"
elif command -v yum &>/dev/null; then
    PKG_MGR="yum"
elif command -v dnf &>/dev/null; then
    PKG_MGR="dnf"
else
    echo "  ERROR: No supported package manager found"
    exit 1
fi
echo "  Package manager: $PKG_MGR"

# Install base deps
echo "  Installing base dependencies..."
case "$PKG_MGR" in
    apt)
        apt-get update -qq
        apt-get install -y -qq curl git jq python3 python3-venv python3-pip unzip
        ;;
    yum|dnf)
        $PKG_MGR install -y curl git jq python3 python3-pip unzip
        ;;
esac
echo "  Base deps: OK"

# Node.js 22
NODE_VERSION=$(node --version 2>/dev/null || echo "none")
NODE_MAJOR=$(echo "$NODE_VERSION" | sed 's/v//' | cut -d. -f1 2>/dev/null || echo "0")
if [ "$NODE_MAJOR" -lt 22 ] 2>/dev/null; then
    echo "  Installing Node.js 22..."
    curl -fsSL https://deb.nodesource.com/setup_22.x | bash - 2>&1 | tail -3
    case "$PKG_MGR" in
        apt) apt-get install -y -qq nodejs ;;
        yum|dnf) $PKG_MGR install -y nodejs ;;
    esac
    echo "  Node.js: $(node --version)"
else
    echo "  Node.js: $NODE_VERSION (>= 22, OK)"
fi

echo ""

# ── Phase 2: OpenClaw Gateway ─────────────────────────────────────────────

echo "=== Phase 2: OpenClaw Gateway ==="

# Install OpenClaw
CURRENT_OC=$(openclaw --version 2>/dev/null || echo "not installed")
echo "  Current: $CURRENT_OC"

echo "  Installing openclaw@$OPENCLAW_VERSION..."
npm install -g "openclaw@$OPENCLAW_VERSION" 2>&1 | tail -5
NEW_OC=$(openclaw --version 2>/dev/null || echo "unknown")
echo "  Installed: $NEW_OC"

# Create config directory structure
mkdir -p "$OPENCLAW_ROOT"
mkdir -p "$AGENTS_DIR"
mkdir -p "$OPENCLAW_ROOT/hooks/transforms"

# Create systemd service (if not restoring from transplant)
if [ ! -f /etc/systemd/system/openclaw-gateway.service ]; then
    echo "  Creating systemd service..."
    cat > /etc/systemd/system/openclaw-gateway.service << 'SVCEOF'
[Unit]
Description=OpenClaw Gateway
After=network.target

[Service]
Type=simple
ExecStart=/usr/bin/openclaw gateway
Restart=on-failure
RestartSec=10
Environment=NODE_ENV=production
WorkingDirectory=/root/.openclaw

[Install]
WantedBy=multi-user.target
SVCEOF
    systemctl daemon-reload
    echo "  Systemd service: created"
fi

echo ""

# ── Phase 3: OpenBot Runtime ──────────────────────────────────────────────

echo "=== Phase 3: OpenBot Runtime ==="

# Clone repo if not present
if [ ! -d /opt/openbot/.git ]; then
    echo "  Cloning OpenBot repo..."
    git clone https://github.com/launchplugai/OpenBot.git /opt/openbot 2>&1 | tail -3
    echo "  Cloned to /opt/openbot"
else
    echo "  Repo exists at /opt/openbot"
    cd /opt/openbot
    git fetch origin 2>/dev/null || true
    git pull --ff-only origin main 2>/dev/null || echo "  Pull skipped (non-ff or offline)"
fi

# Run clawedbot installer
echo "  Running clawedbot-install.sh..."
if [ -f /opt/openbot/scripts/clawedbot-install.sh ]; then
    bash /opt/openbot/scripts/clawedbot-install.sh --yes --no-pull 2>&1 | tail -20
    echo "  OpenBot: installed"
else
    echo "  WARNING: clawedbot-install.sh not found. Manual install needed."
fi

echo ""

# ── Phase 4: Tailscale ────────────────────────────────────────────────────

if ! $FLAG_SKIP_TAILSCALE; then
    echo "=== Phase 4: Tailscale ==="

    if command -v tailscale &>/dev/null; then
        echo "  Tailscale already installed: $(tailscale version 2>/dev/null | head -1)"
    else
        echo "  Installing Tailscale..."
        curl -fsSL https://tailscale.com/install.sh | sh 2>&1 | tail -5
    fi

    # Check if already connected
    if tailscale status &>/dev/null; then
        TS_IP=$(tailscale ip -4 2>/dev/null || echo "unknown")
        echo "  Tailscale: connected ($TS_IP)"
    else
        echo ""
        echo "  !! Tailscale installed but not connected."
        echo "  !! Run manually: tailscale up --authkey=tskey-auth-XXXXX"
        echo "  !! Or: tailscale up (interactive browser auth)"
    fi

    echo ""
else
    echo "=== Phase 4: Tailscale (skipped) ==="
    echo ""
fi

# ── Phase 5: Restore from Transplant ──────────────────────────────────────

if [ -n "$TRANSPLANT_DIR" ]; then
    echo "=== Phase 5: Restore from Transplant ==="

    # Memory (most critical)
    if [ -d "$TRANSPLANT_DIR/memory" ]; then
        echo "  Restoring memory..."
        mkdir -p "$MEMORY_DIR"
        cp -a "$TRANSPLANT_DIR/memory"/* "$MEMORY_DIR/" 2>/dev/null || true
        echo "  Memory: restored"
    fi

    # Agent config (system prompt, models, auth structure)
    if [ -d "$TRANSPLANT_DIR/agents" ]; then
        echo "  Restoring agent config..."
        mkdir -p "$AGENTS_DIR"
        for f in models.json auth-profiles.json system.md; do
            if [ -f "$TRANSPLANT_DIR/agents/$f" ]; then
                cp -a "$TRANSPLANT_DIR/agents/$f" "$AGENTS_DIR/$f"
                echo "    Restored: $f"
            fi
        done
    fi

    # Gateway config (secrets are scrubbed — need manual fill)
    if [ -f "$TRANSPLANT_DIR/openclaw.json" ]; then
        echo "  Restoring openclaw.json (secrets are CHANGE_ME — fill manually)..."
        cp -a "$TRANSPLANT_DIR/openclaw.json" "$OPENCLAW_CONFIG"
        echo "  openclaw.json: restored (NEEDS CREDENTIALS)"
    fi

    # Config profiles
    if [ -d "$TRANSPLANT_DIR/config-profiles" ]; then
        echo "  Restoring config profiles..."
        mkdir -p "$OPENCLAW_ROOT/config-profiles"
        cp -a "$TRANSPLANT_DIR/config-profiles"/* "$OPENCLAW_ROOT/config-profiles/" 2>/dev/null || true
        echo "  Config profiles: restored"
    fi

    # Systemd overrides
    if [ -d "$TRANSPLANT_DIR/systemd" ]; then
        echo "  Restoring systemd config..."
        if [ -f "$TRANSPLANT_DIR/systemd/openclaw-gateway.service" ]; then
            cp -a "$TRANSPLANT_DIR/systemd/openclaw-gateway.service" /etc/systemd/system/
        fi
        if [ -d "$TRANSPLANT_DIR/systemd/override.d" ]; then
            mkdir -p /etc/systemd/system/openclaw-gateway.service.d
            cp -a "$TRANSPLANT_DIR/systemd/override.d"/* /etc/systemd/system/openclaw-gateway.service.d/ 2>/dev/null || true
        fi
        systemctl daemon-reload
        echo "  Systemd: restored"
    fi

    echo ""
else
    echo "=== Phase 5: Transplant (none — fresh install) ==="
    echo ""
fi

# ── Phase 6: Harden Memory ────────────────────────────────────────────────

echo "=== Phase 6: Harden Memory ==="

if [ -f /opt/openbot/scripts/harden-memory.sh ]; then
    bash /opt/openbot/scripts/harden-memory.sh 2>&1 | tail -20
    echo "  Memory: hardened"
else
    echo "  WARNING: harden-memory.sh not found. Creating basic structure..."
    mkdir -p "$MEMORY_DIR"/{daily,metrics/session-reports}
    mkdir -p "$OPENCLAW_ROOT/workspace"
fi

echo ""

# ── Phase 7: Credential Templates ─────────────────────────────────────────

echo "=== Phase 7: Credential Check ==="

# Check if openclaw.json has CHANGE_ME values
if [ -f "$OPENCLAW_CONFIG" ]; then
    CHANGE_ME_COUNT=$(grep -c "CHANGE_ME" "$OPENCLAW_CONFIG" 2>/dev/null || echo "0")
    if [ "$CHANGE_ME_COUNT" -gt 0 ]; then
        echo ""
        echo "  !! $CHANGE_ME_COUNT credential(s) need to be set in $OPENCLAW_CONFIG"
        echo "  !! Search for CHANGE_ME and replace with actual values:"
        echo ""
        grep -n "CHANGE_ME" "$OPENCLAW_CONFIG" 2>/dev/null | while IFS= read -r line; do
            echo "     $line"
        done
        echo ""
    else
        echo "  openclaw.json: no CHANGE_ME placeholders found"
    fi
fi

# Check auth-profiles
if [ -f "$AGENTS_DIR/auth-profiles.json" ]; then
    CHANGE_ME_AUTH=$(grep -c "CHANGE_ME" "$AGENTS_DIR/auth-profiles.json" 2>/dev/null || echo "0")
    if [ "$CHANGE_ME_AUTH" -gt 0 ]; then
        echo "  !! $CHANGE_ME_AUTH credential(s) need to be set in $AGENTS_DIR/auth-profiles.json"
    fi
fi

# Check openbot credentials
if [ ! -f /etc/openbot/credentials.yaml ]; then
    echo ""
    echo "  !! OpenBot credentials not set."
    echo "  !! Create /etc/openbot/credentials.yaml with:"
    echo "     github_token: \"ghp_YOUR_TOKEN_HERE\""
fi

# Print master credential checklist
echo ""
echo "  --- Credential Checklist ---"
echo "  [ ] ANTHROPIC_API_KEY      → openclaw.json env section"
echo "  [ ] Moonshot/Kimi API key  → auth-profiles.json"
echo "  [ ] OpenAI API key         → auth-profiles.json (if used)"
echo "  [ ] GitHub PAT             → /etc/openbot/credentials.yaml"
echo "  [ ] Telegram bot token     → openclaw.json"
echo "  [ ] Tailscale auth key     → tailscale up --authkey=..."
echo ""

# ── Phase 8: Verification ─────────────────────────────────────────────────

echo "=== Phase 8: Verification ==="

PASS=0
FAIL=0

verify() {
    local label="$1"
    local check="$2"
    if eval "$check" &>/dev/null; then
        echo "  PASS: $label"
        ((PASS++)) || true
    else
        echo "  FAIL: $label"
        ((FAIL++)) || true
    fi
}

verify "Node.js >= 22" '[ "$(node --version | sed "s/v//" | cut -d. -f1)" -ge 22 ]'
verify "OpenClaw installed" 'command -v openclaw'
verify "npm available" 'command -v npm'
verify "python3 available" 'command -v python3'
verify "git available" 'command -v git'
verify "jq available" 'command -v jq'
verify "OpenBot repo" '[ -d /opt/openbot/.git ]'
verify "OpenBot wrapper" '[ -x /usr/local/bin/openbot ]'
verify "Config dir" '[ -d /root/.openclaw ]'
verify "openclaw.json" '[ -f /root/.openclaw/openclaw.json ]'
verify "models.json" '[ -f /root/.openclaw/agents/main/agent/models.json ]'
verify "Memory dir" '[ -d /root/.openclaw/memory ]'
verify "MEMORY.md" '[ -f /root/.openclaw/memory/MEMORY.md ]'
verify "Hooks dir" '[ -d /root/.openclaw/hooks/transforms ]'
verify "Systemd unit" '[ -f /etc/systemd/system/openclaw-gateway.service ]'

if ! $FLAG_SKIP_TAILSCALE; then
    verify "Tailscale installed" 'command -v tailscale'
fi

echo ""
echo "  Results: $PASS passed, $FAIL failed"

# ── Start Gateway ──────────────────────────────────────────────────────────

echo ""
echo "=== Starting Gateway ==="

# Only start if config exists and has no CHANGE_ME
if [ -f "$OPENCLAW_CONFIG" ]; then
    CHANGE_ME_REMAINING=$(grep -c "CHANGE_ME" "$OPENCLAW_CONFIG" 2>/dev/null || echo "0")
    if [ "$CHANGE_ME_REMAINING" -gt 0 ]; then
        echo "  NOT starting gateway — $CHANGE_ME_REMAINING CHANGE_ME values remain."
        echo "  Fill credentials first, then: systemctl start openclaw-gateway"
    else
        echo "  Starting openclaw-gateway..."
        systemctl enable openclaw-gateway
        systemctl start openclaw-gateway
        echo "  Waiting ${STARTUP_WAIT}s for startup..."
        sleep "$STARTUP_WAIT"

        if systemctl is-active openclaw-gateway &>/dev/null; then
            echo "  Gateway: ACTIVE"
        else
            echo "  Gateway: FAILED (check: journalctl -u openclaw-gateway -n 30)"
        fi

        if ss -tlnp | grep -q "$GATEWAY_PORT"; then
            echo "  Port $GATEWAY_PORT: LISTENING"
        else
            echo "  Port $GATEWAY_PORT: NOT LISTENING (may need more time)"
        fi
    fi
else
    echo "  NOT starting gateway — no openclaw.json found."
    echo "  Create config first, or restore from transplant."
fi

echo ""
echo "============================================================"
echo "  Bootstrap Complete"
echo "============================================================"
echo ""
echo "Next steps:"
echo "  1. Fill credentials (search for CHANGE_ME in config files)"
echo "  2. Join Tailscale: tailscale up --authkey=tskey-auth-XXXXX"
echo "  3. Start gateway: systemctl start openclaw-gateway"
echo "  4. Verify: bash /opt/openbot/scripts/fix-openclaw-gateway.sh --diagnose"
echo "  5. Run fix-anthropic-env.sh to ensure no env leak"
echo "  6. Test Telegram bot"
echo ""
echo "If migrating from old instance:"
echo "  - Run export-consciousness.sh on OLD box first"
echo "  - Use --from-transplant to restore on this box"
echo "  - Fill in all CHANGE_ME placeholders"
echo "  - Start gateway and verify"
echo ""
