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

# Copy openbot package to a system location
INSTALL_DIR="/opt/openbot"
mkdir -p "$INSTALL_DIR"
cp -r "$REPO_ROOT/openbot" "$INSTALL_DIR/"
cp -r "$REPO_ROOT/policies" "$INSTALL_DIR/"

# Create symlink for easy execution
cat > /usr/local/bin/openbot << 'EOF'
#!/bin/bash
exec python3 -m openbot.cli "$@"
EOF
chmod +x /usr/local/bin/openbot

# Add to PYTHONPATH
echo "export PYTHONPATH=/opt/openbot:\$PYTHONPATH" > /etc/profile.d/openbot.sh
chmod +x /etc/profile.d/openbot.sh

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
echo "  openbot doctor --local"
echo ""
echo "Run a test with:"
echo "  openbot run --target-repo <url> --target-branch <branch> --command '<cmd>' --local"
echo ""
echo "Directories created:"
for dir in "${OPENBOT_DIRS[@]}"; do
    echo "  $OPENBOT_HOME/$dir"
done
