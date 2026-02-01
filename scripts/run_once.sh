#!/bin/bash
#
# Openbot Manual Run Wrapper
#
# This script wraps the openbot run command for manual execution.
# Designed for SSM-based execution on EC2.
#
# Usage: ./run_once.sh <target-repo> <target-branch> "<command>" [health-url]
#
# Example:
#   ./run_once.sh https://github.com/org/repo main "npm test"
#   ./run_once.sh https://github.com/org/repo main "pytest" "http://localhost:8080/health"
#

set -euo pipefail

# Configuration
OPENBOT_HOME="${OPENBOT_HOME:-/var/lib/openbot}"
LOGS_DIR="${LOGS_DIR:-$OPENBOT_HOME/logs}"
RECEIPTS_DIR="${RECEIPTS_DIR:-$OPENBOT_HOME/receipts}"
WORKDIR="${WORKDIR:-$OPENBOT_HOME/workdir}"

# Parse arguments
if [[ $# -lt 3 ]]; then
    echo "Usage: $0 <target-repo> <target-branch> \"<command>\" [health-url]"
    echo ""
    echo "Arguments:"
    echo "  target-repo    Git repository URL"
    echo "  target-branch  Branch to checkout"
    echo "  command        Test command to run (quote if contains spaces)"
    echo "  health-url     Optional health check URL"
    echo ""
    echo "Environment variables:"
    echo "  OPENBOT_HOME   Base directory (default: /var/lib/openbot)"
    echo "  LOGS_DIR       Logs directory (default: \$OPENBOT_HOME/logs)"
    echo "  RECEIPTS_DIR   Receipts directory (default: \$OPENBOT_HOME/receipts)"
    echo "  WORKDIR        Work directory (default: \$OPENBOT_HOME/workdir)"
    exit 1
fi

TARGET_REPO="$1"
TARGET_BRANCH="$2"
COMMAND="$3"
HEALTH_URL="${4:-}"

echo "=== Openbot Manual Run ==="
echo "Timestamp: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo "Target repo: $TARGET_REPO"
echo "Target branch: $TARGET_BRANCH"
echo "Command: $COMMAND"
echo "Health URL: ${HEALTH_URL:-<none>}"
echo ""

# Build openbot command
OPENBOT_CMD="python3 -m openbot.cli run"
OPENBOT_CMD="$OPENBOT_CMD --target-repo \"$TARGET_REPO\""
OPENBOT_CMD="$OPENBOT_CMD --target-branch \"$TARGET_BRANCH\""
OPENBOT_CMD="$OPENBOT_CMD --command \"$COMMAND\""
OPENBOT_CMD="$OPENBOT_CMD --workdir \"$WORKDIR\""
OPENBOT_CMD="$OPENBOT_CMD --logs-dir \"$LOGS_DIR\""
OPENBOT_CMD="$OPENBOT_CMD --receipts-dir \"$RECEIPTS_DIR\""

if [[ -n "$HEALTH_URL" ]]; then
    OPENBOT_CMD="$OPENBOT_CMD --health-url \"$HEALTH_URL\""
fi

echo "Executing: $OPENBOT_CMD"
echo ""

# Execute
eval "$OPENBOT_CMD"
EXIT_CODE=$?

echo ""
echo "=== Run Complete ==="
echo "Exit code: $EXIT_CODE"
echo ""
echo "Check logs in: $LOGS_DIR"
echo "Check receipts in: $RECEIPTS_DIR"

exit $EXIT_CODE
