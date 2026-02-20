#!/bin/bash
# bootstrap-hostinger.sh — Stand up OpenClaw on a generic VPS (Hostinger, etc.)
#
# Replaces bootstrap-new-ec2.sh for non-AWS environments.
# No SSM, no EC2 metadata, no AWS dependencies. Just a VPS with SSH.
#
# Phases:
#   0. Pre-flight (disk, RAM, OS detection)
#   1. OS hardening (ufw, fail2ban, unattended-upgrades)
#   2. System deps (Node 22, Python 3, git, jq)
#   3. OpenClaw gateway (npm install, systemd service)
#   4. OpenBot runtime (clawedbot-install.sh --yes)
#   5. VPN setup (Tailscale or WireGuard stub)
#   6. Restore from transplant (if --from-transplant provided)
#   7. Harden memory system
#   8. Credential templating
#   9. Verification
#
# Usage:
#   sudo bash bootstrap-hostinger.sh --yes
#   sudo bash bootstrap-hostinger.sh --dry-run
#   sudo bash bootstrap-hostinger.sh --yes --from-transplant /tmp/openclaw-transplant
#   sudo bash bootstrap-hostinger.sh --yes --skip-hardening --skip-vpn
#
# Designed for: Ubuntu 22.04 / 24.04 on any VPS provider.

set -euo pipefail

# ── Args ───────────────────────────────────────────────────────────────────

FLAG_YES=false
FLAG_DRY_RUN=false
FLAG_SKIP_HARDENING=false
FLAG_SKIP_VPN=false
TRANSPLANT_DIR=""
OPENCLAW_VERSION="latest"
VPN_TYPE="tailscale"  # tailscale | wireguard | none
GATEWAY_BIND="127.0.0.1"  # default: localhost only (safe)

while [[ $# -gt 0 ]]; do
    case "$1" in
        --yes|-y)           FLAG_YES=true; shift ;;
        --dry-run)          FLAG_DRY_RUN=true; shift ;;
        --from-transplant)  TRANSPLANT_DIR="$2"; shift 2 ;;
        --skip-hardening)   FLAG_SKIP_HARDENING=true; shift ;;
        --skip-vpn)         FLAG_SKIP_VPN=true; VPN_TYPE="none"; shift ;;
        --vpn)              VPN_TYPE="$2"; shift 2 ;;
        --openclaw-version) OPENCLAW_VERSION="$2"; shift 2 ;;
        --bind)             GATEWAY_BIND="$2"; shift 2 ;;
        --help|-h)
            cat <<EOF
Usage: $0 [OPTIONS]

OPTIONS:
    --yes                     Execute all phases (required for changes)
    --dry-run                 Preview what would happen
    --from-transplant <path>  Restore memory/config from consciousness export
    --skip-hardening          Skip UFW + fail2ban setup
    --skip-vpn                Skip VPN installation
    --vpn <type>              VPN type: tailscale (default) or wireguard
    --openclaw-version <ver>  Pin OpenClaw npm version (default: latest)
    --bind <addr>             Gateway bind address (default: 127.0.0.1)
    --help                    Show this help

EXAMPLES:
    # Preview
    sudo bash $0 --dry-run

    # Fresh install
    sudo bash $0 --yes

    # Migrate from AWS (with transplant tarball)
    sudo bash $0 --yes --from-transplant /tmp/openclaw-transplant

    # Fresh install, skip VPN (already have WireGuard via Hostinger)
    sudo bash $0 --yes --skip-vpn
EOF
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
echo "  OpenClaw VPS Bootstrap (Hostinger / Generic)"
echo "  Timestamp: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo "  OpenClaw version: $OPENCLAW_VERSION"
echo "  Transplant: ${TRANSPLANT_DIR:-none}"
echo "  VPN: $VPN_TYPE"
echo "  Gateway bind: $GATEWAY_BIND"
echo "============================================================"
echo ""

# ── Phase 0: Pre-flight ───────────────────────────────────────────────────

echo "=== Phase 0: Pre-flight ==="

if [[ $EUID -ne 0 ]]; then
    echo "ERROR: Must run as root (use sudo)"
    exit 1
fi
echo "  Running as root: OK"

