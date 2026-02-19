#!/bin/bash
# hydrate-efs.sh — Populate EFS with transplant data (one-time operation)
#
# Run this as a one-off ECS task or from any machine with EFS mounted.
# It extracts the consciousness transplant tarball into the EFS mount point.
#
# Usage patterns:
#
#   1. Inside a Fargate task (EFS mounted at /root/.openclaw):
#      bash hydrate-efs.sh --from-s3 s3://bucket/migration/openclaw-transplant-XXXXX.tar.gz
#
#   2. From an EC2 with EFS mounted:
#      bash hydrate-efs.sh --from-file /tmp/openclaw-transplant-XXXXX.tar.gz --mount-point /mnt/efs/openclaw
#
#   3. Dry run (show what would happen):
#      bash hydrate-efs.sh --from-s3 s3://bucket/file.tar.gz --dry-run

set -euo pipefail

# ── Args ───────────────────────────────────────────────────────────────────

SOURCE=""
S3_SOURCE=""
MOUNT_POINT="/root/.openclaw"
DRY_RUN=false

while [[ $# -gt 0 ]]; do
    case "$1" in
        --from-s3)       S3_SOURCE="$2"; shift 2 ;;
        --from-file)     SOURCE="$2"; shift 2 ;;
        --mount-point)   MOUNT_POINT="$2"; shift 2 ;;
        --dry-run)       DRY_RUN=true; shift ;;
        --help|-h)
            echo "Usage: $0 [--from-s3 s3://...] [--from-file /path/to/tarball] [--mount-point /root/.openclaw] [--dry-run]"
            exit 0
            ;;
        *) echo "Unknown flag: $1"; exit 1 ;;
    esac
done

echo "=== EFS Hydration ==="
echo "Timestamp:   $(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo "Mount point: $MOUNT_POINT"
echo "Source:      ${S3_SOURCE:-${SOURCE:-none}}"
echo "Dry run:     $DRY_RUN"
echo ""

# ── Preflight ──────────────────────────────────────────────────────────────

echo "--- Preflight ---"

if [ -z "$S3_SOURCE" ] && [ -z "$SOURCE" ]; then
    echo "ERROR: Specify --from-s3 or --from-file"
    exit 1
fi

if [ ! -d "$MOUNT_POINT" ]; then
    echo "ERROR: Mount point does not exist: $MOUNT_POINT"
    echo "Is EFS mounted? Check: df -h | grep efs"
    exit 1
fi

if [ ! -w "$MOUNT_POINT" ]; then
    echo "ERROR: Mount point is not writable: $MOUNT_POINT"
    echo "Check EFS access point permissions."
    exit 1
fi

echo "Mount point: exists and writable"

# Check if already hydrated
if [ -f "$MOUNT_POINT/memory/MEMORY.md" ] && [ -f "$MOUNT_POINT/openclaw.json" ]; then
    EXISTING_LESSONS=$(python3 -c "import json; print(len(json.load(open('$MOUNT_POINT/memory/lessons.json'))))" 2>/dev/null || echo "?")
    echo ""
    echo "WARNING: EFS already contains data:"
    echo "  MEMORY.md:    $(wc -l < "$MOUNT_POINT/memory/MEMORY.md") lines"
    echo "  Lessons:      $EXISTING_LESSONS"
    echo "  openclaw.json: exists"
    echo ""
    echo "Hydrating will OVERWRITE existing data."
    echo "If this is a re-hydration, make sure you've exported the latest state first."
    echo ""
    if [ "$DRY_RUN" = "false" ]; then
        # Create pre-hydration backup on EFS itself
        BACKUP_DIR="$MOUNT_POINT/backups/pre-hydration-$(date +%Y%m%d-%H%M%S)"
        mkdir -p "$BACKUP_DIR"
        cp -a "$MOUNT_POINT/memory" "$BACKUP_DIR/" 2>/dev/null || true
        cp -a "$MOUNT_POINT/openclaw.json" "$BACKUP_DIR/" 2>/dev/null || true
        cp -a "$MOUNT_POINT/agents" "$BACKUP_DIR/" 2>/dev/null || true
        echo "Pre-hydration backup: $BACKUP_DIR"
    fi
