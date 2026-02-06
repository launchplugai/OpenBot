# OpenClaw Infrastructure Briefing

**Date:** 2026-02-06
**Purpose:** Full context for OpenClaw agent operating on EC2

---

## 1. System Architecture

```
┌──────────────────────────────────────────────────────────────────────┐
│  EC2 Instance (i-0dd3b26129b0681ce) - t3.small - us-east-2          │
│  Tailscale IP: 100.101.182.58                                        │
│                                                                      │
│  ┌─────────────────┐              ┌─────────────────────────────┐   │
│  │  OpenClaw       │───SSM/API───▶│  OpenBot                    │   │
│  │  Gateway        │              │  - Automation runtime       │   │
│  │  Port: 18789    │              │  - Test execution           │   │
│  │  (You are here) │              │  - Repo management          │   │
│  └─────────────────┘              └─────────────────────────────┘   │
│           │                                    │                     │
│           │                                    ▼                     │
│           │                       /var/lib/openbot/workdir/target/  │
│           │                              (DNA repo clone)            │
│           │                                                          │
│           ▼                                                          │
│  ┌─────────────────┐                                                │
│  │  Anthropic API  │  Model: Sonnet 4.5 (primary)                   │
│  │  OpenAI API     │  Subagents: GPT-4o mini                        │
│  └─────────────────┘                                                │
└──────────────────────────────────────────────────────────────────────┘
```

---

## 2. Repository Structure

| Repo | URL | Purpose | Deploys To |
|------|-----|---------|------------|
| **DNA** | `github.com/launchplugai/DNA` | Development & testing | Railway (staging) |
| **BetApp** | `github.com/launchplugai/BetApp` | Canonical production | Manual/verified only |
| **OpenBot** | `github.com/launchplugai/OpenBot` | Infrastructure & automation | EC2 |

### Git Workflow

```
Your Sprint Work
      │
      ▼ git push origin <branch>
┌─────────────┐     auto-deploy      ┌─────────────┐
│    DNA      │─────────────────────▶│   Railway   │
│  (dev repo) │                      │  (staging)  │
└──────┬──────┘                      └─────────────┘
       │
       │ After testing & verification
       ▼
┌─────────────┐
│   BetApp    │  ← Production releases only
│ (canonical) │
└─────────────┘
```

### Your Workdir Remote Configuration

```bash
# Location: /var/lib/openbot/workdir/target/
origin     → https://github.com/launchplugai/DNA.git        # Push here
production → https://github.com/launchplugai/BetApp.git     # Verified releases only
```

---

## 3. Credentials & Access

### GitHub
- **Token:** Stored securely (do not log or expose)
- **Location:** `/etc/openbot/credentials.yaml`
- **Access:** Read/write to all launchplugai repos

### Anthropic API
- **Key:** Configured in systemd service
- **Model:** `claude-sonnet-4-5` (primary), `claude-opus-4-5` (fallback)
- **Org:** LP (LaunchPlug)

### OpenAI API
- **Key:** Configured in `/root/.openclaw/agents/main/agent/auth-profiles.json`
- **Model:** `gpt-4o-mini` (subagents - cost optimization)

---

## 4. OpenBot Integration

### What is OpenBot?
OpenBot is the automation runtime that manages your workspace:

| Component | Function |
|-----------|----------|
| `openbot/cli.py` | Command-line interface |
| `openbot/bridge/` | OpenClaw integration layer |
| `openclaw/tools/openbot-ssm/` | SSM tool for remote control |

### Available Commands (via SSM)
```bash
openbot status          # Check system status
openbot run             # Execute test suite
openbot doctor          # Diagnose issues
```

### DNA Workdir Location
```
/var/lib/openbot/workdir/target/
├── app/                 # Main application
│   ├── api/            # FastAPI endpoints
│   ├── core/           # Core logic
│   ├── models/         # Data models
│   └── tests/          # Test suite
├── requirements.txt
└── ...
```

---

## 5. Model Tiering (Cost Optimization)

Configured to reduce costs from ~$26/day to ~$6/day:

| Role | Model | Cost |
|------|-------|------|
| Primary reasoning | Sonnet 4.5 | $3/$15 per M tokens |
| Complex fallback | Opus 4.5 | $15/$75 per M tokens |
| Subagents | GPT-4o mini | $0.15/$0.60 per M tokens |

---

## 6. Gateway Configuration

**Config file:** `/root/.openclaw/openclaw.json`

Key settings:
```json
{
  "gateway": {
    "controlUi": { "allowInsecureAuth": true }
  },
  "agents": {
    "defaults": {
      "maxConcurrent": 2,
      "subagents": { "maxConcurrent": 2 }
    }
  }
}
```

**Systemd service:** `/etc/systemd/system/openclaw-gateway.service`
- Auto-restarts on crash
- Binds to Tailscale interface only

---

## 7. Your Operating Rules

### DO:
- Push sprint branches to `origin` (DNA repo)
- Run `git remote -v` before any git operations
- Use feature branches: `claude/<ticket>-<description>`
- Test via Railway deployment

### DON'T:
- Push directly to `production` remote (BetApp) without approval
- Push to `main` without PR/review
- Store secrets in code

### Branch Naming
```
claude/ticket-<id>-<description>
claude/sprint-<number>-<feature>
```

---

## 8. Quick Reference Commands

```bash
# Check remotes
git remote -v

# Push sprint work
git push origin <branch-name>

# Check OpenBot status
openbot status

# View logs
tail -f /tmp/openclaw-gateway.log

# Restart gateway
systemctl restart openclaw-gateway
```

---

## 9. Support Contacts

- **Infrastructure issues:** Check OpenBot docs at `/home/user/OpenBot/docs/`
- **Gateway issues:** Run `openclaw doctor --fix`
- **Credential issues:** Check `/etc/openbot/credentials.yaml`

---

## Acknowledgment

After reading this briefing:
1. Run `git remote -v` in your workdir to verify configuration
2. Confirm you understand the DNA → BetApp workflow
3. Continue with current sprint work

```bash
cd /var/lib/openbot/workdir/target && git remote -v
```
