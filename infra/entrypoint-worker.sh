#!/bin/bash
# entrypoint-worker.sh — OpenBot worker entrypoint for Fargate
#
# Injects GitHub PAT from env, then runs the requested openbot command.
# Default command: openbot doctor --local
#
# Usage in ECS task:
#   command: ["run", "--target-repo", "https://github.com/launchplugai/DNA", ...]
#   command: ["doctor"]
#   command: ["doctor", "--local"]

set -euo pipefail

echo "=== OpenBot Worker Entrypoint ==="
echo "Timestamp: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo "Command: $@"
echo ""

# ── Inject GitHub PAT ─────────────────────────────────────────────────────

if [ -n "${GITHUB_TOKEN:-}" ]; then
    mkdir -p /etc/openbot
    cat > /etc/openbot/credentials.yaml << EOF
github_token: "${GITHUB_TOKEN}"
EOF
    chmod 640 /etc/openbot/credentials.yaml
    echo "GitHub PAT: injected into /etc/openbot/credentials.yaml"
else
    echo "GitHub PAT: not set (private repos will fail to clone)"
fi

echo ""

# ── Check EFS mount (if available) ────────────────────────────────────────

if [ -d /root/.openclaw/memory ]; then
    echo "EFS memory: mounted"
    LESSONS=$(python3 -c "import json; print(len(json.load(open('/root/.openclaw/memory/lessons.json'))))" 2>/dev/null || echo "?")
    echo "Lessons loaded: $LESSONS"
else
    echo "EFS memory: not mounted (stateless mode)"
fi

echo ""

# ── Run the command ───────────────────────────────────────────────────────

echo "=== Executing: openbot $@ ==="
exec /usr/local/bin/openbot "$@"
