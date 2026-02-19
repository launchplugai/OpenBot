#!/bin/bash
# fixit-cron.sh — Alternative to systemd: run heartbeat via cron
#
# Install:
#   crontab -e
#   */15 * * * * /opt/openbot/fixit-bot/deploy/fixit-cron.sh >> /var/log/fixit.log 2>&1
#
# This runs ONE beat every 15 minutes via cron instead of a persistent daemon.
# Same result, different scheduling. Use this if you prefer cron over systemd.

set -euo pipefail

# Ensure only one instance runs at a time
LOCKFILE="/tmp/fixit-heartbeat.lock"
exec 200>"$LOCKFILE"
flock -n 200 || exit 0

cd /opt/openbot/fixit-bot

# Run a single beat
/usr/local/bin/fixit heartbeat --once \
    --config /root/.fixit/heartbeat-config.json \
    2>&1

echo "---"