# Detect OS
if [ -f /etc/os-release ]; then
    . /etc/os-release
    echo "  OS: $PRETTY_NAME"
    if [[ "$ID" != "ubuntu" && "$ID" != "debian" ]]; then
        echo "  WARNING: This script is tested on Ubuntu/Debian. Other distros may need adjustments."
    fi
else
    echo "  OS: unknown"
fi

# Check disk
AVAIL_MB=$(df -m /root | tail -1 | awk '{print $4}')
echo "  Disk available: ${AVAIL_MB}MB"
if [ "$AVAIL_MB" -lt 2000 ]; then
    echo "  WARNING: Less than 2GB free. Recommend at least 5GB."
fi

# Check RAM
TOTAL_RAM=$(free -m | awk '/^Mem:/{print $2}')
echo "  RAM: ${TOTAL_RAM}MB"
if [ "$TOTAL_RAM" -lt 3500 ]; then
    echo "  WARNING: Less than 4GB RAM. OpenClaw needs ~1GB, OpenBot needs ~0.5GB."
    echo "  Minimum: 4GB. Recommended: 8GB (if running browser automation)."
fi

# Check transplant dir
if [ -n "$TRANSPLANT_DIR" ]; then
    if [ -d "$TRANSPLANT_DIR" ]; then
        echo "  Transplant dir: $TRANSPLANT_DIR (found)"
        if [ -f "$TRANSPLANT_DIR/manifest.json" ]; then
            echo "  Manifest: $(python3 -c "import json,sys; m=json.load(open('$TRANSPLANT_DIR/manifest.json')); print(f'exported {m[\"exported_at\"]} from {m.get(\"hostname\",\"unknown\")}')" 2>/dev/null || echo 'present')"
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
    if ! $FLAG_SKIP_HARDENING; then
        echo "  Phase 1: OS hardening (ufw, fail2ban, unattended-upgrades)"
    fi
    echo "  Phase 2: Install system deps (Node 22, python3, git, jq)"
    echo "  Phase 3: Install OpenClaw $OPENCLAW_VERSION + systemd service"
    echo "  Phase 4: Clone + install OpenBot (clawedbot-install.sh --yes)"
    if [ "$VPN_TYPE" != "none" ]; then
        echo "  Phase 5: Install $VPN_TYPE"
    fi
    if [ -n "$TRANSPLANT_DIR" ]; then
        echo "  Phase 6: Restore from transplant ($TRANSPLANT_DIR)"
    fi
    echo "  Phase 7: Harden memory system"
    echo "  Phase 8: Template credentials (CHANGE_ME placeholders)"
    echo "  Phase 9: Verify everything"
    exit 0
fi

if ! $FLAG_YES; then
    echo "No --yes flag provided. Run with --yes to execute, or --dry-run to preview."
    exit 0
fi

# ── Phase 1: OS Hardening ────────────────────────────────────────────────

if ! $FLAG_SKIP_HARDENING; then
    echo "=== Phase 1: OS Hardening ==="

    # Update packages
    echo "  Updating packages..."
    apt-get update -qq
    apt-get upgrade -y -qq 2>&1 | tail -3

    # Install security essentials
    echo "  Installing security tools..."
    apt-get install -y -qq ufw fail2ban unattended-upgrades

    # UFW firewall
    echo "  Configuring UFW..."
    ufw default deny incoming 2>/dev/null || true
    ufw default allow outgoing 2>/dev/null || true

    # Allow SSH (critical — don't lock yourself out)
    ufw allow 22/tcp 2>/dev/null || true

    # DO NOT open gateway port publicly — it should only be reachable via VPN
    # If you need it on the VPN interface, add a rule like:
    #   ufw allow in on tailscale0 to any port 18789
    # But not here by default.

    # Enable UFW (non-interactive)
    echo "y" | ufw enable 2>/dev/null || true
    echo "  UFW: $(ufw status | head -1)"

    # fail2ban
    echo "  Configuring fail2ban..."
    if [ ! -f /etc/fail2ban/jail.local ]; then
        cat > /etc/fail2ban/jail.local << 'F2BEOF'
[DEFAULT]
bantime  = 3600
findtime = 600
maxretry = 5

