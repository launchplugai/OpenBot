# Guideline: CLI Worker Fleet — Setup, Diagnosis & Recovery

> **Status**: SOLVED
> **Date**: 2026-02-15
> **Author**: Executive Consultant
> **Applies to**: All nodes, all sessions

---

## 1. Problem Statement

The CLI worker tier (4x coding agents) was non-functional. Middle management could not delegate coding tasks. Three issues surfaced simultaneously:

| Symptom | Reported As | Actual Root Cause |
|---------|-------------|-------------------|
| Claude CLI `-p` hangs | Interactive-only assumption | Not authenticated — Anthropic credits depleted |
| Codex CLI not installed | Missing binary | Wrong tool — `codex` on system is a templating engine, not an AI agent |
| Kimi 128K returns 429 | API overloaded | Transient rate limit, resolved on retry |

---

## 2. Constitutional Context

Per the org chart, workers are **the hands of the organization**. When they go down, the entire coding pipeline stops. The executive can think, management can plan, operations can monitor — but nothing ships.

```
President → Executive → Middle Mgmt → WORKERS (broken) → nothing ships
```

Worker issues are **critical path**. Diagnose immediately, escalate if not resolved in < 10 minutes.

---

## 3. Diagnosis Procedure

Run this checklist in order. Stop at the first failure.

### 3.1 Claude CLI

```bash
# Is it installed?
which claude && claude --version

# Is it authenticated?
ANTHROPIC_API_KEY="$KEY" claude -p "respond OK"

# If "Not logged in" or 400 credit error:
curl -s https://api.anthropic.com/v1/messages \
  -H "x-api-key: $ANTHROPIC_API_KEY" \
  -H "anthropic-version: 2023-06-01" \
  -H "Content-Type: application/json" \
  -d '{"model":"claude-sonnet-4-5-20250929","max_tokens":5,"messages":[{"role":"user","content":"ping"}]}'
```

**Interpretation:**
- `200` → Credits active. CLI should work with `-p` flag.
- `400` "credit balance too low" → Credits depleted. CLI will not function. Switch to aider.
- `401` → Bad API key. Check `/etc/profile.d/ai-cli-keys.sh`.
- `404` → Wrong baseUrl. Must be `https://api.anthropic.com` (not `/v1`).

### 3.2 Aider (Fallback Worker)

```bash
# Is it installed?
which aider || /usr/local/bin/aider --version

# Test headless mode:
OPENAI_API_KEY="$KEY" aider --no-git --model openai/gpt-4o-mini \
  --message "respond OK" --yes --no-auto-commits
```

### 3.3 Kimi 128K (Middle Management)

```bash
curl -s https://api.moonshot.ai/v1/chat/completions \
  -H "Authorization: Bearer $MOONSHOT_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"model":"moonshot-v1-128k","messages":[{"role":"user","content":"ping"}],"max_tokens":5}'
```

**Note:** Use `api.moonshot.ai`, NOT `api.moonshot.cn`. The `.cn` endpoint rejects this key.

### 3.4 GPT-4o-mini (Operations)

```bash
curl -s https://api.openai.com/v1/chat/completions \
  -H "Authorization: Bearer $OPENAI_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"model":"gpt-4o-mini","messages":[{"role":"user","content":"ping"}],"max_tokens":5}'
```

---

## 4. Resolution Matrix

| Scenario | Action | Command |
|----------|--------|---------|
| Anthropic credits active | Use Claude CLI as primary worker | `claude -p "TASK" --allowedTools "Edit,Write,Bash,Read"` |
| Anthropic credits depleted | Use aider as primary worker | `aider --model openai/gpt-4o-mini --message "TASK" --yes` |
| Both Anthropic + OpenAI down | Escalate to president. No coding workers available. | — |
| Kimi 128K 429 | Transient. Retry in 30s. If persistent, use Kimi 8K or GPT-4o-mini for management. | — |
| Wrong `codex` binary | Ignore. `/usr/bin/codex` is a templating tool, not relevant. | — |

---

## 5. Worker Spawning — Correct Commands

### Primary: Claude CLI (when Anthropic credits active)

