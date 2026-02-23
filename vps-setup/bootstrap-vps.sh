#!/bin/bash
#
# Bootstrap script for OpenBot VPS
#
# Prepares a fresh Ubuntu VPS with:
#   - OpenBot automation runtime
#   - DNA Matrix (port 8000)
#   - OpenClaw gateway (port 18789)
#   - All dependencies and system services
#
# Usage:
#   sudo bash bootstrap-vps.sh [--skip-dna] [--skip-openclaw]
#
# Prerequisites:
#   - Ubuntu 20.04+ (fresh or existing)
#   - Root access
#   - Internet connectivity
#

set -euo pipefail

readonly SCRIPT_VERSION="1.0.0"
readonly OPENBOT_REPO="https://github.com/launchplugai/OpenBot.git"
readonly DNA_REPO="https://github.com/launchplugai/DNA.git"
readonly OPENBOT_DIR="/opt/openbot"
readonly DATA_DIR="/var/lib/openbot"
readonly CONFIG_DIR="/etc/openbot"

# Flags
SKIP_DNA=false
SKIP_OPENCLAW=false

# -----------------------------------------------------------------------------
# Argument parsing
# -----------------------------------------------------------------------------

while [[ $# -gt 0 ]]; do
    case "$1" in
        --skip-dna)     SKIP_DNA=true; shift ;;
        --skip-openclaw) SKIP_OPENCLAW=true; shift ;;
        --help|-h)
            echo "Usage: sudo bash $0 [--skip-dna] [--skip-openclaw]"
            exit 0
            ;;
        *)
            echo "Unknown option: $1"
            exit 1
            ;;
    esac
done

# -----------------------------------------------------------------------------
# Preflight
# -----------------------------------------------------------------------------

if [[ $EUID -ne 0 ]]; then
    echo "[ERROR] This script must be run as root (use sudo)"
    exit 1
fi

echo "============================================================"
echo "  OpenBot VPS Bootstrap v${SCRIPT_VERSION}"
echo "  Timestamp: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo "============================================================"
echo ""

# -----------------------------------------------------------------------------
# Step 1: System packages
# -----------------------------------------------------------------------------

echo "=== Step 1: System packages ==="

apt-get update -qq
apt-get install -y -qq \
    git \
    python3 \
    python3-pip \
    python3-venv \
    curl \
    jq

echo "[OK] System packages installed"
echo ""

# -----------------------------------------------------------------------------
# Step 2: OpenBot installation
# -----------------------------------------------------------------------------

echo "=== Step 2: OpenBot installation ==="

if [[ -d "$OPENBOT_DIR/.git" ]]; then
    echo "[INFO] OpenBot repo already exists at $OPENBOT_DIR, pulling latest..."
    cd "$OPENBOT_DIR"
    git fetch origin
    git pull --ff-only origin master || echo "[WARN] Pull failed, continuing with current state"
else
    echo "[INFO] Cloning OpenBot..."
    git clone "$OPENBOT_REPO" "$OPENBOT_DIR"
fi

# Run the clawedbot installer
if [[ -f "$OPENBOT_DIR/scripts/clawedbot-install.sh" ]]; then
    echo "[INFO] Running clawedbot installer..."
    bash "$OPENBOT_DIR/scripts/clawedbot-install.sh" --yes
else
    echo "[INFO] Running standard installer..."
    bash "$OPENBOT_DIR/scripts/install.sh"
fi

echo "[OK] OpenBot installed"
echo ""

# -----------------------------------------------------------------------------
# Step 3: DNA Matrix setup (port 8000)
# -----------------------------------------------------------------------------

if ! $SKIP_DNA; then
    echo "=== Step 3: DNA Matrix setup ==="

    DNA_DIR="/opt/dna-matrix"

    if [[ -d "$DNA_DIR/.git" ]]; then
        echo "[INFO] DNA Matrix repo already exists, pulling latest..."
        cd "$DNA_DIR"
        git fetch origin
        git pull --ff-only origin main || echo "[WARN] Pull failed, continuing"
    else
        echo "[INFO] Cloning DNA Matrix..."
        git clone "$DNA_REPO" "$DNA_DIR"
    fi

    # Create a venv for DNA Matrix
    DNA_VENV="/opt/dna-matrix/venv"
    if [[ ! -d "$DNA_VENV" ]]; then
        python3 -m venv "$DNA_VENV"
    fi

    # Install dependencies
    "$DNA_VENV/bin/pip" install --upgrade pip -q
    "$DNA_VENV/bin/pip" install -r "$DNA_DIR/requirements.txt" -q
    "$DNA_VENV/bin/pip" install -e "$DNA_DIR/dna-matrix" -q 2>/dev/null || true

    # Create systemd service for DNA Matrix
    cat > /etc/systemd/system/dna-matrix.service <<'UNIT'
[Unit]
Description=DNA Matrix - Sports Parlay Risk Evaluation Engine
After=network.target

[Service]
Type=simple
User=openbot
Group=openbot
WorkingDirectory=/opt/dna-matrix
ExecStart=/opt/dna-matrix/venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000
Restart=on-failure
RestartSec=5
Environment=ENV=production
Environment=LEADING_LIGHT_ENABLED=false
Environment=SHERLOCK_ENABLED=false

