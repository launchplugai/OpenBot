#!/bin/bash
# harden-memory.sh — Ensure OpenClaw memory system is persistent and structured
#
# The memory system at /root/.openclaw/memory/ is how the org retains
# context between sessions. This script:
#   1. Creates missing directories and files
#   2. Sets correct permissions
#   3. Initializes structured templates if empty
#   4. Validates existing memory files
#   5. Sets up daily rotation
#
# Run via SSM:
#   aws ssm send-command --instance-id i-0dd3b26129b0681ce \
#     --document-name AWS-RunShellScript \
#     --parameters 'commands=["bash /opt/openbot/scripts/harden-memory.sh"]' \
#     --region us-east-2

set -euo pipefail

MEMORY_DIR="/root/.openclaw/memory"
WORKSPACE_DIR="/root/.openclaw/workspace"
TODAY=$(date +%Y-%m-%d)

echo "=== OpenClaw Memory Persistence Hardening ==="
echo "Timestamp: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo ""

# ── 1. Directory structure ────────────────────────────────────────────────

echo "--- Directory Structure ---"

DIRS=(
    "$MEMORY_DIR"
    "$MEMORY_DIR/daily"
    "$MEMORY_DIR/metrics"
    "$MEMORY_DIR/metrics/session-reports"
    "$WORKSPACE_DIR"
)

for dir in "${DIRS[@]}"; do
    if [ -d "$dir" ]; then
        echo "  EXISTS: $dir"
    else
        mkdir -p "$dir"
        echo "  CREATED: $dir"
    fi
done
echo ""

# ── 2. Core memory files ─────────────────────────────────────────────────

echo "--- Core Memory Files ---"

# MEMORY.md — long-term curated knowledge (read FIRST every session)
if [ ! -f "$MEMORY_DIR/MEMORY.md" ]; then
    cat > "$MEMORY_DIR/MEMORY.md" << 'MEMEOF'
# OpenClaw Memory

> Long-term curated knowledge. Read this FIRST every session.

## System Identity
- Bot: @MarvinAI_open_bot (Telegram)
- Executive: Kimi K2.5 (coordinator, never writes code)
- Workers: Claude Code CLI Opus 4.6 (coding operators)
- Operations: GPT-4o-mini (health, metrics, config)

## Architecture
- EC2 i-0dd3b26129b0681ce, t3.medium, us-east-2
- Gateway: OpenClaw on port 18789, SSM-only access
- Repos: DNA (quarantine), OpenBot (enforcement), BetApp (production — DO NOT TOUCH)

## Key Rules
- All work goes to DNA repo (quarantine). Never touch production.
- PO approval required before any merge to production.
- Claude is a worker, not the face. Kimi is the Executive.
- ANTHROPIC_API_KEY stays in openclaw.json env, not shell env.

## Capabilities
- Web search: Kimi $web_search (server-side, zero EC2 impact)
- Browser: sandbox sidecar or BYOC to Kimi Claw (Phase 2)
- Memory: this file + daily notes + lessons + taskboard

## Lessons Learned
(Append here as lessons accumulate)
MEMEOF
    echo "  CREATED: MEMORY.md (template)"
else
    echo "  EXISTS:  MEMORY.md ($(wc -l < "$MEMORY_DIR/MEMORY.md") lines)"
fi

# current-work.json — active tasks and recent completions
if [ ! -f "$MEMORY_DIR/current-work.json" ]; then
    cat > "$MEMORY_DIR/current-work.json" << 'CWEOF'
{
  "active_tasks": [],
  "recently_completed": [],
  "blocked": [],
  "last_updated": null
}
CWEOF
    echo "  CREATED: current-work.json (template)"
else
    # Validate JSON
    if python3 -c "import json; json.load(open('$MEMORY_DIR/current-work.json'))" 2>/dev/null; then
        echo "  EXISTS:  current-work.json (valid JSON)"
    else
        echo "  WARNING: current-work.json is INVALID JSON — backing up and recreating"
        cp "$MEMORY_DIR/current-work.json" "$MEMORY_DIR/current-work.json.broken.$(date +%s)"
        cat > "$MEMORY_DIR/current-work.json" << 'CWEOF'
{
  "active_tasks": [],
  "recently_completed": [],
  "blocked": [],
  "last_updated": null
}
CWEOF
    fi
fi

# taskboard.json — task queue
if [ ! -f "$MEMORY_DIR/taskboard.json" ]; then
    cat > "$MEMORY_DIR/taskboard.json" << 'TBEOF'
{
  "pending": [],
  "claimed": [],
  "done": [],
  "last_updated": null
}
TBEOF
    echo "  CREATED: taskboard.json (template)"
else
    if python3 -c "import json; json.load(open('$MEMORY_DIR/taskboard.json'))" 2>/dev/null; then
        echo "  EXISTS:  taskboard.json (valid JSON)"
    else
        echo "  WARNING: taskboard.json is INVALID JSON — backing up and recreating"
        cp "$MEMORY_DIR/taskboard.json" "$MEMORY_DIR/taskboard.json.broken.$(date +%s)"
        cat > "$MEMORY_DIR/taskboard.json" << 'TBEOF'
{
  "pending": [],
  "claimed": [],
  "done": [],
  "last_updated": null
}
TBEOF
    fi
fi

# lessons.json — collective lessons from all workers
if [ ! -f "$MEMORY_DIR/lessons.json" ]; then
    echo "[]" > "$MEMORY_DIR/lessons.json"
    echo "  CREATED: lessons.json (empty array)"
