#!/bin/bash
#
# Openbot Installation Script
#
# This script installs Openbot runtime dependencies on Ubuntu EC2.
# Designed for SSM-based deployment (no SSH required).
#
# Usage: sudo ./install.sh
#

set -euo pipefail

OPENBOT_USER="openbot"
OPENBOT_HOME="/var/lib/openbot"
OPENBOT_DIRS=("logs" "receipts" "workdir")

echo "=== Openbot Installation Script ==="
echo "Timestamp: $(date -u +%Y-%m-%dT%H:%M:%SZ)"

# Check if running as root
if [[ $EUID -ne 0 ]]; then
    echo "ERROR: This script must be run as root (use sudo)"
    exit 1
fi

# Check OS
if [[ ! -f /etc/lsb-release ]]; then
    echo "WARNING: This script is designed for Ubuntu. Proceeding anyway..."
fi

echo ""
echo "=== Step 1: Installing system dependencies ==="
apt-get update -qq
apt-get install -y -qq git python3 python3-pip curl

echo ""
echo "=== Step 2: Creating openbot user ==="
if id "$OPENBOT_USER" &>/dev/null; then
    echo "User $OPENBOT_USER already exists"
else
    useradd --system --shell /bin/false --home-dir "$OPENBOT_HOME" "$OPENBOT_USER"
    echo "Created user $OPENBOT_USER"
fi

echo ""
echo "=== Step 3: Creating directories ==="
mkdir -p "$OPENBOT_HOME"
for dir in "${OPENBOT_DIRS[@]}"; do
    mkdir -p "$OPENBOT_HOME/$dir"
    echo "Created $OPENBOT_HOME/$dir"
done

# Set ownership
chown -R "$OPENBOT_USER:$OPENBOT_USER" "$OPENBOT_HOME"
chmod 750 "$OPENBOT_HOME"

echo ""
echo "=== Step 4: Installing Openbot package ==="
# Find the script directory (where install.sh is located)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"

# Install directory
INSTALL_DIR="/opt/openbot"

# If repo is not already at /opt/openbot, sync it there
if [[ "$(realpath "$REPO_ROOT")" != "$(realpath "$INSTALL_DIR" 2>/dev/null || echo "$INSTALL_DIR")" ]]; then
    echo "Syncing repo from $REPO_ROOT to $INSTALL_DIR..."
    mkdir -p "$INSTALL_DIR"
    # Use rsync if available, fallback to cp
    if command -v rsync &>/dev/null; then
        rsync -a --exclude='.git' --exclude='venv' --exclude='__pycache__' \
            --exclude='*.pyc' "$REPO_ROOT/" "$INSTALL_DIR/"
    else
        # Manual copy avoiding venv and pycache
        find "$REPO_ROOT" -maxdepth 1 -mindepth 1 \
            ! -name '.git' ! -name 'venv' ! -name '__pycache__' \
            -exec cp -r {} "$INSTALL_DIR/" \;
    fi
else
    echo "Repo already at $INSTALL_DIR"
fi

# Install python3-venv if not present
apt-get install -y -qq python3-venv 2>/dev/null || true

# Create virtual environment (idempotent)
VENV_DIR="$INSTALL_DIR/venv"
if [[ ! -d "$VENV_DIR" ]]; then
    echo "Creating virtual environment at $VENV_DIR..."
    python3 -m venv "$VENV_DIR"
else
    echo "Virtual environment already exists at $VENV_DIR"
fi

# Upgrade pip and install openbot in editable mode
echo "Installing openbot package into venv..."
"$VENV_DIR/bin/pip" install --upgrade pip -q
"$VENV_DIR/bin/pip" install -e "$INSTALL_DIR" -q

# Create /usr/local/bin/openbot wrapper
echo "Creating /usr/local/bin/openbot wrapper..."
cat > /usr/local/bin/openbot << EOF
#!/bin/bash
exec $VENV_DIR/bin/python -m openbot.cli "\$@"
EOF
chmod +x /usr/local/bin/openbot

# Remove old PYTHONPATH profile script if exists (no longer needed with venv)
rm -f /etc/profile.d/openbot.sh 2>/dev/null || true

echo ""
echo "=== Step 5: Installing systemd service ==="
if [[ -f "$REPO_ROOT/runtime/openbot.service" ]]; then
    cp "$REPO_ROOT/runtime/openbot.service" /etc/systemd/system/
    systemctl daemon-reload
    echo "Systemd service installed (not enabled - use 'systemctl enable openbot' if needed)"
else
    echo "WARNING: systemd service file not found"
fi

echo ""
echo "=== Installation Complete ==="
echo ""
echo "Verify installation with:"
echo "  openbot doctor"
echo ""
echo "Run a test with:"
echo "  openbot run --target-repo <url> --target-branch <branch> --command '<cmd>'"
echo ""
echo "For local development (no system install):"
echo "  python3 -m openbot.cli doctor --local"
echo ""
echo "Directories created:"
for dir in "${OPENBOT_DIRS[@]}"; do
    echo "  $OPENBOT_HOME/$dir"
done
