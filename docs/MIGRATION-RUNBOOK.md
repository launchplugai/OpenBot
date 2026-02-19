# OpenBot/OpenClaw EC2 Migration Runbook

> **Operational playbook for sanitizing the old EC2 and bootstrapping a fresh instance.**
> Every command is copy-paste ready. Every step has a verification gate.
> If a step fails, the rollback path is immediately below it.

---

## Table of Contents

1. [Pre-Migration Audit](#1-pre-migration-audit)
2. [Export Consciousness from Old EC2](#2-export-consciousness-from-old-ec2)
3. [Extract Tarball via S3](#3-extract-tarball-via-s3)
4. [Provision New EC2](#4-provision-new-ec2)
5. [Bootstrap New EC2](#5-bootstrap-new-ec2)
6. [Restore from Transplant](#6-restore-from-transplant)
7. [Credential Injection](#7-credential-injection)
8. [Gateway Startup and Config Validation](#8-gateway-startup-and-config-validation)
9. [Enable Capabilities](#9-enable-capabilities)
10. [OpenBot Runtime Setup](#10-openbot-runtime-setup)
11. [Tailscale Networking](#11-tailscale-networking)
12. [Fixit-Bot Heartbeat](#12-fixit-bot-heartbeat)
13. [End-to-End Smoke Tests](#13-end-to-end-smoke-tests)
14. [Cutover: Old → New](#14-cutover-old--new)
15. [Post-Cutover Cleanup](#15-post-cutover-cleanup)
16. [Rollback: New → Old](#16-rollback-new--old)
17. [Reference: Full File Map](#17-reference-full-file-map)
18. [Reference: Credential Matrix](#18-reference-credential-matrix)
19. [Reference: Known Gotchas](#19-reference-known-gotchas)

---

## 1. Pre-Migration Audit

**Goal:** Confirm the old EC2 is in a known good state before we touch anything.

### 1.1 Connect to Old EC2

```bash
aws ssm start-session --target i-0dd3b26129b0681ce --region us-east-2
```

### 1.2 Gateway Health Check

```bash
systemctl is-active openclaw-gateway
ss -tlnp | grep 18789
curl -s --connect-timeout 10 http://localhost:18789/ | head -5
```

**Expected:** `active`, port 18789 LISTENING, health endpoint responds.

### 1.3 Memory Integrity

```bash
ls -la /root/.openclaw/memory/
cat /root/.openclaw/memory/MEMORY.md | head -5
python3 -c "import json; d=json.load(open('/root/.openclaw/memory/lessons.json')); print(f'{len(d)} lessons')"
python3 -c "import json; d=json.load(open('/root/.openclaw/memory/taskboard.json')); print(f'pending={len(d[\"pending\"])}, done={len(d[\"done\"])}')"
ls /root/.openclaw/memory/daily/ | tail -5
```

**Record the output.** This is what you're preserving.

### 1.4 Config Integrity

```bash
python3 -c "import json; json.load(open('/root/.openclaw/openclaw.json')); print('openclaw.json: valid')"
python3 -c "import json; json.load(open('/root/.openclaw/agents/main/agent/models.json')); print('models.json: valid')"
python3 -c "import json; json.load(open('/root/.openclaw/agents/main/agent/auth-profiles.json')); print('auth-profiles.json: valid')"
cat /root/.openclaw/agents/main/agent/system.md | wc -l
```

**All must be valid JSON / non-empty.**

### 1.5 Resource Baseline

```bash
free -m
df -h /root /tmp
openclaw --version
node --version
ls /tmp/openclaw/sessions/ 2>/dev/null | wc -l
```

**Record:** RAM, disk, OpenClaw version, Node version, session count.

### 1.6 Tailscale State

```bash
tailscale status
tailscale ip -4
```

**Record:** Tailscale IP (100.x.x.x) and connected peers.

### 1.7 OpenBot State

```bash
/usr/local/bin/openbot doctor 2>&1 | python3 -m json.tool
ls -t /var/lib/openbot/receipts/*.json 2>/dev/null | head -3
```

**Record:** Doctor status, latest receipts.

### 1.8 Pull Latest Scripts

The migration scripts must be on the old EC2 before export.

```bash
cd /opt/openbot
git fetch origin claude/fix-openclaw-diagnostics-skxvK
git checkout claude/fix-openclaw-diagnostics-skxvK
git pull origin claude/fix-openclaw-diagnostics-skxvK
ls -la scripts/export-consciousness.sh scripts/bootstrap-new-ec2.sh
```

**Verify:** Both scripts exist and are executable (`-rwxr-xr-x`).

---

## 2. Export Consciousness from Old EC2

### 2.1 Dry Run First

```bash
bash /opt/openbot/scripts/export-consciousness.sh --dry-run
```

**Check:** All critical files show `FOUND`. Note any `MISS` items.

### 2.2 Full Export

```bash
bash /opt/openbot/scripts/export-consciousness.sh
```

**Output:** `/tmp/openclaw-transplant-YYYYMMDD-HHMMSS.tar.gz`

### 2.3 Verify Tarball Contents

```bash
TARBALL=$(ls -t /tmp/openclaw-transplant-*.tar.gz | head -1)
echo "Tarball: $TARBALL"
echo "Size: $(du -h "$TARBALL" | cut -f1)"
echo ""
echo "--- Contents ---"
tar tzf "$TARBALL" | head -40
echo ""
echo "--- Manifest ---"
tar xzf "$TARBALL" -O ./manifest.json 2>/dev/null | python3 -m json.tool
```

**Verify checklist:**

| Item | Must be present |
|------|----------------|
| `memory/MEMORY.md` | Yes |
| `memory/lessons.json` | Yes |
| `memory/current-work.json` | Yes |
| `memory/taskboard.json` | Yes |
| `memory/decisions.md` | Yes |
| `memory/daily/*.md` | Yes (at least recent ones) |
| `agents/models.json` | Yes |
| `agents/auth-profiles.json` | Yes (scrubbed) |
| `agents/system.md` | Yes |
| `openclaw.json` | Yes (scrubbed) |
| `manifest.json` | Yes |

### 2.4 Verify Secrets Are Scrubbed

```bash
tar xzf "$TARBALL" -O ./openclaw.json 2>/dev/null | grep -i "CHANGE_ME"
tar xzf "$TARBALL" -O ./agents/auth-profiles.json 2>/dev/null | grep -i "CHANGE_ME"
```

**Must show CHANGE_ME placeholders, NOT real keys.**

If you see actual API keys: **STOP.** Re-run the export — the scrubber may have failed. Manually check the Python scrub logic in `export-consciousness.sh`.

---

## 3. Extract Tarball via S3

### 3.1 Upload from Old EC2

```bash
TARBALL=$(ls -t /tmp/openclaw-transplant-*.tar.gz | head -1)
S3_BUCKET="YOUR-BUCKET-NAME"
S3_PATH="s3://${S3_BUCKET}/migration/$(basename $TARBALL)"

aws s3 cp "$TARBALL" "$S3_PATH" --region us-east-2
echo "Uploaded to: $S3_PATH"
```

### 3.2 Verify Upload

```bash
aws s3 ls "s3://${S3_BUCKET}/migration/" --region us-east-2
```

**Verify:** File exists, size matches local tarball.

### 3.3 Alternative: Direct SCP via Tailscale

If both instances are on the same Tailscale network and the new box is already provisioned:

```bash
# From old EC2 (if scp is available):
scp "$TARBALL" root@100.x.x.x:/tmp/
```

### 3.4 Alternative: Base64 via SSM (small tarballs only, <256KB)

```bash
# On old EC2:
base64 "$TARBALL" > /tmp/transplant.b64

# Then retrieve via SSM get-command-invocation output
# Only viable for very small exports
```

---

## 4. Provision New EC2

### 4.1 Instance Requirements

| Setting | Value | Notes |
|---------|-------|-------|
| AMI | Ubuntu 22.04 LTS (amd64) | Or Amazon Linux 2023 |
| Instance type | t3.medium (minimum) | 4GB RAM, 2 vCPU |
| Root volume | 30GB gp3 | 20GB minimum, 30GB comfortable |
| Region | us-east-2 (Ohio) | Match existing infra |
| VPC/Subnet | Same as old instance | For Tailscale peering |
| Security Group | Outbound HTTPS (443) only | No inbound. No SSH. |
| IAM Role | Instance profile with `AmazonSSMManagedInstanceCore` | Required for SSM access |
| Key Pair | None | SSM only, no SSH |
| User data | See 4.2 | Bootstrap SSM agent |

### 4.2 User Data Script (Launch Config)

```bash
#!/bin/bash
# Ensure SSM agent is running
yum install -y amazon-ssm-agent 2>/dev/null || apt-get install -y amazon-ssm-agent 2>/dev/null
systemctl enable amazon-ssm-agent
systemctl start amazon-ssm-agent
```

### 4.3 Verify SSM Connectivity

Wait 2-3 minutes after launch, then:

```bash
aws ssm describe-instance-information \
  --filters "Key=InstanceIds,Values=i-NEW_INSTANCE_ID" \
  --region us-east-2 \
  --query "InstanceInformationList[0].[PingStatus,PlatformType,PlatformName]"
```

**Expected:** `["Online", "Linux", "Ubuntu"]` or similar.

### 4.4 First SSM Connection

```bash
aws ssm start-session --target i-NEW_INSTANCE_ID --region us-east-2
```

**Verify:** You get a shell prompt.

### 4.5 Record New Instance Details

```bash
# On new EC2:
echo "Instance ID: $(curl -s http://169.254.169.254/latest/meta-data/instance-id)"
echo "Private IP:  $(curl -s http://169.254.169.254/latest/meta-data/local-ipv4)"
echo "AZ:          $(curl -s http://169.254.169.254/latest/meta-data/placement/availability-zone)"
echo "RAM:         $(free -m | awk '/^Mem:/{print $2}')MB"
echo "Disk:        $(df -h / | tail -1 | awk '{print $4}') free"
echo "OS:          $(cat /etc/os-release | grep PRETTY_NAME | cut -d'"' -f2)"
```

**Save this output.** You'll reference it throughout.

---

## 5. Bootstrap New EC2

### 5.1 Clone the Repo

```bash
apt-get update -qq && apt-get install -y -qq git
git clone https://github.com/launchplugai/OpenBot.git /opt/openbot
cd /opt/openbot
git checkout claude/fix-openclaw-diagnostics-skxvK
git pull origin claude/fix-openclaw-diagnostics-skxvK
```

**Verify:**

```bash
ls /opt/openbot/scripts/bootstrap-new-ec2.sh /opt/openbot/scripts/export-consciousness.sh
```

### 5.2 Download Transplant Tarball

```bash
S3_BUCKET="YOUR-BUCKET-NAME"
aws s3 cp "s3://${S3_BUCKET}/migration/openclaw-transplant-*.tar.gz" /tmp/ --region us-east-2

# If multiple files, get the latest:
TARBALL=$(ls -t /tmp/openclaw-transplant-*.tar.gz | head -1)
echo "Using: $TARBALL"
```

### 5.3 Extract Transplant

```bash
mkdir -p /root/.openclaw-transplant
tar xzf "$TARBALL" -C /root/.openclaw-transplant
ls -la /root/.openclaw-transplant/
cat /root/.openclaw-transplant/manifest.json | python3 -m json.tool 2>/dev/null || cat /root/.openclaw-transplant/manifest.json
```

**Verify:** `manifest.json` present, `memory/` directory present, `agents/` directory present.

### 5.4 Dry Run Bootstrap

```bash
bash /opt/openbot/scripts/bootstrap-new-ec2.sh --dry-run --from-transplant /root/.openclaw-transplant
```

**Review the output.** Confirm all 8 phases are listed.

### 5.5 Full Bootstrap

```bash
bash /opt/openbot/scripts/bootstrap-new-ec2.sh \
  --yes \
  --from-transplant /root/.openclaw-transplant \
  --skip-tailscale
```

> **Note:** We skip Tailscale here because it requires an auth key. We'll do it separately in step 11.

**This takes 3-5 minutes.** It will:

1. Install Node.js 22, Python 3, git, jq, curl
2. Install OpenClaw gateway + systemd service
3. Clone and install OpenBot (clawedbot-install.sh)
4. Restore memory, agent config, gateway config from transplant
5. Harden memory system
6. Print credential checklist

### 5.6 Verify Bootstrap

```bash
echo "=== Node ==="
node --version   # Must be >= 22

echo "=== OpenClaw ==="
openclaw --version

echo "=== OpenBot ==="
/usr/local/bin/openbot doctor --local 2>&1 | head -20

echo "=== Config ==="
python3 -c "import json; json.load(open('/root/.openclaw/openclaw.json')); print('openclaw.json: valid')"
python3 -c "import json; json.load(open('/root/.openclaw/agents/main/agent/models.json')); print('models.json: valid')"

echo "=== Memory ==="
ls /root/.openclaw/memory/
cat /root/.openclaw/memory/MEMORY.md | head -5

echo "=== Pending Credentials ==="
grep -c "CHANGE_ME" /root/.openclaw/openclaw.json
grep -c "CHANGE_ME" /root/.openclaw/agents/main/agent/auth-profiles.json 2>/dev/null || echo "0"
```

**Gate:** Node >= 22, OpenClaw installed, configs valid, memory restored, CHANGE_ME count known.

---

## 6. Restore from Transplant

> If the bootstrap `--from-transplant` handled this, skip to verification.
> This section is for manual restoration or troubleshooting.

### 6.1 Memory Restoration

```bash
TRANSPLANT="/root/.openclaw-transplant"

# Core memory files
mkdir -p /root/.openclaw/memory/daily /root/.openclaw/memory/metrics/session-reports
cp -a "$TRANSPLANT"/memory/MEMORY.md /root/.openclaw/memory/
cp -a "$TRANSPLANT"/memory/lessons.json /root/.openclaw/memory/
cp -a "$TRANSPLANT"/memory/current-work.json /root/.openclaw/memory/
cp -a "$TRANSPLANT"/memory/taskboard.json /root/.openclaw/memory/
cp -a "$TRANSPLANT"/memory/decisions.md /root/.openclaw/memory/
cp -a "$TRANSPLANT"/memory/conflicts.json /root/.openclaw/memory/

# Daily notes
cp -a "$TRANSPLANT"/memory/daily/* /root/.openclaw/memory/daily/ 2>/dev/null || true

# Metrics
cp -a "$TRANSPLANT"/memory/metrics/* /root/.openclaw/memory/metrics/ 2>/dev/null || true
```

### 6.2 Verify Memory JSON Integrity

```bash
for f in current-work.json taskboard.json lessons.json conflicts.json; do
    FILE="/root/.openclaw/memory/$f"
    if python3 -c "import json; json.load(open('$FILE'))" 2>/dev/null; then
        echo "OK: $f"
    else
        echo "CORRUPT: $f — reinitializing"
        # Fallback: run harden-memory.sh to recreate templates
    fi
done
```

If any file is corrupt, run:

```bash
bash /opt/openbot/scripts/harden-memory.sh
```

### 6.3 Agent Config Restoration

```bash
mkdir -p /root/.openclaw/agents/main/agent
cp -a "$TRANSPLANT"/agents/models.json /root/.openclaw/agents/main/agent/
cp -a "$TRANSPLANT"/agents/auth-profiles.json /root/.openclaw/agents/main/agent/
cp -a "$TRANSPLANT"/agents/system.md /root/.openclaw/agents/main/agent/
```

### 6.4 Gateway Config Restoration

```bash
cp -a "$TRANSPLANT"/openclaw.json /root/.openclaw/openclaw.json
```

### 6.5 Config Profiles Restoration

```bash
mkdir -p /root/.openclaw/config-profiles
cp -a "$TRANSPLANT"/config-profiles/* /root/.openclaw/config-profiles/ 2>/dev/null || true
```

### 6.6 Set Permissions

```bash
chmod -R u+rw /root/.openclaw/memory/
chmod -R u+rw /root/.openclaw/agents/
chmod u+rw /root/.openclaw/openclaw.json
```

**Critical:** `openclaw.json` MUST be writable. The gateway writes to it during conversations. Read-only = EPERM crash.

---

## 7. Credential Injection

> **This is the manual step. No script can do this for you.**
> Gather all credentials before starting. Have them in a password manager ready.

### 7.1 Credential Checklist

| # | Credential | Where it goes | How to get it |
|---|-----------|---------------|--------------|
| 1 | `ANTHROPIC_API_KEY` | `openclaw.json` → `env` section | https://console.anthropic.com/settings/keys |
| 2 | Moonshot/Kimi API key | `auth-profiles.json` → kimi/moonshot profile `apiKey` field | https://platform.moonshot.cn/console/api-keys |
| 3 | OpenAI API key | `auth-profiles.json` → openai profile `apiKey` field | https://platform.openai.com/api-keys |
| 4 | Telegram bot token | `openclaw.json` → telegram config section | @BotFather on Telegram |
| 5 | GitHub PAT | `/etc/openbot/credentials.yaml` | https://github.com/settings/tokens (scope: `repo`) |
| 6 | Tailscale auth key | `tailscale up --authkey=...` | https://login.tailscale.com/admin/settings/keys |

### 7.2 Inject ANTHROPIC_API_KEY

```bash
python3 << 'PYEOF'
import json

config_path = '/root/.openclaw/openclaw.json'
with open(config_path) as f:
    config = json.load(f)

# Set Anthropic key in env section
config.setdefault('env', {})
config['env']['ANTHROPIC_API_KEY'] = 'sk-ant-PASTE_YOUR_KEY_HERE'

with open(config_path, 'w') as f:
    json.dump(config, f, indent=2, ensure_ascii=False)
    f.write('\n')

print('ANTHROPIC_API_KEY set in openclaw.json env section')
PYEOF
```

**Replace `sk-ant-PASTE_YOUR_KEY_HERE` with the real key.**

**Verify:** Key is ONLY in `openclaw.json`, not in shell env:

```bash
echo "In config: $(python3 -c "import json; c=json.load(open('/root/.openclaw/openclaw.json')); k=c.get('env',{}).get('ANTHROPIC_API_KEY',''); print(f'{k[:8]}...' if k else 'NOT SET')")"
echo "In shell:  ${ANTHROPIC_API_KEY:-not set (correct)}"
```

### 7.3 Inject Moonshot/Kimi API Key

```bash
python3 << 'PYEOF'
import json

auth_path = '/root/.openclaw/agents/main/agent/auth-profiles.json'
with open(auth_path) as f:
    auth = json.load(f)

# Find and update the moonshot/kimi profile
# The structure varies — inspect first:
print("Current structure:")
print(json.dumps(auth, indent=2)[:500])
print("...")
print("\nUpdate the appropriate apiKey field with your Moonshot key.")
print("Then re-run this with the actual key.")
PYEOF
```

> **Important:** The auth-profiles.json structure varies per OpenClaw version.
> Inspect the output above, find the moonshot/kimi entry, and set its `apiKey` field.

Example for a typical structure:

```bash
python3 << 'PYEOF'
import json

auth_path = '/root/.openclaw/agents/main/agent/auth-profiles.json'
with open(auth_path) as f:
    auth = json.load(f)

# Walk the structure and find CHANGE_ME values
def fill_keys(obj, path=''):
    if isinstance(obj, dict):
        for k, v in obj.items():
            if v == 'CHANGE_ME':
                print(f"  NEEDS KEY: {path}.{k}")
            else:
                fill_keys(v, f'{path}.{k}')
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            fill_keys(v, f'{path}[{i}]')

fill_keys(auth)
PYEOF
```

Then set each one:

```bash
# Replace CHANGE_ME values with actual keys using sed or python
python3 -c "
import json
p = '/root/.openclaw/agents/main/agent/auth-profiles.json'
with open(p) as f: d = json.load(f)
s = json.dumps(d)
# Replace one at a time — inspect between each
# s = s.replace('CHANGE_ME', 'YOUR_MOONSHOT_KEY', 1)  # First occurrence
# with open(p, 'w') as f: f.write(s)
print(f'CHANGE_ME count: {s.count(\"CHANGE_ME\")}')
"
```

### 7.4 Inject Telegram Bot Token

```bash
python3 << 'PYEOF'
import json

config_path = '/root/.openclaw/openclaw.json'
with open(config_path) as f:
    config = json.load(f)

# Find the telegram section — varies by OpenClaw config structure
# Common locations: config.telegram.botToken, config.integrations.telegram.token
print("Searching for telegram config...")
s = json.dumps(config, indent=2)
for line in s.split('\n'):
    if 'telegram' in line.lower() or 'bot' in line.lower() and 'token' in line.lower():
        print(f"  {line.strip()}")

print("\nSet the bot token in the appropriate field.")
PYEOF
```

### 7.5 Inject GitHub PAT

```bash
mkdir -p /etc/openbot
cat > /etc/openbot/credentials.yaml << 'EOF'
github_token: "ghp_PASTE_YOUR_TOKEN_HERE"
EOF
chown root:openbot /etc/openbot/credentials.yaml 2>/dev/null || chown root:root /etc/openbot/credentials.yaml
chmod 640 /etc/openbot/credentials.yaml
echo "GitHub PAT written to /etc/openbot/credentials.yaml"
```

### 7.6 Final Credential Verification

```bash
echo "=== Credential Status ==="

# Anthropic
ANTH=$(python3 -c "import json; c=json.load(open('/root/.openclaw/openclaw.json')); k=c.get('env',{}).get('ANTHROPIC_API_KEY',''); print('SET' if k and k != 'CHANGE_ME' else 'MISSING')" 2>/dev/null)
echo "Anthropic:  $ANTH"

# Auth profiles CHANGE_ME count
AUTH_CM=$(grep -c "CHANGE_ME" /root/.openclaw/agents/main/agent/auth-profiles.json 2>/dev/null || echo "0")
echo "Auth keys:  $AUTH_CM remaining CHANGE_ME values"

# Gateway config CHANGE_ME count
GW_CM=$(grep -c "CHANGE_ME" /root/.openclaw/openclaw.json 2>/dev/null || echo "0")
echo "Gateway:    $GW_CM remaining CHANGE_ME values"

# GitHub PAT
if [ -f /etc/openbot/credentials.yaml ]; then
    GH=$(grep -c "ghp_" /etc/openbot/credentials.yaml 2>/dev/null || echo "0")
    echo "GitHub PAT: $([ "$GH" -gt 0 ] && echo 'SET' || echo 'MISSING')"
else
    echo "GitHub PAT: FILE MISSING"
fi

# Shell env leak check
echo "Shell env:  ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY:+LEAKED (BAD)}"
echo "Shell env:  ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY:-not set (correct)}"
```

**Gate:** All credentials SET, zero CHANGE_ME remaining, no shell env leak.

---

## 8. Gateway Startup and Config Validation

### 8.1 Clear Any Stale Sessions

```bash
rm -rf /tmp/openclaw/sessions/* 2>/dev/null
mkdir -p /tmp/openclaw/sessions
```

### 8.2 Validate Config Files

```bash
echo "--- JSON Validation ---"
for f in /root/.openclaw/openclaw.json \
         /root/.openclaw/agents/main/agent/models.json \
         /root/.openclaw/agents/main/agent/auth-profiles.json; do
    if [ -f "$f" ]; then
        if python3 -c "import json; json.load(open('$f'))" 2>/dev/null; then
            echo "VALID: $f"
        else
            echo "INVALID: $f  <--- FIX THIS BEFORE STARTING"
        fi
    else
        echo "MISSING: $f"
    fi
done

echo ""
echo "--- Config Writable ---"
if [ -w /root/.openclaw/openclaw.json ]; then
    echo "openclaw.json: writable (good)"
else
    echo "openclaw.json: NOT WRITABLE — gateway will EPERM crash"
    echo "Fix: chmod u+w /root/.openclaw/openclaw.json"
fi
```

### 8.3 Validate Model Chain

```bash
python3 << 'PYEOF'
import json

with open('/root/.openclaw/openclaw.json') as f:
    config = json.load(f)

agents = config.get('agents', {})
defaults = agents.get('defaults', {})
model = defaults.get('model', {})
primary = model.get('primary', 'not configured')
fallbacks = model.get('fallbacks', [])

print(f"Primary model:   {primary}")
print(f"Fallback models: {fallbacks}")

env = config.get('env', {})
keys = [k for k in env.keys() if 'KEY' in k.upper()]
for k in keys:
    v = env[k]
    masked = f"{v[:8]}..." if len(v) > 8 else "***"
    print(f"API key:         {k} = {masked}")

tools = config.get('tools', {})
also_allow = tools.get('alsoAllow', [])
print(f"Allowed tools:   {also_allow}")
PYEOF
```

### 8.4 Ensure Hooks Directory Exists

```bash
mkdir -p /root/.openclaw/hooks/transforms
echo "Hooks dir: $(ls -d /root/.openclaw/hooks/transforms)"
```

This is required by the 2026.2.12 security patch.

### 8.5 Fix Anthropic Env Leak

```bash
bash /opt/openbot/scripts/fix-anthropic-env.sh
```

### 8.6 Start Gateway

```bash
systemctl daemon-reload
systemctl enable openclaw-gateway
systemctl start openclaw-gateway
echo "Gateway starting... waiting 60s for startup"
sleep 60
```

> **The 60s wait is mandatory.** OpenClaw takes ~50s to initialize. Checking earlier gives false negatives.

### 8.7 Verify Gateway

```bash
echo "=== Gateway Status ==="

# Service
if systemctl is-active openclaw-gateway &>/dev/null; then
    echo "Service:     ACTIVE"
else
    echo "Service:     FAILED"
    echo "--- Last 30 log lines ---"
    journalctl -u openclaw-gateway --no-pager -n 30
    echo ""
    echo "FIX: Check logs above. Common causes:"
    echo "  - Invalid JSON in openclaw.json"
    echo "  - Missing API key"
    echo "  - Port 18789 already in use"
    echo "  - Node.js version < 22"
    exit 1
fi

# Port
if ss -tlnp | grep -q 18789; then
    echo "Port 18789:  LISTENING"
else
    echo "Port 18789:  NOT LISTENING (may need 30s more)"
fi

# Health
HEALTH=$(curl -s --connect-timeout 10 http://localhost:18789/ 2>&1 | head -5)
if [ -n "$HEALTH" ]; then
    echo "Health:      RESPONDING"
else
    echo "Health:      NOT RESPONDING"
fi

# Memory after startup
echo "RAM used:    $(free -m | awk '/^Mem:/{print $3}')MB / $(free -m | awk '/^Mem:/{print $2}')MB"
```

**Gate:** Service ACTIVE, port LISTENING, health RESPONDING.

### 8.8 Run Full Diagnostics

```bash
bash /opt/openbot/scripts/fix-openclaw-gateway.sh --diagnose
```

Review every section. Fix any issues before proceeding.

---

## 9. Enable Capabilities

### 9.1 Web Search (Phase 1)

```bash
bash /opt/openbot/scripts/enable-web-search.sh
```

**Verify:**

```bash
python3 -c "
import json
with open('/root/.openclaw/openclaw.json') as f:
    c = json.load(f)
ws = c.get('tools',{}).get('web',{}).get('search',{}).get('enabled', False)
wf = c.get('tools',{}).get('web',{}).get('fetch',{}).get('enabled', False)
also = c.get('tools',{}).get('alsoAllow', [])
print(f'web_search: {ws}')
print(f'web_fetch: {wf}')
print(f'alsoAllow: {also}')
"
```

**Expected:** `web_search: True`, `web_fetch: True`, `alsoAllow` includes `web_search` and `web_fetch`.

### 9.2 Browser (Phase 2 — Optional)

**Option A: Sandbox (requires Docker)**

```bash
# Install Docker first if not present:
curl -fsSL https://get.docker.com | sh

# Then enable browser:
bash /opt/openbot/scripts/enable-browser.sh --sandbox
```

**Option B: BYOC (requires Kimi Claw membership)**

```bash
bash /opt/openbot/scripts/enable-browser.sh --byoc
```

**Verify:**

```bash
bash /opt/openbot/scripts/enable-browser.sh --status
```

### 9.3 Verify All Capabilities

```bash
python3 << 'PYEOF'
import json

with open('/root/.openclaw/openclaw.json') as f:
    c = json.load(f)

also = c.get('tools', {}).get('alsoAllow', [])
ws = c.get('tools', {}).get('web', {}).get('search', {}).get('enabled', False)
wf = c.get('tools', {}).get('web', {}).get('fetch', {}).get('enabled', False)
be = c.get('browser', {}).get('enabled', False)
bp = c.get('browser', {}).get('defaultProfile', 'none')

print("Capabilities:")
print(f"  Web search:     {'ON' if ws else 'OFF'}")
print(f"  Web fetch:      {'ON' if wf else 'OFF'}")
print(f"  Browser:        {'ON' if be else 'OFF'} (profile: {bp})")
print(f"  Tools allowed:  {also}")
PYEOF
```

---

## 10. OpenBot Runtime Setup

### 10.1 Verify Installation

```bash
# Wrapper exists and points to correct venv
cat /usr/local/bin/openbot
# Should show: exec /var/lib/openbot/venv/bin/python -m openbot.cli "$@"

# Venv works
/var/lib/openbot/venv/bin/python -c "import openbot; print('openbot package: OK')"

# Doctor check
/usr/local/bin/openbot doctor --local 2>&1 | python3 -m json.tool
```

### 10.2 Configure OpenBot for DNA Sherlock

```bash
cat > /etc/openbot/config.yaml << 'EOF'
target_repo: "https://github.com/launchplugai/DNA"
target_branch: "main"
setup_command: "pip install -r requirements.txt && pip install -e ./dna-matrix"
command: "pytest app/tests -v"
EOF

chown root:openbot /etc/openbot/config.yaml 2>/dev/null || true
chmod 640 /etc/openbot/config.yaml
echo "Config written to /etc/openbot/config.yaml"
```

### 10.3 Verify Systemd Services

```bash
ls -la /etc/systemd/system/openbot*.service
systemctl daemon-reload
systemctl is-enabled openbot.service 2>/dev/null || echo "openbot.service: not enabled (OK for Phase 1)"
systemctl is-enabled openbot-run.service 2>/dev/null || echo "openbot-run.service: not enabled (OK for Phase 1)"
```

### 10.4 Directory Permissions

```bash
ls -la /var/lib/openbot/
ls -la /etc/openbot/
id openbot 2>/dev/null || echo "openbot user: does not exist (clawedbot-install creates it)"
```

---

## 11. Tailscale Networking

### 11.1 Install Tailscale

```bash
curl -fsSL https://tailscale.com/install.sh | sh
```

### 11.2 Join Tailnet

> Generate a one-time auth key at https://login.tailscale.com/admin/settings/keys

```bash
tailscale up --authkey=tskey-auth-PASTE_YOUR_KEY_HERE
```

### 11.3 Verify Tailscale

```bash
tailscale status
TS_IP=$(tailscale ip -4)
echo "Tailscale IP: $TS_IP"
```

**Record the new Tailscale IP.** The old instance was `100.101.182.58`. The new one will be different.

### 11.4 Update DNS/References

If any config references the old Tailscale IP (`100.101.182.58`), update it:

```bash
grep -r "100.101.182.58" /root/.openclaw/ 2>/dev/null
# If found, replace with new IP
```

---

## 12. Fixit-Bot Heartbeat

### 12.1 Install Fixit Cron

```bash
# Check if fixit CLI exists
which fixit 2>/dev/null || echo "fixit not installed — install separately"

# If fixit is available:
mkdir -p /root/.fixit
# Create heartbeat config (adjust as needed):
cat > /root/.fixit/heartbeat-config.json << 'EOF'
{
  "interval": "15m",
  "plugins": ["openbot"],
  "notify": true
}
EOF

# Install cron job
(crontab -l 2>/dev/null; echo "*/15 * * * * /opt/openbot/fixit-bot/deploy/fixit-cron.sh >> /var/log/fixit.log 2>&1") | crontab -
echo "Fixit cron installed. Verify:"
crontab -l | grep fixit
```

### 12.2 Test Heartbeat

```bash
bash /opt/openbot/fixit-bot/deploy/fixit-cron.sh
echo "Exit code: $?"
```

---

## 13. End-to-End Smoke Tests

### 13.1 Gateway Responds to API Call

```bash
curl -s --connect-timeout 10 http://localhost:18789/ | head -10
echo ""
echo "Status: $([ $? -eq 0 ] && echo 'PASS' || echo 'FAIL')"
```

### 13.2 Memory System Intact

```bash
echo "=== Memory Smoke Test ==="
for f in MEMORY.md lessons.json current-work.json taskboard.json decisions.md; do
    FILE="/root/.openclaw/memory/$f"
    if [ -f "$FILE" ]; then
        SIZE=$(wc -c < "$FILE")
        echo "  $f: ${SIZE} bytes"
    else
        echo "  $f: MISSING"
    fi
done
DAILY_COUNT=$(ls /root/.openclaw/memory/daily/ 2>/dev/null | wc -l)
echo "  daily notes: $DAILY_COUNT"
```

### 13.3 OpenBot Doctor

```bash
/usr/local/bin/openbot doctor 2>&1 | python3 -c "
import json, sys
try:
    report = json.load(sys.stdin)
    status = report.get('overall_status', 'UNKNOWN')
    print(f'OpenBot doctor: {status}')
    if status != 'HEALTHY':
        print(json.dumps(report, indent=2))
except:
    print('OpenBot doctor: could not parse output')
"
```

### 13.4 Model Chain Connectivity

> This test verifies the gateway can reach each API provider.

```bash
# Check Kimi/Moonshot API
curl -s --connect-timeout 10 https://api.moonshot.cn/v1/models \
  -H "Authorization: Bearer $(python3 -c "import json; c=json.load(open('/root/.openclaw/agents/main/agent/auth-profiles.json')); print('test')" 2>/dev/null)" \
  | head -5
echo "Moonshot API: $([ $? -eq 0 ] && echo 'reachable' || echo 'UNREACHABLE')"

# Check OpenAI API
curl -s --connect-timeout 10 https://api.openai.com/v1/models \
  | head -5
echo "OpenAI API: $([ $? -eq 0 ] && echo 'reachable' || echo 'UNREACHABLE')"

# Check Anthropic API
curl -s --connect-timeout 10 https://api.anthropic.com/v1/messages \
  -H "x-api-key: test" -H "anthropic-version: 2023-06-01" \
  | head -5
echo "Anthropic API: $([ $? -eq 0 ] && echo 'reachable' || echo 'UNREACHABLE')"
```

### 13.5 Telegram Bot Test

> This is manual. Send a test message to `@MarvinAI_open_bot` on Telegram.

1. Open Telegram
2. Message `@MarvinAI_open_bot`: "health check"
3. Wait up to 90 seconds for response
4. If no response: check `journalctl -u openclaw-gateway --no-pager -n 50`

### 13.6 Full Diagnostics Script

```bash
bash /opt/openbot/scripts/fix-openclaw-gateway.sh --diagnose
```

**Gate:** All sections show healthy. No CRITICAL or FATAL errors.

---

## 14. Cutover: Old → New

> **Only proceed after all smoke tests pass on the new EC2.**

### 14.1 Stop Old Gateway

On the **old** EC2:

```bash
systemctl stop openclaw-gateway
systemctl disable openclaw-gateway
echo "Old gateway stopped and disabled."
```

### 14.2 Verify New Gateway Takes Over

On the **new** EC2:

```bash
systemctl is-active openclaw-gateway
ss -tlnp | grep 18789
```

### 14.3 Update Tailscale DNS (if applicable)

If your Telegram webhook or any external reference points to the old Tailscale IP:

- Old: `100.101.182.58`
- New: `$(tailscale ip -4)` on new EC2

Update any webhook URLs, DNS records, or config that reference the old IP.

### 14.4 Final Telegram Test

Send another message to `@MarvinAI_open_bot`. Confirm it responds from the new instance.

### 14.5 Update ONBOARDING.md

Update the instance ID and Tailscale IP in the onboarding doc:

```bash
# On new EC2:
NEW_ID=$(curl -s http://169.254.169.254/latest/meta-data/instance-id)
NEW_TS_IP=$(tailscale ip -4)
echo "New instance: $NEW_ID"
echo "New Tailscale: $NEW_TS_IP"
echo ""
echo "Update docs/openclaw/ONBOARDING.md:"
echo "  EC2 Instance: $NEW_ID"
echo "  Tailscale IP: $NEW_TS_IP"
```

---

## 15. Post-Cutover Cleanup

### 15.1 On New EC2

```bash
# Create today's daily note
bash /opt/openbot/scripts/harden-memory.sh

# Verify no stale sessions
ls /tmp/openclaw/sessions/ 2>/dev/null | wc -l

# Check resource usage
free -m
df -h /root /tmp
```

### 15.2 On Old EC2

> **Do NOT terminate the old instance immediately.** Keep it for 48-72 hours as a rollback target.

```bash
# On old EC2 — just ensure gateway is stopped
systemctl is-active openclaw-gateway  # Should show "inactive"
```

### 15.3 After 72 Hours (if no issues)

```bash
# Terminate old EC2 (from your local machine)
aws ec2 terminate-instances --instance-ids i-0dd3b26129b0681ce --region us-east-2
```

---

## 16. Rollback: New → Old

> If the new EC2 has critical issues, revert to the old one.

### 16.1 Stop New Gateway

```bash
# On new EC2:
systemctl stop openclaw-gateway
```

### 16.2 Restart Old Gateway

```bash
# On old EC2 (via SSM):
systemctl enable openclaw-gateway
systemctl start openclaw-gateway
sleep 60
systemctl is-active openclaw-gateway
```

### 16.3 Revert Webhook/DNS

Point any Telegram webhooks or DNS back to the old Tailscale IP (`100.101.182.58`).

### 16.4 Investigate and Retry

Check what went wrong on the new instance:

```bash
journalctl -u openclaw-gateway --no-pager -n 100
bash /opt/openbot/scripts/fix-openclaw-gateway.sh --diagnose
```

Fix the issue, then attempt cutover again from step 14.

---

## 17. Reference: Full File Map

```
/root/.openclaw/
├── openclaw.json                          # Gateway config (secrets here)
├── agents/main/agent/
│   ├── models.json                        # Model chain: primary + fallbacks
│   ├── auth-profiles.json                 # Provider API keys
│   └── system.md                          # System prompt (agent personality)
├── memory/
│   ├── MEMORY.md                          # Long-term knowledge (read first)
│   ├── lessons.json                       # Collective lessons array
│   ├── current-work.json                  # Active / completed / blocked tasks
│   ├── taskboard.json                     # pending → claimed → done queue
│   ├── decisions.md                       # Append-only architecture decisions
│   ├── conflicts.json                     # File conflict tracker
│   ├── daily/YYYY-MM-DD.md              # One per day
│   └── metrics/
│       ├── cost-tracker.json
│       ├── worker-scores.json
│       └── session-reports/
├── hooks/transforms/                      # Required by 2026.2.12 security patch
├── config-profiles/                       # Switchable backup/normal configs
│   ├── pre-websearch-backup/
│   ├── pre-browser-backup/
│   └── pre-env-fix-backup/
├── workspace/                             # Code workspaces
└── backups/                               # Upgrade rollback snapshots

/opt/openbot/                              # Git repo
├── scripts/*.sh                           # All operational scripts
├── runtime/*.yaml, *.service              # Config templates + systemd
├── openbot/*.py                           # Python package
├── policies/*.yaml, *.json                # Protected paths, escalation, schema
├── docs/                                  # Operations, security, sprints
└── fixit-bot/                             # Heartbeat daemon

/var/lib/openbot/                          # Runtime data (openbot user)
├── venv/                                  # Python virtualenv
├── logs/<run_id>.log
├── receipts/<run_id>.json
│   └── quarantine/                        # Invalid receipts
└── workdir/<run_id>/target/               # Cloned repos (cleaned after run)

/etc/openbot/
├── config.yaml                            # OpenBot run config
└── credentials.yaml                       # GitHub PAT (640, root:openbot)

/usr/local/bin/
├── openbot                                # CLI wrapper → venv python
└── openbot-run                            # Config-driven run wrapper

/tmp/openclaw/sessions/                    # Session files (clear when >40)
```

---

## 18. Reference: Credential Matrix

| Credential | Config file | JSON path | Notes |
|-----------|------------|-----------|-------|
| ANTHROPIC_API_KEY | openclaw.json | `.env.ANTHROPIC_API_KEY` | NOT in ~/.bashrc or shell env |
| Moonshot API key | auth-profiles.json | varies by profile | For Kimi K2.5 + $web_search |
| OpenAI API key | auth-profiles.json | varies by profile | For GPT-4o-mini ops |
| Telegram token | openclaw.json | telegram config section | @MarvinAI_open_bot |
| GitHub PAT | /etc/openbot/credentials.yaml | `github_token` | scope: repo, read:org |
| Tailscale key | CLI argument | `tailscale up --authkey=` | One-time use |

---

## 19. Reference: Known Gotchas

| # | Gotcha | Impact | Fix |
|---|--------|--------|-----|
| 1 | Anthropic baseUrl must be `https://api.anthropic.com` (no `/v1`) | 404 errors | SDK appends `/v1/messages` automatically |
| 2 | `openclaw.json` must be writable | EPERM crash, gateway won't start | `chmod u+w`, never `chattr +i` |
| 3 | Sessions bloat past 40 | 80K token requests, timeouts on all providers | `rm -rf /tmp/openclaw/sessions/*` + restart |
| 4 | Gateway startup takes 50s | Checking health too early gives false negatives | Always wait 60s after `systemctl start` |
| 5 | ANTHROPIC_API_KEY in shell env | Silent Anthropic auto-discovery, burns credits | Run `fix-anthropic-env.sh` |
| 6 | SSM heredocs break | Multi-line scripts fail via SSM | Base64-encode Python scripts |
| 7 | t3.medium = 4GB RAM | Gateway uses 400-1000MB, browser sidecar adds 500MB-1GB | Monitor with `free -m`, use BYOC for browser |
| 8 | Gateway rewrites openclaw.json | Config changes during conversation trigger restarts | Accept ~50s downtime, config profiles recover |
| 9 | Anthropic credits deplete | 400 "credit balance too low" | Switch to backup profile (Kimi-only) |
| 10 | Node.js must be >= 22 | OpenClaw won't start | `curl -fsSL https://deb.nodesource.com/setup_22.x \| bash -` |

---

*End of runbook. Last updated: 2026-02-19.*