[sshd]
enabled = true
port    = ssh
filter  = sshd
logpath = /var/log/auth.log
maxretry = 3
F2BEOF
    fi
    systemctl enable fail2ban 2>/dev/null || true
    systemctl restart fail2ban 2>/dev/null || true
    echo "  fail2ban: enabled"

    # Unattended upgrades (security patches only)
    echo "  Enabling unattended security upgrades..."
    dpkg-reconfigure -f noninteractive unattended-upgrades 2>/dev/null || true
    echo "  unattended-upgrades: enabled"

    echo ""
else
    echo "=== Phase 1: OS Hardening (skipped) ==="
    echo ""
fi

# ── Phase 2: System Dependencies ─────────────────────────────────────────

echo "=== Phase 2: System Dependencies ==="

apt-get update -qq
apt-get install -y -qq curl git jq python3 python3-venv python3-pip unzip
echo "  Base deps: OK"

# Node.js 22
NODE_VERSION=$(node --version 2>/dev/null || echo "none")
NODE_MAJOR=$(echo "$NODE_VERSION" | sed 's/v//' | cut -d. -f1 2>/dev/null || echo "0")
if [ "$NODE_MAJOR" -lt 22 ] 2>/dev/null; then
    echo "  Installing Node.js 22..."
    curl -fsSL https://deb.nodesource.com/setup_22.x | bash - 2>&1 | tail -3
    apt-get install -y -qq nodejs
    echo "  Node.js: $(node --version)"
else
    echo "  Node.js: $NODE_VERSION (>= 22, OK)"
fi

echo ""

# ── Phase 3: OpenClaw Gateway ────────────────────────────────────────────

echo "=== Phase 3: OpenClaw Gateway ==="

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
    cat > /etc/systemd/system/openclaw-gateway.service << SVCEOF
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

# ── Phase 4: OpenBot Runtime ─────────────────────────────────────────────

echo "=== Phase 4: OpenBot Runtime ==="

if [ ! -d /opt/openbot/.git ]; then
    echo "  Cloning OpenBot repo..."
    git clone https://github.com/launchplugai/OpenBot.git /opt/openbot 2>&1 | tail -3
    echo "  Cloned to /opt/openbot"
else
    echo "  Repo exists at /opt/openbot"
    cd /opt/openbot
    git fetch origin 2>/dev/null || true
    git pull --ff-only origin master 2>/dev/null || echo "  Pull skipped (non-ff or offline)"
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

# ── Phase 5: VPN ─────────────────────────────────────────────────────────

if [ "$VPN_TYPE" != "none" ]; then
    echo "=== Phase 5: VPN ($VPN_TYPE) ==="

    case "$VPN_TYPE" in
        tailscale)
            if command -v tailscale &>/dev/null; then
                echo "  Tailscale already installed: $(tailscale version 2>/dev/null | head -1)"
            else
                echo "  Installing Tailscale..."
                curl -fsSL https://tailscale.com/install.sh | sh 2>&1 | tail -5
            fi

            if tailscale status &>/dev/null; then
                TS_IP=$(tailscale ip -4 2>/dev/null || echo "unknown")
                echo "  Tailscale: connected ($TS_IP)"

                # Allow gateway on Tailscale interface
                ufw allow in on tailscale0 to any port "$GATEWAY_PORT" 2>/dev/null || true
                echo "  UFW: opened port $GATEWAY_PORT on tailscale0"
            else
                echo ""
                echo "  !! Tailscale installed but not connected."
                echo "  !! Run: tailscale up --authkey=tskey-auth-XXXXX"
                echo "  !! Then: ufw allow in on tailscale0 to any port $GATEWAY_PORT"
            fi
            ;;
        wireguard)
            if command -v wg &>/dev/null; then
                echo "  WireGuard already installed"
            else
                echo "  Installing WireGuard..."
                apt-get install -y -qq wireguard
            fi
            echo "  WireGuard installed. Configure manually:"
            echo "    1. Create /etc/wireguard/wg0.conf"
            echo "    2. wg-quick up wg0"
            echo "    3. ufw allow in on wg0 to any port $GATEWAY_PORT"
            ;;
    esac

    echo ""
else
    echo "=== Phase 5: VPN (skipped) ==="
    echo ""
fi

# ── Phase 6: Restore from Transplant ─────────────────────────────────────

