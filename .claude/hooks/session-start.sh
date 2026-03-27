#!/bin/bash
set -euo pipefail

# Only run in remote (Claude Code on the web) environments
if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
  exit 0
fi

cd "$CLAUDE_PROJECT_DIR"

# Install the openbot (OpenClawed) package in editable mode so the CLI and imports work
pip install -e .

# Install ruff for fast Python linting
pip install ruff

# Ensure local runtime directories exist for openbot doctor/run in --local mode
mkdir -p logs receipts workdir

# Verify the openbot CLI is functional
openbot doctor --local
