#!/bin/bash
#
# Claude Code CLI Setup for EC2
#
# Installs Claude Code CLI on the OpenClaw EC2 instance.
# Auth must be provided separately (see usage below).
#
# Usage:
#   # Step 1: On your Mac (has a browser)
#   claude setup-token
#   # Complete OAuth in browser, wait for "Authentication successful"
#
#   # Step 2: Copy auth to EC2
#   scp -r ~/.claude/ root@100.101.182.58:/root/
#
#   # Step 3: Run this script on EC2
#   sudo ./scripts/setup-ccli.sh
#
#   # Step 4: Verify
#   claude "What is 2+2?"
#

set -euo pipefail

# =============================================================================
# Constants
# =============================================================================

readonly SCRIPT_NAME="$(basename "$0")"
readonly NODE_MAJOR=22

# =============================================================================
# Logging
# =============================================================================

log_info()  { echo "[INFO]  $*"; }
log_ok()    { echo "[OK]    $*"; }
log_fail()  { echo "[FAIL]  $*" >&2; }
log_warn()  { echo "[WARN]  $*" >&2; }

# =============================================================================
# Checks
# =============================================================================

check_root() {
    if [[ $EUID -ne 0 ]]; then
        log_fail "Must run as root (use sudo)"
        exit 1
    fi
}

check_node() {
    if command -v node &>/dev/null; then
        local ver
        ver=$(node --version)
        log_ok "Node.js already installed: $ver"
        return 0
    fi
    return 1
}

check_claude() {
    if command -v claude &>/dev/null; then
        local ver
        ver=$(claude --version 2>/dev/null || echo "unknown")
        log_ok "Claude Code CLI already installed: $ver"
        return 0
    fi
    return 1
}

check_auth() {
    if [[ -d /root/.claude ]] && [[ -f /root/.claude/.credentials.json || -f /root/.claude/credentials.json ]]; then
        log_ok "Claude auth credentials found"
        return 0
    fi
    log_warn "No Claude auth found at /root/.claude/"
    log_warn "Run 'claude setup-token' on a machine with a browser, then scp ~/.claude/ here"
    return 1
}

# =============================================================================
# Install
# =============================================================================

install_node() {
    log_info "Installing Node.js ${NODE_MAJOR}.x..."

    # NodeSource setup
    if [[ ! -f /etc/apt/sources.list.d/nodesource.list ]]; then
        apt-get update -qq
        apt-get install -y -qq ca-certificates curl gnupg
        mkdir -p /etc/apt/keyrings
        curl -fsSL https://deb.nodesource.com/gpgkey/nodesource-repo.gpg.key \
            | gpg --dearmor -o /etc/apt/keyrings/nodesource.gpg
        echo "deb [signed-by=/etc/apt/keyrings/nodesource.gpg] https://deb.nodesource.com/node_${NODE_MAJOR}.x nodistro main" \
            > /etc/apt/sources.list.d/nodesource.list
    fi

    apt-get update -qq
    apt-get install -y -qq nodejs

    log_ok "Node.js installed: $(node --version)"
}

install_claude() {
    log_info "Installing Claude Code CLI..."
    npm install -g @anthropic-ai/claude-code
    log_ok "Claude Code CLI installed: $(claude --version 2>/dev/null || echo 'installed')"
}

# =============================================================================
# Main
# =============================================================================

main() {
    echo "============================================================"
    echo "  Claude Code CLI Setup for EC2"
    echo "============================================================"
    echo ""

    check_root

    # Install Node.js if missing
    if ! check_node; then
        install_node
    fi

    # Install Claude Code CLI if missing
    if ! check_claude; then
        install_claude
    fi

    # Check auth
    echo ""
    echo "=== Auth Status ==="
    if check_auth; then
        echo ""
        log_info "Testing Claude Code CLI..."
        if claude --print "What is 2+2?" 2>/dev/null; then
            echo ""
            log_ok "Claude Code CLI is fully working!"
        else
            log_warn "CLI installed but auth may need refresh"
            log_warn "Try: claude setup-token (on Mac) then scp ~/.claude/ here"
        fi
    else
        echo ""
        echo "=== Next Steps ==="
        echo "  1. On your Mac:  claude setup-token"
        echo "  2. Copy auth:    scp -r ~/.claude/ root@100.101.182.58:/root/"
        echo "  3. Verify:       claude \"What is 2+2?\""
    fi

    echo ""
    echo "============================================================"
}

main "$@"