else
    if python3 -c "import json; json.load(open('$MEMORY_DIR/lessons.json'))" 2>/dev/null; then
        LESSON_COUNT=$(python3 -c "import json; print(len(json.load(open('$MEMORY_DIR/lessons.json'))))")
        echo "  EXISTS:  lessons.json ($LESSON_COUNT lessons)"
    else
        echo "  WARNING: lessons.json is INVALID JSON — backing up and recreating"
        cp "$MEMORY_DIR/lessons.json" "$MEMORY_DIR/lessons.json.broken.$(date +%s)"
        echo "[]" > "$MEMORY_DIR/lessons.json"
    fi
fi

# decisions.md — architecture decisions (append-only)
if [ ! -f "$MEMORY_DIR/decisions.md" ]; then
    cat > "$MEMORY_DIR/decisions.md" << 'DECEOF'
# Architecture Decisions

> Append-only log. Never delete entries.

## 2026-02-19: Web Search Enabled (Phase 1)
- **Decision:** Enable Kimi $web_search for live web data
- **Rationale:** Zero EC2 impact, no extra API keys, search runs on Moonshot infra
- **Config:** tools.alsoAllow += web_search, web_fetch; models.json += $web_search native tool

## 2026-02-19: Browser Automation (Phase 2)
- **Decision:** Sandbox sidecar (Option A) for immediate use, BYOC (Option B) for scale
- **Rationale:** t3.medium can't run native browser; container capped at 1GB; BYOC for heavy use
DECEOF
    echo "  CREATED: decisions.md (with initial entries)"
else
    echo "  EXISTS:  decisions.md ($(wc -l < "$MEMORY_DIR/decisions.md") lines)"
fi

# conflicts.json — file-level conflict detection
if [ ! -f "$MEMORY_DIR/conflicts.json" ]; then
    echo "[]" > "$MEMORY_DIR/conflicts.json"
    echo "  CREATED: conflicts.json (empty)"
else
    echo "  EXISTS:  conflicts.json"
fi

# Metrics files
if [ ! -f "$MEMORY_DIR/metrics/cost-tracker.json" ]; then
    cat > "$MEMORY_DIR/metrics/cost-tracker.json" << 'CTEOF'
{
  "daily_totals": {},
  "by_model": {},
  "last_updated": null
}
CTEOF
    echo "  CREATED: metrics/cost-tracker.json"
else
    echo "  EXISTS:  metrics/cost-tracker.json"
fi

if [ ! -f "$MEMORY_DIR/metrics/worker-scores.json" ]; then
    cat > "$MEMORY_DIR/metrics/worker-scores.json" << 'WSEOF'
{
  "workers": {},
  "last_updated": null
}
WSEOF
    echo "  CREATED: metrics/worker-scores.json"
else
    echo "  EXISTS:  metrics/worker-scores.json"
fi
echo ""

# ── 3. Today's daily note ────────────────────────────────────────────────

echo "--- Daily Note ---"

DAILY_FILE="$MEMORY_DIR/daily/$TODAY.md"
if [ ! -f "$DAILY_FILE" ]; then
    cat > "$DAILY_FILE" << DNEOF
# $TODAY

## Decisions
- (none yet)

## Work Done
- (none yet)

## Metrics
- Requests: (pending)
- Cost: ~\$0.00
- Errors: 0

## Blockers
- (none)

## Lessons
- (none yet)

## Self-Improvement
- (pending end-of-day review)

## Tomorrow
- (pending)
DNEOF
    echo "  CREATED: daily/$TODAY.md"
else
    echo "  EXISTS:  daily/$TODAY.md ($(wc -l < "$DAILY_FILE") lines)"
fi
echo ""

# ── 4. Permissions ────────────────────────────────────────────────────────

echo "--- Permissions ---"

# All memory files should be readable/writable by root (gateway runs as root)
chmod -R u+rw "$MEMORY_DIR"
echo "  Set u+rw on $MEMORY_DIR (recursive)"

# Workspace should also be writable
[ -d "$WORKSPACE_DIR" ] && chmod -R u+rw "$WORKSPACE_DIR"
echo "  Set u+rw on $WORKSPACE_DIR (recursive)"
echo ""

# ── 5. Disk usage ────────────────────────────────────────────────────────

echo "--- Memory Disk Usage ---"
du -sh "$MEMORY_DIR" 2>/dev/null || echo "  Could not measure"
du -sh "$MEMORY_DIR/daily/" 2>/dev/null || echo "  No daily notes"
du -sh "$MEMORY_DIR/metrics/" 2>/dev/null || echo "  No metrics"

# Count daily notes
DAILY_COUNT=$(ls "$MEMORY_DIR/daily/" 2>/dev/null | wc -l)
echo "  Daily notes: $DAILY_COUNT files"

# Warn if too many (should archive >7 days)
if [ "$DAILY_COUNT" -gt 14 ]; then
    echo "  WARNING: $DAILY_COUNT daily notes. Consider archiving notes older than 7 days."
fi
echo ""

# ── 6. Summary ────────────────────────────────────────────────────────────

echo "=== Memory Hardening Complete ==="
echo ""
echo "Files in $MEMORY_DIR:"
ls -la "$MEMORY_DIR/" 2>/dev/null
echo ""
echo "Session start protocol should now work:"
echo "  STEP 1: Read MEMORY.md, latest daily note, current-work.json, lessons.json"
echo "  STEP 2: Health check (gateway, APIs, RAM, sessions)"
echo "  STEP 3: State report to president"
echo "  STEP 4: Await instructions"
