# OpenClaw Systemd Services

Two systemd service files for EC2 deployment.

---

## openbot.service

Doctor/health check service (placeholder for Phase 2 automation):

```ini
[Unit]
Description=Openbot Automation Runtime
Documentation=https://github.com/launchplugai/openbot
After=network.target

[Service]
Type=oneshot
User=openbot
Group=openbot
WorkingDirectory=/var/lib/openbot

# Environment
Environment=PYTHONPATH=/opt/openbot
Environment=OPENBOT_HOME=/var/lib/openbot

# Execution
ExecStart=/usr/local/bin/openbot doctor

# Security hardening
NoNewPrivileges=yes
ProtectSystem=strict
ProtectHome=yes
ReadWritePaths=/var/lib/openbot
PrivateTmp=yes
ProtectKernelTunables=yes
ProtectKernelModules=yes
ProtectControlGroups=yes

# Resource limits
TimeoutStartSec=600
MemoryMax=1G

[Install]
WantedBy=multi-user.target
```

---

## openbot-run.service

Config-driven run service (the main execution service):

```ini
[Unit]
Description=Openbot Config-Driven Run
Documentation=https://github.com/launchplugai/openbot
After=network.target

[Service]
Type=oneshot
User=openbot
Group=openbot
WorkingDirectory=/var/lib/openbot

# Environment
Environment=OPENBOT_HOME=/var/lib/openbot

# Execution - uses config-driven wrapper
ExecStart=/usr/local/bin/openbot-run

# Security hardening
NoNewPrivileges=yes
ProtectSystem=strict
ProtectHome=yes
ReadWritePaths=/var/lib/openbot /etc/openbot
PrivateTmp=yes
ProtectKernelTunables=yes
ProtectKernelModules=yes
ProtectControlGroups=yes

# Resource limits
TimeoutStartSec=600
MemoryMax=1G

[Install]
WantedBy=multi-user.target
```

---

## Usage

```bash
# Install services
sudo cp runtime/openbot.service /etc/systemd/system/
sudo cp runtime/openbot-run.service /etc/systemd/system/
sudo systemctl daemon-reload

# Run doctor
sudo systemctl start openbot

# Run tests (reads /etc/openbot/config.yaml)
sudo systemctl start openbot-run

# Check results
journalctl -u openbot-run --no-pager
ls -t /var/lib/openbot/receipts/*.json | head -1

# Enable (optional - for scheduled runs)
sudo systemctl enable openbot.service openbot-run.service
```

## Security Hardening

Both services use:
- `NoNewPrivileges=yes` - Prevent privilege escalation
- `ProtectSystem=strict` - Read-only filesystem except allowed paths
- `ProtectHome=yes` - No access to home directories
- `PrivateTmp=yes` - Private /tmp mount
- `ProtectKernelTunables=yes` - No sysctl changes
- `MemoryMax=1G` - Memory limit
- `TimeoutStartSec=600` - 10 minute timeout
