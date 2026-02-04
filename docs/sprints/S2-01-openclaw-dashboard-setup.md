# SPRINT 2 — TICKET S2-01: OpenClaw Dashboard Setup (EC2 + Tailscale)

## Purpose

Enable remote access to an AI-powered conversational gateway (OpenClaw) running on EC2, accessible from mobile devices via Tailscale private network. This provides a secure, phone-accessible dashboard for managing AI agent interactions without exposing any public ports or requiring SSH access.

**Key Objectives:**
- Install OpenClaw CLI and gateway on existing EC2 instance
- Configure Tailscale for secure private network access
- Enable mobile browser access to the OpenClaw Control UI
- Maintain SSM-only administration (no SSH, no public inbound ports)

---

## Architecture Overview

```
┌─────────────────┐     Tailscale VPN      ┌──────────────────────┐
│  iPhone/Mobile  │◄─────────────────────►│  EC2 Instance        │
│  (Tailscale)    │    Private Network     │  - OpenClaw Gateway  │
└─────────────────┘                        │  - Tailscale         │
                                           │  - Node.js 22        │
┌─────────────────┐                        └──────────────────────┘
│  Mac/Desktop    │◄─────────────────────►           │
│  (Tailscale)    │                                  │
└─────────────────┘                                  ▼
                                           ┌──────────────────────┐
┌─────────────────┐     AWS SSM            │  Anthropic API       │
│  Admin Machine  │◄─────────────────────►│  (Claude Models)     │
│  (AWS CLI)      │    Session Manager     └──────────────────────┘
└─────────────────┘
```

---

## Infrastructure Details

### EC2 Instance
| Setting | Value |
|---------|-------|
| Instance ID | `i-0dd3b26129b0681ce` |
| Region | `us-east-2` |
| Instance Type | t3.micro (upgraded storage) |
| OS | Ubuntu (with SSM Agent) |
| Storage | 15GB EBS (expanded from 7GB) |
| Swap | 2GB (for npm/Node.js memory requirements) |

### Network Configuration
| Setting | Value |
|---------|-------|
| Tailscale IP | `100.101.182.58` |
| Tailscale Hostname | `ip-172-31-6-230` |
| Tailscale FQDN | `ip-172-31-6-230.tailb88b88.ts.net` |
| Gateway Port | `18789` |
| Inbound Public Ports | None (Tailscale only) |

### Software Versions
| Component | Version |
|-----------|---------|
| OpenClaw | `2026.2.2-3` |
| Node.js | `22.22.0` |
| Tailscale | Latest stable |
| npm | Bundled with Node.js |

---

## Setup Tasks Completed

### Task 1: Storage Expansion

**Problem:** Default 7GB EBS volume insufficient for npm packages (700+ dependencies)

**Solution:**
1. Expanded EBS volume to 15GB via AWS Console
2. Extended partition and filesystem on EC2:
   ```bash
   sudo growpart /dev/nvme0n1 1
   sudo resize2fs /dev/nvme0n1p1
   ```
3. Added swap file for Node.js memory requirements:
   ```bash
   sudo fallocate -l 2G /swapfile
   sudo chmod 600 /swapfile
   sudo mkswap /swapfile
   sudo swapon /swapfile
   echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
   ```

**Verification:**
```bash
df -h  # Shows ~14GB available
free -h  # Shows 2GB swap
```

### Task 2: OpenClaw Installation

**Prerequisites:**
- Node.js 22+ installed
- npm available
- Sufficient disk space (5GB+ recommended)
- Memory: 1GB+ RAM or swap configured

**Installation:**
```bash
# Set memory limit for npm/Node
export NODE_OPTIONS="--max-old-space-size=1024"

# Install globally
sudo npm install -g openclaw
```

**Post-Install Verification:**
```bash
openclaw --version
# Output: 2026.2.2-3
```

### Task 3: Tailscale Installation

**Purpose:** Provide secure private network access without public IP exposure

**Installation:**
```bash
curl -fsSL https://tailscale.com/install.sh | sh
sudo tailscale up
```

**Authentication:**
- Opens browser link for Tailscale login
- Links device to tailnet after authentication
- Assigns private Tailscale IP (100.x.x.x range)

**Verification:**
```bash
tailscale status
# Shows device list with IPs
```

### Task 4: OpenClaw Gateway Configuration

**Configuration File:** `/root/.openclaw/openclaw.json`

**Required Settings:**
```json
{
  "gateway": {
    "trustedProxies": ["127.0.0.1"],
    "controlUi": {
      "allowInsecureAuth": true
    }
  }
}
```

**Setting Descriptions:**

