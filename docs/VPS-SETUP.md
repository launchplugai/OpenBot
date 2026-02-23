# VPS Setup Guide — OpenBot + DNA Matrix + OpenClaw

## Overview

This guide covers deploying the full OpenBot stack on a VPS, including:
- **OpenBot** — automation runtime (CLI)
- **DNA Matrix** — sports parlay risk evaluation engine (port 8000)
- **OpenClaw** — agent coordination gateway (port 18789)
- **Agent team** — Ralph, Ira, and Tess

## Architecture

```
┌─────────────────────────────────────────────────┐
│                     VPS                          │
│                                                  │
│  ┌──────────────┐  ┌────────────────────────┐   │
│  │   OpenBot     │  │    DNA Matrix          │   │
│  │   CLI         │  │    :8000               │   │
│  │   /usr/local/ │  │    /opt/dna-matrix     │   │
│  │   bin/openbot │  │    uvicorn app.main    │   │
│  └──────┬───────┘  └────────────────────────┘   │
│         │                                        │
│  ┌──────┴───────┐  ┌────────────────────────┐   │
│  │  Agents       │  │    OpenClaw Gateway    │   │
│  │  Ralph (run)  │  │    :18789              │   │
│  │  Ira (doctor) │  │    /data/.openclaw     │   │
│  │  Tess (audit) │  └────────────────────────┘   │
│  └──────────────┘                                │
│                                                  │
│  /var/lib/openbot/{logs,receipts,workdir}        │
│  /etc/openbot/config.yaml                        │
└─────────────────────────────────────────────────┘
         │
    SSH / SSM
         │
┌─────────────────┐
│  Claude Code     │
│  (local machine) │
│  ~/.claude/      │
│  projects/       │
│  dna-vps.json    │
└─────────────────┘
```

## Agent Roles

| Agent | Role                  | OpenBot Command   | Description                                   |
|-------|-----------------------|-------------------|-----------------------------------------------|
| Ralph | Repository Auditor    | `openbot run`     | Clones target repos, runs tests, writes proofs |
| Ira   | Infrastructure Monitor| `openbot doctor`  | Health checks, environment validation          |
| Tess  | Test Analyst          | Receipt analysis  | Parses receipts, identifies regressions        |

## Quick Start (Bootstrap)

```bash
# On your VPS (as root):
git clone https://github.com/launchplugai/OpenBot.git /opt/openbot
sudo bash /opt/openbot/vps-setup/bootstrap-vps.sh
```

The bootstrap script handles:
1. Installing system packages (git, python3, curl, jq)
2. Running the OpenBot installer (`clawedbot-install.sh --yes`)
3. Cloning and configuring DNA Matrix with systemd service
4. Setting up OpenClaw gateway config
5. Copying the DNA Sherlock config to `/etc/openbot/config.yaml`
6. Verifying all components

### Bootstrap Options

```bash
# Full install (default)
sudo bash bootstrap-vps.sh

# Skip DNA Matrix
sudo bash bootstrap-vps.sh --skip-dna

# Skip OpenClaw
sudo bash bootstrap-vps.sh --skip-openclaw
```

## Connecting Claude Code

### 1. Copy the project config

```bash
mkdir -p ~/.claude/projects
cp vps-setup/dna-vps.json ~/.claude/projects/dna-vps.json
```

### 2. Edit connection details

Open `~/.claude/projects/dna-vps.json` and set:
- `ssh.host` — your VPS IP or hostname
- `ssh.user` — your SSH username
- `ssh.key` — path to your SSH private key

### 3. Launch

```bash
claude --project dna-vps
```

## Manual Setup (Without Bootstrap)

If you prefer step-by-step setup:

### Step 1: OpenBot

```bash
git clone https://github.com/launchplugai/OpenBot.git /opt/openbot
sudo bash /opt/openbot/scripts/clawedbot-install.sh --yes
```

### Step 2: DNA Matrix

```bash
git clone https://github.com/launchplugai/DNA.git /opt/dna-matrix
python3 -m venv /opt/dna-matrix/venv
/opt/dna-matrix/venv/bin/pip install -r /opt/dna-matrix/requirements.txt
/opt/dna-matrix/venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000
```

### Step 3: OpenClaw

```bash
mkdir -p /data/.openclaw
# Configure gateway at /data/.openclaw/config.yaml
```

### Step 4: OpenBot Config

```bash
sudo cp /opt/openbot/runtime/config.dna-sherlock.yaml /etc/openbot/config.yaml
```

## Verification

```bash
# OpenBot health
openbot doctor

# DNA Matrix health
curl -s http://localhost:8000/health | jq .

# OpenClaw status
curl -s http://localhost:18789/status

# Run a test (Ralph agent)
sudo systemctl start openbot-run

# Check receipts (Tess agent territory)
ls -lt /var/lib/openbot/receipts/ | head -5
cat /var/lib/openbot/receipts/$(ls -t /var/lib/openbot/receipts/ | head -1) | jq .
```

## Ports Summary

| Port  | Service     | Protocol | Access        |
|-------|-------------|----------|---------------|
| 8000  | DNA Matrix  | HTTP     | localhost     |
| 18789 | OpenClaw    | HTTP     | localhost     |
| 22    | SSH         | TCP      | Key-auth only |

## Troubleshooting

### DNA Matrix won't start
```bash
journalctl -u dna-matrix --no-pager -n 50
# Common fix: check python dependencies
/opt/dna-matrix/venv/bin/pip install -r /opt/dna-matrix/requirements.txt
```

### OpenBot doctor reports UNHEALTHY
```bash
openbot doctor
# Check permissions
ls -la /var/lib/openbot/
sudo chown -R openbot:openbot /var/lib/openbot
```

### Receipts not being written
```bash
# Check workdir permissions
ls -la /var/lib/openbot/workdir/
# Check config
cat /etc/openbot/config.yaml
```