if [ -n "$TRANSPLANT_DIR" ]; then
    echo "=== Phase 6: Restore from Transplant ==="

    # Memory (most critical)
    if [ -d "$TRANSPLANT_DIR/memory" ]; then
        echo "  Restoring memory..."
        mkdir -p "$MEMORY_DIR"
        cp -a "$TRANSPLANT_DIR/memory"/* "$MEMORY_DIR/" 2>/dev/null || true
        echo "  Memory: restored"
    fi

    # Agent config
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

    # Gateway config (secrets are scrubbed)
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

    # Systemd overrides (from old box — may need tweaking)
    if [ -d "$TRANSPLANT_DIR/systemd" ]; then
        echo "  Restoring systemd overrides..."
        if [ -d "$TRANSPLANT_DIR/systemd/override.d" ]; then
            mkdir -p /etc/systemd/system/openclaw-gateway.service.d
            cp -a "$TRANSPLANT_DIR/systemd/override.d"/* /etc/systemd/system/openclaw-gateway.service.d/ 2>/dev/null || true
        fi
        # Don't overwrite the service file itself — use the fresh one from Phase 3
        systemctl daemon-reload
        echo "  Systemd overrides: restored (service file kept fresh)"
    fi

    echo ""
else
    echo "=== Phase 6: Transplant (none — fresh install) ==="
    echo ""
fi

# ── Phase 7: Harden Memory ───────────────────────────────────────────────

echo "=== Phase 7: Harden Memory ==="

if [ -f /opt/openbot/scripts/harden-memory.sh ]; then
    bash /opt/openbot/scripts/harden-memory.sh 2>&1 | tail -20
    echo "  Memory: hardened"
else
    echo "  WARNING: harden-memory.sh not found. Creating basic structure..."
    mkdir -p "$MEMORY_DIR"/{daily,metrics/session-reports}
    mkdir -p "$OPENCLAW_ROOT/workspace"
fi

echo ""

# ── Phase 8: Credential Templates ────────────────────────────────────────

echo "=== Phase 8: Credential Check ==="

# Create minimal openclaw.json if it doesn't exist
if [ ! -f "$OPENCLAW_CONFIG" ]; then
    echo "  Creating template openclaw.json..."
    cat > "$OPENCLAW_CONFIG" << 'CFGEOF'
{
  "env": {
    "ANTHROPIC_API_KEY": "CHANGE_ME"
  },
  "agents": {
    "defaults": {
      "model": {
        "primary": "claude-opus-4-6",
        "fallbacks": ["kimi-k2.5", "gpt-4o-mini"]
      }
    }
  },
  "telegram": {
    "enabled": false,
    "token": "CHANGE_ME",
    "allowedUsers": []
  },
  "gateway": {
    "port": 18789,
    "bind": "127.0.0.1"
  }
}
CFGEOF
    chmod 600 "$OPENCLAW_CONFIG"
    echo "  Template created — fill CHANGE_ME values before starting."
fi

# Check CHANGE_ME counts
if [ -f "$OPENCLAW_CONFIG" ]; then
    CHANGE_ME_COUNT=$(grep -c "CHANGE_ME" "$OPENCLAW_CONFIG" 2>/dev/null || echo "0")
    if [ "$CHANGE_ME_COUNT" -gt 0 ]; then
        echo ""
        echo "  !! $CHANGE_ME_COUNT credential(s) need to be set in $OPENCLAW_CONFIG"
        grep -n "CHANGE_ME" "$OPENCLAW_CONFIG" 2>/dev/null | while IFS= read -r line; do
            echo "     $line"
        done
        echo ""
    fi
fi

if [ -f "$AGENTS_DIR/auth-profiles.json" ]; then
    CHANGE_ME_AUTH=$(grep -c "CHANGE_ME" "$AGENTS_DIR/auth-profiles.json" 2>/dev/null || echo "0")
    if [ "$CHANGE_ME_AUTH" -gt 0 ]; then
        echo "  !! $CHANGE_ME_AUTH credential(s) need to be set in $AGENTS_DIR/auth-profiles.json"
    fi
fi

if [ ! -f /etc/openbot/credentials.yaml ]; then
    echo ""
    echo "  !! OpenBot credentials not set."
    echo "  !! Create /etc/openbot/credentials.yaml with:"
    echo "     github_token: \"ghp_YOUR_TOKEN_HERE\""
fi

# Lock down config file permissions
chmod 600 "$OPENCLAW_CONFIG" 2>/dev/null || true
[ -f "$AGENTS_DIR/auth-profiles.json" ] && chmod 600 "$AGENTS_DIR/auth-profiles.json" 2>/dev/null || true
[ -f /etc/openbot/credentials.yaml ] && chmod 600 /etc/openbot/credentials.yaml 2>/dev/null || true

echo ""
echo "  --- Credential Checklist ---"
echo "  [ ] ANTHROPIC_API_KEY      → $OPENCLAW_CONFIG env section"
echo "  [ ] Moonshot/Kimi API key  → $AGENTS_DIR/auth-profiles.json"
echo "  [ ] OpenAI API key         → $AGENTS_DIR/auth-profiles.json (if used)"
echo "  [ ] GitHub PAT             → /etc/openbot/credentials.yaml"
echo "  [ ] Telegram bot token     → $OPENCLAW_CONFIG telegram section"
if [ "$VPN_TYPE" = "tailscale" ]; then
    echo "  [ ] Tailscale auth key     → tailscale up --authkey=..."
fi
echo ""

# ── Phase 9: Verification ────────────────────────────────────────────────

echo "=== Phase 9: Verification ==="

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
verify "openclaw.json permissions" '[ "$(stat -c %a /root/.openclaw/openclaw.json)" = "600" ]'
verify "models.json" '[ -f /root/.openclaw/agents/main/agent/models.json ]'
verify "Memory dir" '[ -d /root/.openclaw/memory ]'
verify "MEMORY.md" '[ -f /root/.openclaw/memory/MEMORY.md ]'
verify "Hooks dir" '[ -d /root/.openclaw/hooks/transforms ]'
verify "Systemd unit" '[ -f /etc/systemd/system/openclaw-gateway.service ]'

if ! $FLAG_SKIP_HARDENING; then
    verify "UFW active" 'ufw status | grep -q "Status: active"'
    verify "fail2ban running" 'systemctl is-active fail2ban'
fi

if [ "$VPN_TYPE" = "tailscale" ]; then
    verify "Tailscale installed" 'command -v tailscale'
fi

echo ""
echo "  Results: $PASS passed, $FAIL failed"

# ── Start Gateway ─────────────────────────────────────────────────────────

echo ""
echo "=== Starting Gateway ==="

if [ -f "$OPENCLAW_CONFIG" ]; then
    CHANGE_ME_REMAINING=$(grep -c "CHANGE_ME" "$OPENCLAW_CONFIG" 2>/dev/null || echo "0")
    if [ "$CHANGE_ME_REMAINING" -gt 0 ]; then
        echo "  NOT starting gateway — $CHANGE_ME_REMAINING CHANGE_ME values remain."
        echo "  Fill credentials first, then:"
        echo "    systemctl enable openclaw-gateway"
        echo "    systemctl start openclaw-gateway"
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
fi

echo ""
echo "============================================================"
echo "  VPS Bootstrap Complete"
echo "============================================================"
echo ""
echo "What you have:"
echo "  - UFW firewall (SSH only, gateway behind VPN)"
echo "  - fail2ban (SSH brute-force protection)"
echo "  - Unattended security upgrades"
echo "  - OpenClaw gateway (systemd managed)"
echo "  - OpenBot runtime"
if [ -n "$TRANSPLANT_DIR" ]; then
    echo "  - Restored memory, config profiles, system prompt"
fi
echo ""
echo "What you DON'T have (vs AWS):"
echo "  - No SSM (use SSH or VPN directly)"
echo "  - No CloudWatch (use journalctl)"
echo "  - No Secrets Manager (credentials in config files, chmod 600)"
echo "  - No managed backups (set up cron with export-consciousness.sh)"
echo ""
echo "Next steps:"
echo "  1. Fill credentials:  grep -rn CHANGE_ME $OPENCLAW_ROOT/"
echo "  2. Connect VPN:       tailscale up --authkey=tskey-auth-XXXXX"
echo "  3. Start gateway:     systemctl start openclaw-gateway"
echo "  4. Diagnose:          bash /opt/openbot/scripts/fix-openclaw-gateway.sh --diagnose"
echo "  5. Test Telegram bot"
echo ""
echo "Recommended cron (weekly backup):"
echo "  0 3 * * 0 bash /opt/openbot/scripts/export-consciousness.sh 2>&1 | logger -t openclaw-backup"
echo ""