| Setting | Purpose |
|---------|---------|
| `gateway.trustedProxies` | Trust localhost for proxy headers (required when using Tailscale Serve) |
| `gateway.controlUi.allowInsecureAuth` | Allow token auth over HTTP (Tailscale provides encryption at network layer) |

**Apply Settings via CLI:**
```bash
export NODE_OPTIONS="--max-old-space-size=1024"
openclaw config set gateway.trustedProxies '["127.0.0.1"]'
openclaw config set gateway.controlUi.allowInsecureAuth true
```

### Task 5: Gateway Startup

**Environment Variables Required:**
| Variable | Purpose |
|----------|---------|
| `NODE_OPTIONS` | Memory limit for Node.js heap |
| `ANTHROPIC_API_KEY` | API key for Claude model access |

**Start Command:**
```bash
export NODE_OPTIONS="--max-old-space-size=1024"
export ANTHROPIC_API_KEY="<your-api-key>"

nohup openclaw gateway \
  --port 18789 \
  --bind tailnet \
  --dev \
  --allow-unconfigured \
  --token "<your-gateway-token>" \
  > /tmp/openclaw-gateway.log 2>&1 &
```

**Flag Descriptions:**

| Flag | Purpose |
|------|---------|
| `--port 18789` | WebSocket/HTTP port for gateway |
| `--bind tailnet` | Bind to Tailscale interface only (not public) |
| `--dev` | Development mode with relaxed requirements |
| `--allow-unconfigured` | Start without full config wizard completion |
| `--token` | Shared token for gateway authentication |

### Task 6: Tailscale Serve Setup (Optional HTTPS)

**Purpose:** Provide automatic HTTPS certificates via Tailscale

**Enable Tailscale Serve:**
1. First, enable Serve feature in Tailscale admin console (one-time)
2. Then configure on EC2:
   ```bash
   tailscale serve --bg http://127.0.0.1:18789
   ```

**Verification:**
```bash
tailscale serve status
# Shows: https://<hostname>.tailb88b88.ts.net -> proxy http://127.0.0.1:18789
```

---

## Gateway Access Methods

### Method 1: Direct Tailscale IP (HTTP)
```
http://100.101.182.58:18789/?token=<gateway-token>
```
- Requires `gateway.controlUi.allowInsecureAuth: true`
- Works when gateway bound with `--bind tailnet`

### Method 2: Tailscale Serve (HTTPS)
```
https://ip-172-31-6-230.tailb88b88.ts.net/?token=<gateway-token>
```
- Automatic TLS certificates from Tailscale
- Requires Tailscale Serve enabled in admin console

### Method 3: Control UI Settings
1. Open gateway URL in browser
2. Navigate to **Overview** tab
3. Enter gateway token in **Gateway Token** field
4. Click **Connect**

---

## Issues Encountered & Resolutions

### Issue 1: Out of Memory (OOM) During npm Install
| Aspect | Detail |
|--------|--------|
| Symptom | `npm install -g openclaw` killed by kernel OOM |
| Cause | Node.js/npm exceeded available RAM on t3.micro |
| Resolution | Added 2GB swap file |
| Prevention | Always configure swap on small instances before npm install |

### Issue 2: Disk Space Exhausted
| Aspect | Detail |
|--------|--------|
| Symptom | SSM commands failing, "no space left on device" |
| Cause | 7GB default EBS filled by npm cache + packages |
| Resolution | Expanded EBS to 15GB, extended filesystem |
| Prevention | Use 15GB+ for instances running Node.js applications |

### Issue 3: Control UI Requires Secure Context
| Aspect | Detail |
|--------|--------|
| Symptom | `control ui requires HTTPS or localhost (secure context)` |
| Cause | Browser security blocks WebSocket on non-HTTPS origins |
| Resolution | Either use Tailscale Serve (HTTPS) or set `allowInsecureAuth: true` with token auth |
| Notes | Tailscale network is encrypted, so HTTP over Tailscale is secure |

### Issue 4: Device Pairing Required
| Aspect | Detail |
|--------|--------|
| Symptom | `disconnected (1008): pairing required` |
| Cause | OpenClaw requires device pairing for Control UI by default |
| Resolution | Use `--bind tailnet` + `--dev` mode + `allowInsecureAuth` |
| Notes | Tailscale provides identity verification at network level |

### Issue 5: Tailscale Serve Not Enabled
| Aspect | Detail |
|--------|--------|
| Symptom | `tailscale serve` command hangs indefinitely |
| Cause | Tailscale Serve feature not enabled in admin console |
| Resolution | Enable via link provided in error message |
| Notes | One-time setup per tailnet |

