# Claude Code VPS Setup — OpenBot + DNA Matrix

## Overview

This document describes how to configure Claude Code to control a VPS running
the OpenBot automation platform, DNA Matrix, and the OpenClaw gateway.

## Services Running on VPS

| Service        | Port  | Description                              |
|----------------|-------|------------------------------------------|
| DNA Matrix     | 8000  | Sports parlay risk evaluation engine     |
| OpenClaw       | 18789 | Gateway for agent coordination           |
| OpenBot        | —     | Automation runtime (CLI, no port)        |

## Prerequisites

- Claude Code installed locally (`npm install -g @anthropic-ai/claude-code`)
- SSH access to the VPS (key-based authentication)
- VPS running Ubuntu 20.04+ with OpenBot installed via `clawedbot-install.sh`

## Quick Start

### 1. Create the Claude Code Project Config

Copy the template to your local machine:

```bash
mkdir -p ~/.claude/projects
cp vps-setup/dna-vps.json ~/.claude/projects/dna-vps.json
```

Edit `~/.claude/projects/dna-vps.json` and replace:
- `YOUR_VPS_IP` with your VPS IP address or hostname
- `YOUR_SSH_USER` with your SSH username
- `YOUR_SSH_KEY_PATH` with the path to your SSH private key

### 2. Launch Claude Code with VPS Project

```bash
claude --project dna-vps
```

### 3. What Claude Code Gets Access To

Once connected, Claude Code has full access to:

- **DNA Matrix** — running on port 8000, health endpoint at `/health`
- **OpenClaw gateway** — running on port 18789
- **OpenBot CLI** — `openbot doctor`, `openbot run`, `openbot ssm`
- **Git repo** — `/opt/openbot` with all checkpoints and receipts
- **Logs & Receipts** — `/var/lib/openbot/{logs,receipts}`

## VPS Directory Layout

```
/opt/openbot/                  # OpenBot source repo
/var/lib/openbot/
  ├── venv/                    # Python virtual environment
  ├── logs/                    # Run logs
  ├── receipts/                # Receipt JSON artifacts
  └── workdir/                 # Disposable clone targets
/etc/openbot/
  ├── config.yaml              # Active runtime config
  └── credentials.yaml         # Git credentials (if needed)
/usr/local/bin/openbot         # CLI wrapper
/usr/local/bin/openbot-run     # Config-driven runner
```

## Bootstrap a Fresh VPS

Use the bootstrap script to prepare a new VPS:

```bash
# From your local machine, copy and run:
scp vps-setup/bootstrap-vps.sh user@YOUR_VPS_IP:/tmp/
ssh user@YOUR_VPS_IP 'sudo bash /tmp/bootstrap-vps.sh'
```

Or run the bootstrap directly via Claude Code after connecting.

## Verifying the Setup

After bootstrap, verify everything is running:

```bash
# Check OpenBot health
openbot doctor

# Check DNA Matrix
curl -s http://localhost:8000/health | python3 -m json.tool

# Check OpenClaw gateway
curl -s http://localhost:18789/status

# Check recent receipts
ls -lt /var/lib/openbot/receipts/ | head -5
```

## Security Notes

- VPS access uses SSH key authentication only (no passwords)
- OpenBot runs as unprivileged `openbot` user
- DNA Matrix core engine (`dna-matrix/core/`) is FROZEN — never modify
- All runs produce audit receipts in `/var/lib/openbot/receipts/`
- Protected paths enforced via `policies/protected_paths.yaml`
