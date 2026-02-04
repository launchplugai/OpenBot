# SPRINT 2 — TICKET S2-01: OpenClaw Dashboard Setup (EC2 + Tailscale)

## Goal
Install and configure OpenClaw on the existing EC2 instance, accessible via Tailscale from mobile devices. No SSH, no public ports, SSM-only administration.

---

## Access Details

### EC2 Instance
| Setting | Value |
|---------|-------|
| Instance ID | `i-0dd3b26129b0681ce` |
| Region | `us-east-2` |
| Tailscale IP | `100.101.182.58` |
| Hostname | `ip-172-31-6-230` |
| Tailscale DNS | `ip-172-31-6-230.tailb88b88.ts.net` |

### OpenClaw Gateway
| Setting | Value |
|---------|-------|
| WebSocket URL | `ws://100.101.182.58:18789` |
| HTTP URL | `http://100.101.182.58:18789` |
| HTTPS URL (via Tailscale Serve) | `https://ip-172-31-6-230.tailb88b88.ts.net` |
| Auth Mode | Token |
| Gateway Token | `devtoken` |
| Agent Model | `anthropic/claude-opus-4-5` |
| OpenClaw Version | `2026.2.2-3` |

### Tailscale Network
| Device | IP | OS |
|--------|----|----|
| EC2 (ip-172-31-6-230) | `100.101.182.58` | Linux |
| iPhone 12 Pro Max | `100.67.196.120` | iOS |
| Marcus's Mac Studio | `100.75.246.47` | macOS |

---

## What Was Done

### 1. Disk Space Expansion
- Original EBS volume: 7GB (ran out during npm install)
- Expanded to: 15GB via AWS Console
- Extended filesystem: `growpart` + `resize2fs`
- Added 2GB swap file for npm install OOM issues

### 2. OpenClaw Installation
```bash
sudo npm install -g openclaw@2026.2.2-3
```
- 700 packages installed
- Required `NODE_OPTIONS="--max-old-space-size=1024"` to avoid heap OOM

### 3. Tailscale Installation
```bash
curl -fsSL https://tailscale.com/install.sh | sh
sudo tailscale up
```
- User authenticated via web link
- EC2 joined tailnet as `ip-172-31-6-230`

### 4. OpenClaw Gateway Configuration

**Config file:** `/root/.openclaw/openclaw.json`
```json
{
  "gateway": {
    "trustedProxies": ["127.0.0.1"],
    "controlUi": {
      "allowInsecureAuth": true
    },
    "remote": {
      "token": "c95dda7aaef299136c08a8f8794afdb3"
    }
  }
}
```

**Gateway start command:**
```bash
export NODE_OPTIONS="--max-old-space-size=1024"
export ANTHROPIC_API_KEY=<key>
nohup openclaw gateway --port 18789 --bind tailnet --dev --allow-unconfigured --token devtoken > /tmp/openclaw-gateway.log 2>&1 &
```

### 5. Tailscale Serve (HTTPS)
```bash
tailscale serve --bg http://127.0.0.1:18789
```
- Required user to enable Tailscale Serve in admin console
- Provides HTTPS at `https://ip-172-31-6-230.tailb88b88.ts.net`

---

## Issues Encountered & Resolutions

### Issue 1: OOM During npm install
- **Symptom:** `npm install -g openclaw` killed by OOM
- **Resolution:** Added 2GB swap file
```bash
sudo fallocate -l 2G /swapfile
sudo chmod 600 /swapfile
sudo mkswap /swapfile
sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
```

### Issue 2: Disk Full (100%)
- **Symptom:** SSM commands failing, no space left
- **Resolution:** User expanded EBS volume to 15GB via AWS Console
```bash
sudo growpart /dev/nvme0n1 1
sudo resize2fs /dev/nvme0n1p1
```

### Issue 3: Control UI Requires HTTPS
- **Symptom:** `control ui requires HTTPS or localhost (secure context)`
- **Resolution:** Set up Tailscale Serve for automatic HTTPS certificates

### Issue 4: Pairing Required
- **Symptom:** `disconnected (1008): pairing required`
- **Resolution:** Multiple config changes needed:
  1. Set `gateway.trustedProxies: ["127.0.0.1"]`
  2. Use `--bind tailnet` to trust Tailscale connections
  3. Set `gateway.controlUi.allowInsecureAuth: true` for HTTP token auth

### Issue 5: Password Mismatch
- **Symptom:** Password auth failed even with correct password
- **Resolution:** Switched to token auth with `--token devtoken`

### Issue 6: Tailscale Serve Not Enabled
- **Symptom:** `tailscale serve` command hung
- **Resolution:** User enabled Serve in Tailscale admin console via:
  `https://login.tailscale.com/f/serve?node=ng23Un6P5u11CNTRL`

---

## Files Created/Modified on EC2

| Path | Purpose |
|------|---------|
| `/root/.openclaw/openclaw.json` | OpenClaw config |
| `/root/.openclaw/workspace/` | Agent workspace |
| `/root/.openclaw/canvas/` | Canvas UI files |
| `/tmp/openclaw-gateway.log` | Gateway stdout/stderr |
| `/tmp/openclaw/openclaw-2026-02-04.log` | Detailed gateway logs |
| `/swapfile` | 2GB swap for OOM prevention |

---

## Verification

### Gateway Status
```
[gateway] listening on ws://100.101.182.58:18789 (PID 42693)
[gateway] agent model: anthropic/claude-opus-4-5
[browser/service] Browser control service ready (profiles=2)
```

### Dashboard Access
- URL: `http://100.101.182.58:18789/?token=devtoken`
- Status: **CONNECTED** from iPhone via Tailscale

---

## Security Notes

1. **Gateway bound to Tailscale only** - Not accessible from public internet
2. **Token auth enabled** - Requires `devtoken` to connect
3. **ANTHROPIC_API_KEY on EC2** - Should be rotated after testing
4. **AWS credentials used during session** - User should rotate after testing
5. **allowInsecureAuth=true** - Allows HTTP token auth (Tailscale provides network security)

---

## Post-Completion Checklist

- [x] OpenClaw installed and running
- [x] Tailscale installed and authenticated
- [x] Gateway accessible from phone
- [x] Dashboard connected successfully
- [ ] Rotate AWS credentials
- [ ] Rotate Anthropic API key (optional)
- [ ] Set up systemd service for gateway persistence

---

## Commands Reference

### Start Gateway
```bash
export NODE_OPTIONS="--max-old-space-size=1024"
export ANTHROPIC_API_KEY=<your-key>
nohup openclaw gateway --port 18789 --bind tailnet --dev --allow-unconfigured --token devtoken > /tmp/openclaw-gateway.log 2>&1 &
```

### Stop Gateway
```bash
pkill -f "openclaw gateway"
# or
openclaw gateway stop
```

### Check Gateway Status
```bash
cat /tmp/openclaw-gateway.log
pgrep -a openclaw
```

### Restart with Config Reload
```bash
pkill -USR1 -f openclaw-gateway
```

### Tailscale Serve Status
```bash
tailscale serve status
```

---

## Receipt

```json
{
  "ticket": "S2-01",
  "status": "COMPLETE",
  "instance_id": "i-0dd3b26129b0681ce",
  "region": "us-east-2",
  "tailscale_ip": "100.101.182.58",
  "openclaw_version": "2026.2.2-3",
  "gateway_url": "ws://100.101.182.58:18789",
  "gateway_token": "devtoken",
  "dashboard_verified": true,
  "mobile_access_verified": true,
  "timestamp": "2026-02-04T20:50:00Z"
}
```