### Issue 6: Gateway Auth Mismatch
| Aspect | Detail |
|--------|--------|
| Symptom | `password_mismatch` or `token_missing` errors |
| Cause | Auth mode/credentials mismatch between gateway and client |
| Resolution | Ensure consistent auth mode and token on both sides |
| Notes | Use `--auth token` for simplest setup |

---

## Operational Commands

### Gateway Management

**Start Gateway:**
```bash
export NODE_OPTIONS="--max-old-space-size=1024"
export ANTHROPIC_API_KEY="<key>"
nohup openclaw gateway --port 18789 --bind tailnet --dev --allow-unconfigured --token "<token>" > /tmp/openclaw-gateway.log 2>&1 &
```

**Stop Gateway:**
```bash
openclaw gateway stop
# or
pkill -f "openclaw gateway"
```

**Check Status:**
```bash
pgrep -a openclaw
cat /tmp/openclaw-gateway.log | tail -20
```

**Reload Config:**
```bash
pkill -USR1 -f openclaw-gateway
```

**View Detailed Logs:**
```bash
cat /tmp/openclaw/openclaw-$(date +%Y-%m-%d).log | tail -50
```

### Tailscale Management

**Check Status:**
```bash
tailscale status
```

**Check Serve Config:**
```bash
tailscale serve status
```

**Reset Serve:**
```bash
tailscale serve reset
```

### System Health

**Check Disk:**
```bash
df -h
```

**Check Memory:**
```bash
free -h
```

**Check Swap:**
```bash
swapon --show
```

---

## File Locations

| Path | Purpose |
|------|---------|
| `/root/.openclaw/openclaw.json` | Main configuration file |
| `/root/.openclaw/workspace/` | Agent workspace directory |
| `/root/.openclaw/canvas/` | Canvas UI static files |
| `/root/.openclaw/cron/` | Scheduled jobs configuration |
| `/tmp/openclaw-gateway.log` | Gateway stdout/stderr |
| `/tmp/openclaw/openclaw-YYYY-MM-DD.log` | Detailed daily logs |
| `/swapfile` | Swap file for memory overflow |

---

## Security Considerations

1. **Network Isolation:** Gateway binds to Tailscale interface only; not accessible from public internet
2. **Token Authentication:** Gateway requires token for all connections
3. **No SSH:** Instance administered via SSM only; no SSH port exposed
4. **Tailscale Encryption:** All traffic between devices encrypted by Tailscale
5. **API Key Storage:** Anthropic API key passed via environment variable (not stored in config files)
6. **Credential Rotation:** API keys and tokens should be rotated after initial testing

---

## Post-Setup Checklist

- [x] EBS volume expanded to 15GB
- [x] Swap file configured (2GB)
- [x] OpenClaw installed globally
- [x] Tailscale installed and authenticated
- [x] Gateway configuration applied
- [x] Gateway running and accessible
- [x] Mobile device connected successfully
- [ ] Set up systemd service for gateway auto-start
- [ ] Configure log rotation
- [ ] Rotate credentials after testing
- [ ] Document backup/restore procedure

---

## Future Improvements

1. **Systemd Service:** Create service file for automatic gateway start on reboot
2. **Log Rotation:** Configure logrotate for gateway logs
3. **Monitoring:** Add health checks and alerting
4. **Backup:** Document config backup procedure
5. **Multi-User:** Configure role-based access for multiple operators

---

## Troubleshooting Quick Reference

| Symptom | Likely Cause | Quick Fix |
|---------|--------------|-----------|
| Gateway won't start | Missing API key | Set `ANTHROPIC_API_KEY` env var |
| OOM during startup | Insufficient memory | Ensure swap is enabled |
| "Secure context required" | HTTP without allowInsecureAuth | Set config or use Tailscale Serve |
| "Pairing required" | Missing dev/tailnet flags | Use `--bind tailnet --dev` |
| Can't reach gateway | Wrong IP or port | Check `tailscale status` for IP |
| Token mismatch | Different token in UI | Match token with `--token` flag |

---

## Receipt

```json
{
  "ticket": "S2-01",
  "title": "OpenClaw Dashboard Setup",
  "status": "COMPLETE",
  "instance_id": "i-0dd3b26129b0681ce",
  "region": "us-east-2",
  "components_installed": [
    "openclaw@2026.2.2-3",
    "tailscale",
    "swap (2GB)"
  ],
  "storage_expanded": "7GB -> 15GB",
  "access_method": "Tailscale private network",
  "gateway_port": 18789,
  "dashboard_verified": true,
  "mobile_access_verified": true,
  "timestamp": "2026-02-04"
}
```
