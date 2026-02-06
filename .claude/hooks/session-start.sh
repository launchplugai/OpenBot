#!/bin/bash
set -euo pipefail

# Only run in remote (Claude Code on the web) environments
if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
  exit 0
fi

cd "$CLAUDE_PROJECT_DIR"

# Install the openbot package in editable mode so the CLI and imports work
pip install -e .

# Install ruff for fast Python linting
pip install ruff