```bash
# Simple task:
cd /root/.openclaw/workspace/DNA && \
  ANTHROPIC_API_KEY="$KEY" claude -p "Fix the auth bug in login.py"

# With tool restrictions:
claude -p "TASK" --allowedTools "Edit,Write,Bash,Read,Glob,Grep"

# With specific files:
claude -p "Fix the validation in these files" --add-dir /root/.openclaw/workspace/DNA/src
```

### Fallback: Aider (when Anthropic depleted, or for cost savings)

```bash
# Single file task:
cd /root/.openclaw/workspace/DNA && \
  aider src/login.py --model openai/gpt-4o-mini --message "Fix auth bug" --yes

# Multi-file task:
aider src/login.py src/auth.py tests/test_auth.py \
  --model openai/gpt-4o-mini --message "Fix auth and add tests" --yes

# Complex task (use gpt-4o for better reasoning):
aider --model openai/gpt-4o --message "Refactor the entire auth module" --yes
```

### Worker Selection Logic (for Middle Management)

```
1. Test Anthropic API → 200? Use claude -p
2. Anthropic 400/401?  → Use aider with gpt-4o-mini
3. OpenAI also down?   → Escalate to executive. STOP.
```

---

## 6. Environment Configuration

All API keys live in two places:

### `/etc/profile.d/ai-cli-keys.sh` (system-wide, all shells)
```bash
export ANTHROPIC_API_KEY="sk-ant-..."
export OPENAI_API_KEY="sk-proj-..."
```

### `/root/.bashrc` (root user SSM sessions)
```bash
export ANTHROPIC_API_KEY="sk-ant-..."
export OPENAI_API_KEY="sk-proj-..."
```

### `/root/.openclaw/openclaw.json` → `env` section (gateway process)
```json
{
  "env": {
    "ANTHROPIC_API_KEY": "sk-ant-...",
    "MOONSHOT_API_KEY": "sk-...",
    "OPENAI_API_KEY": "sk-proj-..."
  }
}
```

**Rule:** Keys go in all three places. If a key is missing from one, workers spawned from that context will fail silently.

---

## 7. Chain of Command — Immutable

This is constitutional law. No profile switch, no config change, no emergency overrides this.

```
PRESIDENT (Human)
  ↓
EXECUTIVE: moonshot/kimi-k2.5          ← ALWAYS primary. No exceptions.
  ↓
MIDDLE MGMT: moonshot/moonshot-v1-128k ← Task masters. Drive workers.
  ↓
WORKERS: claude -p / aider             ← Coding. Testing. Git.
  ↓
OPERATIONS: openai/gpt-4o-mini         ← Heartbeat. Config. Metrics.
```

**Profiles control fallback chains, NOT the executive role:**
- `backup`: Kimi 2.5 → GPT-4o-mini (no Anthropic spend)
- `normal`: Kimi 2.5 → Claude Sonnet → GPT-4o-mini (full stack)

**Violation:** Promoting Claude to primary (executive) breaks the constitutional hierarchy. The `normal` profile was rebuilt to prevent this. If a profile puts anything other than `moonshot/kimi-k2.5` as primary, it is non-compliant and must be corrected immediately.

---

## 8. Prevention

1. **Never assume a CLI tool is what its name suggests.** Verify with `--help` before trusting it.
2. **Test API keys before declaring a worker ready.** A 200 from the API is the only proof.
3. **Keep aider installed as permanent fallback.** Anthropic credits will deplete again. When they do, the coding pipeline must not stop.
4. **Profile switches must preserve the chain of command.** No model promotion above its constitutional tier.
5. **Log worker availability in the daily note.** Future sessions inherit this context.

---

## 9. Installed Tools Reference

| Tool | Path | Version | Purpose |
|------|------|---------|---------|
| Claude CLI | `/usr/bin/claude` | 2.1.37 | Primary coding worker (Anthropic) |
| Aider | `/usr/local/bin/aider` | 0.86.2 | Fallback coding worker (OpenAI) |
| Node.js | `/usr/bin/node` | 22.22.0 | Gateway runtime |
| Python | `/usr/bin/python3` | 3.12.3 | Scripts and automation |
| Git | `/usr/bin/git` | (system) | Version control |

---

*This guideline is a constitutional artifact. Follow it. Reference it. Update it when reality changes.*