fi

echo ""

# ── Download ───────────────────────────────────────────────────────────────

TARBALL="/tmp/transplant-hydration-$$.tar.gz"

if [ -n "$S3_SOURCE" ]; then
    echo "--- Downloading from S3 ---"
    if [ "$DRY_RUN" = "true" ]; then
        echo "  [DRY RUN] aws s3 cp $S3_SOURCE $TARBALL"
    else
        aws s3 cp "$S3_SOURCE" "$TARBALL"
        echo "  Downloaded: $(du -h "$TARBALL" | cut -f1)"
    fi
elif [ -n "$SOURCE" ]; then
    if [ ! -f "$SOURCE" ]; then
        echo "ERROR: File not found: $SOURCE"
        exit 1
    fi
    TARBALL="$SOURCE"
    echo "Using local file: $(du -h "$TARBALL" | cut -f1)"
fi

echo ""

# ── Inspect ────────────────────────────────────────────────────────────────

echo "--- Tarball Contents ---"
if [ "$DRY_RUN" = "false" ] && [ -f "$TARBALL" ]; then
    echo "Files:"
    tar tzf "$TARBALL" | head -30
    TOTAL=$(tar tzf "$TARBALL" | wc -l)
    echo "... ($TOTAL files total)"
    echo ""

    # Check manifest
    echo "Manifest:"
    tar xzf "$TARBALL" -O ./manifest.json 2>/dev/null | python3 -m json.tool 2>/dev/null || echo "  No manifest found"
    echo ""

    # Verify no secrets leaked
    echo "Secret scan:"
    STAGING="/tmp/hydration-scan-$$"
    mkdir -p "$STAGING"
    tar xzf "$TARBALL" -C "$STAGING"
    LEAKS=$(grep -rIn --exclude-dir=.git -E "(sk-ant-|ghp_|xoxb-|tskey-auth-)" "$STAGING" 2>/dev/null | grep -v "CHANGE_ME" | wc -l)
    if [ "$LEAKS" -gt 0 ]; then
        echo "  WARNING: $LEAKS potential secret leaks found!"
        grep -rIn --exclude-dir=.git -E "(sk-ant-|ghp_|xoxb-|tskey-auth-)" "$STAGING" 2>/dev/null | grep -v "CHANGE_ME" | head -5
        echo ""
        echo "  ABORT: Scrub the tarball first. Do NOT hydrate with real secrets in config files."
        rm -rf "$STAGING"
        exit 1
    else
        echo "  Clean — no secrets found (good)"
    fi
    rm -rf "$STAGING"
else
    echo "  [DRY RUN] Would inspect tarball contents"
fi

echo ""

# ── Extract ────────────────────────────────────────────────────────────────

echo "--- Hydrating EFS ---"

if [ "$DRY_RUN" = "true" ]; then
    echo "  [DRY RUN] Would extract tarball to $MOUNT_POINT"
    echo "  [DRY RUN] Would create subdirectories"
    echo "  [DRY RUN] Would set permissions"
    echo ""
    echo "=== Dry Run Complete ==="
    exit 0
fi

# Extract
tar xzf "$TARBALL" -C "$MOUNT_POINT"
echo "  Extracted to: $MOUNT_POINT"

# Ensure directory structure
mkdir -p "$MOUNT_POINT/memory/daily"
mkdir -p "$MOUNT_POINT/memory/metrics/session-reports"
mkdir -p "$MOUNT_POINT/agents/main/agent"
mkdir -p "$MOUNT_POINT/hooks/transforms"
mkdir -p "$MOUNT_POINT/config-profiles"
mkdir -p "$MOUNT_POINT/workspace"
mkdir -p "$MOUNT_POINT/backups"