[Install]
WantedBy=multi-user.target
UNIT

    systemctl daemon-reload
    systemctl enable dna-matrix.service
    systemctl start dna-matrix.service || echo "[WARN] DNA Matrix failed to start (may need config)"

    echo "[OK] DNA Matrix configured on port 8000"
    echo ""
else
    echo "=== Step 3: DNA Matrix setup (SKIPPED) ==="
    echo ""
fi

# -----------------------------------------------------------------------------
# Step 4: OpenClaw gateway setup (port 18789)
# -----------------------------------------------------------------------------

if ! $SKIP_OPENCLAW; then
    echo "=== Step 4: OpenClaw gateway setup ==="

    # Create OpenClaw data directory
    OPENCLAW_DIR="/data/.openclaw"
    mkdir -p "$OPENCLAW_DIR"

    # Copy the setup doc if it exists
    if [[ -f "$OPENBOT_DIR/vps-setup/CLAUDE_CODE_SETUP.md" ]]; then
        cp "$OPENBOT_DIR/vps-setup/CLAUDE_CODE_SETUP.md" "$OPENCLAW_DIR/"
        echo "[OK] Setup doc copied to $OPENCLAW_DIR/CLAUDE_CODE_SETUP.md"
    fi

    # Create OpenClaw config stub
    cat > "$OPENCLAW_DIR/config.yaml" <<'CONFIG'
# OpenClaw Gateway Configuration
gateway:
  host: 0.0.0.0
  port: 18789

agents:
  ralph:
    role: repository-auditor
    description: "Clones and tests target repos via openbot run"
    command: "openbot run"
  ira:
    role: infrastructure-monitor
    description: "Health checks and system status via openbot doctor"
    command: "openbot doctor"
  tess:
    role: test-analyst
    description: "Parses receipts and identifies regressions"
    command: "receipt-analysis"

services:
  dna-matrix:
    url: "http://localhost:8000"
    health: "/health"
  openbot:
    cli: "/usr/local/bin/openbot"
    config: "/etc/openbot/config.yaml"
CONFIG

    chown -R openbot:openbot "$OPENCLAW_DIR" 2>/dev/null || true

    echo "[OK] OpenClaw gateway configured on port 18789"
    echo ""
else
    echo "=== Step 4: OpenClaw gateway setup (SKIPPED) ==="
    echo ""
fi

# -----------------------------------------------------------------------------
# Step 5: Configure OpenBot for DNA Matrix
# -----------------------------------------------------------------------------

echo "=== Step 5: OpenBot config for DNA Matrix ==="

if [[ -f "$OPENBOT_DIR/runtime/config.dna-sherlock.yaml" ]]; then
    if [[ ! -f "$CONFIG_DIR/config.yaml" ]]; then
        cp "$OPENBOT_DIR/runtime/config.dna-sherlock.yaml" "$CONFIG_DIR/config.yaml"
        chown root:openbot "$CONFIG_DIR/config.yaml"
        chmod 640 "$CONFIG_DIR/config.yaml"
        echo "[OK] Copied DNA Sherlock config to $CONFIG_DIR/config.yaml"
    else
        echo "[INFO] Config already exists at $CONFIG_DIR/config.yaml, skipping"
    fi
fi

echo ""

# -----------------------------------------------------------------------------
# Step 6: Verification
# -----------------------------------------------------------------------------

echo "=== Step 6: Verification ==="

# Check OpenBot
if command -v openbot &>/dev/null; then
    echo "[OK] openbot CLI available: $(command -v openbot)"
else
    echo "[FAIL] openbot CLI not in PATH"
fi

# Check DNA Matrix
if ! $SKIP_DNA; then
    sleep 2  # Give service time to start
    if curl -sf http://localhost:8000/health > /dev/null 2>&1; then
        echo "[OK] DNA Matrix responding on port 8000"
    else
        echo "[WARN] DNA Matrix not responding yet (may need time to start)"
    fi
fi

# Check directories
for dir in "$DATA_DIR/logs" "$DATA_DIR/receipts" "$DATA_DIR/workdir"; do
    if [[ -d "$dir" ]]; then
        echo "[OK] Directory exists: $dir"
    else
        echo "[FAIL] Missing: $dir"
    fi
done

echo ""

# -----------------------------------------------------------------------------
# Summary
# -----------------------------------------------------------------------------

echo "============================================================"
echo "                   BOOTSTRAP COMPLETE"
echo "============================================================"
echo ""
echo "Services:"
echo "  OpenBot CLI:    /usr/local/bin/openbot"
if ! $SKIP_DNA; then
echo "  DNA Matrix:     http://localhost:8000 (systemd: dna-matrix.service)"
fi
if ! $SKIP_OPENCLAW; then
echo "  OpenClaw:       http://localhost:18789 (config: /data/.openclaw/config.yaml)"
fi
echo ""
echo "Agents:"
echo "  Ralph:  Repository auditor  (openbot run)"
echo "  Ira:    Infrastructure monitor (openbot doctor)"
echo "  Tess:   Test analyst (receipt analysis)"
echo ""
echo "To connect Claude Code:"
echo "  1. Copy vps-setup/dna-vps.json to ~/.claude/projects/"
echo "  2. Edit with your VPS connection details"
echo "  3. Run: claude --project dna-vps"
echo ""
echo "Quick test:"
echo "  openbot doctor"
echo "  curl -s http://localhost:8000/health | jq ."
echo ""
echo "============================================================"
