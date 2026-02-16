#!/bin/bash
# fix-openclaw-gateway.sh — Diagnose and restart the OpenClaw gateway
# Run via: aws ssm send-command --instance-id i-0dd3b26129b0681ce \
#   --document-name AWS-RunShellScript --parameters 'commands=["bash /opt/openbot/scripts/fix-openclaw-gateway.sh"]' \
#   --region us-east-2
# Or paste into an SSM Session Manager terminal.

set -euo pipefail

echo "=== OpenClaw Gateway Diagnostics ==="
echo "Timestamp: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo ""

# 1. Service status
echo "--- Service Status ---"
systemctl status openclaw-gateway --no-pager 2>&1 || true
echo ""

# 2. Recent logs (last 50 lines)
echo "--- Recent Logs ---"
journalctl -u openclaw-gateway --no-pager -n 50 2>&1 || true
echo ""

# 3. Check if port 18789 is listening
echo "--- Port Check ---"
ss -tlnp | grep 18789 || echo "Port 18789 NOT listening"
echo ""

# 4. Disk space (session bloat is a known issue)
echo "--- Disk Usage ---"
df -h /tmp /root 2>/dev/null || df -h
echo ""
du -sh /tmp/openclaw/sessions/ 2>/dev/null || echo "No sessions dir"
echo ""

# 5. Memory
echo "--- Memory ---"
free -m
echo ""

# 6. Fix: clear stale sessions + restart
echo "=== Applying Fix ==="
echo "Clearing stale sessions..."
rm -rf /tmp/openclaw/sessions/*
echo "Cleared."

echo "Restarting openclaw-gateway..."
systemctl restart openclaw-gateway
sleep 5

# 7. Verify
echo "--- Post-fix Status ---"
systemctl is-active openclaw-gateway && echo "Service: ACTIVE" || echo "Service: FAILED"
ss -tlnp | grep 18789 && echo "Port 18789: LISTENING" || echo "Port 18789: NOT LISTENING"

# 8. Quick health check
echo "--- Health Check ---"
curl -s --connect-timeout 5 http://localhost:18789/ 2>&1 | head -20 || echo "Gateway not responding yet (may need more time)"

echo ""
echo "=== Done ==="