# CRITICAL: Do NOT create a sessions directory on EFS
# Sessions must stay ephemeral in /tmp/openclaw/sessions/
rm -rf "$MOUNT_POINT/sessions" 2>/dev/null || true

# Set permissions
chmod -R u+rw "$MOUNT_POINT/memory/" 2>/dev/null || true
chmod u+rw "$MOUNT_POINT/openclaw.json" 2>/dev/null || true

echo ""

# ── Verify ─────────────────────────────────────────────────────────────────

echo "--- Verification ---"

PASS=0
FAIL=0

verify() {
    local label="$1"
    local check="$2"
    if eval "$check"; then
        echo "  PASS: $label"
        ((PASS++)) || true
    else
        echo "  FAIL: $label"
        ((FAIL++)) || true
    fi
}

verify "MEMORY.md exists" "[ -f '$MOUNT_POINT/memory/MEMORY.md' ]"
verify "lessons.json exists" "[ -f '$MOUNT_POINT/memory/lessons.json' ]"
verify "lessons.json valid JSON" "python3 -c \"import json; json.load(open('$MOUNT_POINT/memory/lessons.json'))\" 2>/dev/null"
verify "current-work.json exists" "[ -f '$MOUNT_POINT/memory/current-work.json' ]"
verify "taskboard.json exists" "[ -f '$MOUNT_POINT/memory/taskboard.json' ]"
verify "decisions.md exists" "[ -f '$MOUNT_POINT/memory/decisions.md' ]"
verify "daily notes directory" "[ -d '$MOUNT_POINT/memory/daily' ]"
verify "models.json exists" "[ -f '$MOUNT_POINT/agents/main/agent/models.json' ]"
verify "models.json valid JSON" "python3 -c \"import json; json.load(open('$MOUNT_POINT/agents/main/agent/models.json'))\" 2>/dev/null"
verify "system.md exists" "[ -f '$MOUNT_POINT/agents/main/agent/system.md' ]"
verify "openclaw.json exists" "[ -f '$MOUNT_POINT/openclaw.json' ]"
verify "openclaw.json valid JSON" "python3 -c \"import json; json.load(open('$MOUNT_POINT/openclaw.json'))\" 2>/dev/null"
verify "openclaw.json writable" "[ -w '$MOUNT_POINT/openclaw.json' ]"
verify "No sessions on EFS" "[ ! -d '$MOUNT_POINT/sessions' ]"
verify "hooks/transforms dir" "[ -d '$MOUNT_POINT/hooks/transforms' ]"

echo ""
echo "  Results: $PASS passed, $FAIL failed"

if [ "$FAIL" -gt 0 ]; then
    echo ""
    echo "  Some checks failed. Review above and fix before starting the gateway."
fi

# Cleanup temp tarball (only if we downloaded from S3)
if [ -n "$S3_SOURCE" ] && [ -f "$TARBALL" ]; then
    rm -f "$TARBALL"
fi

echo ""
echo "=== Hydration Complete ==="
echo ""
echo "EFS state at $MOUNT_POINT:"
echo "  Memory:    $(wc -l < "$MOUNT_POINT/memory/MEMORY.md" 2>/dev/null || echo '?') lines in MEMORY.md"
echo "  Lessons:   $(python3 -c "import json; print(len(json.load(open('$MOUNT_POINT/memory/lessons.json'))))" 2>/dev/null || echo '?') entries"
echo "  Daily:     $(ls "$MOUNT_POINT/memory/daily/" 2>/dev/null | wc -l) notes"
echo "  Decisions: $(wc -l < "$MOUNT_POINT/memory/decisions.md" 2>/dev/null || echo '?') lines"
echo ""
echo "Next: Fill secrets via Secrets Manager, then start the gateway service."
