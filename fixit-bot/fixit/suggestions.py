"""Suggestion Pool — the living queue where fixit findings land, live, and die.

The pool is THREE things:
  1. An OUTPUT for new findings (heartbeat dumps here)
  2. An INPUT for the next heartbeat (fixit reads it back to check status)
  3. A self-cleaning lifecycle manager

Item lifecycle:
  OPEN → RESOLVED     (fix confirmed — removed from pool)
  OPEN → IMPLEMENTED  (upgrade selected + shipped — removed from pool)
  OPEN → DEPRECATED   (too old, no longer relevant — aged out)
  OPEN → MERGED       (duplicate of existing item — consolidated)

Pool categories:
  fix       Active problem. Should be resolved soon. Auto-escalates if old.
  upgrade   Design improvement. Stays until implemented or deprecated.
  patch     Incremental fix. Medium lifespan.

The pool persists as a single JSON file. Flat. Simple. Grep-friendly.
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Optional


# How many days before items auto-deprecate (by category)
AUTO_DEPRECATE_DAYS = {
    "fix": 14,        # fixes should be resolved within 2 weeks
    "patch": 30,      # patches within a month
    "upgrade": 90,    # upgrades get 3 months to be selected
}


@dataclass
class Suggestion:
    """A single item in the pool."""

    id: str
    category: str                       # fix | upgrade | patch
    title: str
    explanation: str
    frame: str                          # which reasoning frame originated this
    confidence: float
    blast_radius: str
    command: Optional[str] = None       # suggested fix
    tags: list[str] = field(default_factory=list)

    # Lifecycle
    status: str = "open"                # open | resolved | implemented | deprecated | merged
    created_at: float = 0.0
    updated_at: float = 0.0
    resolved_at: Optional[float] = None
    merged_into: Optional[str] = None   # ID of the item this was merged into

    # Tracking
    seen_count: int = 1                 # how many heartbeats have seen this pattern
    last_seen_at: float = 0.0
    source_scans: list[str] = field(default_factory=list)  # scan IDs that found this

    def age_days(self) -> float:
        return (time.time() - self.created_at) / 86400

    def is_stale(self) -> bool:
        """Is this item past its auto-deprecation age?"""
        max_days = AUTO_DEPRECATE_DAYS.get(self.category, 30)
        return self.age_days() > max_days

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> Suggestion:
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


class SuggestionPool:
    """Persistent suggestion queue with lifecycle management.

    The pool is stored as a single JSON file at data_dir/pool.json.
    """

    def __init__(self, data_dir: str | Path):
        self.data_dir = Path(data_dir)
        self.pool_path = self.data_dir / "pool.json"
        self.archive_path = self.data_dir / "pool-archive.json"
        self.data_dir.mkdir(parents=True, exist_ok=True)

    # ── Write Operations ──────────────────────────────────────────────

    def add(
        self,
        category: str,
        title: str,
        explanation: str,
        frame: str,
        confidence: float,
        blast_radius: str = "low",
        command: str | None = None,
        tags: list[str] | None = None,
        scan_id: str | None = None,
    ) -> Suggestion:
        """Add a new suggestion or merge with an existing similar one."""
        pool = self._load()
        now = time.time()

        # Check for duplicates (same title or very similar)
        existing = self._find_similar(pool, title, frame)
        if existing and existing.status == "open":
            # Merge: bump seen count, update confidence, add scan reference
            existing.seen_count += 1
            existing.last_seen_at = now
            existing.updated_at = now
            if confidence > existing.confidence:
                existing.confidence = confidence
            if scan_id:
                existing.source_scans.append(scan_id)
                existing.source_scans = existing.source_scans[-20:]  # cap history
            self._save(pool)
            return existing

        # New suggestion
        suggestion = Suggestion(
            id=f"sg-{uuid.uuid4().hex[:8]}",
            category=category,
            title=title,
            explanation=explanation,
            frame=frame,
            confidence=confidence,
            blast_radius=blast_radius,
            command=command,
            tags=tags or [],
            created_at=now,
            updated_at=now,
            last_seen_at=now,
            source_scans=[scan_id] if scan_id else [],
        )
        pool.append(suggestion)
        self._save(pool)
        return suggestion

    def resolve(self, suggestion_id: str) -> Suggestion:
        """Mark a fix as resolved (problem is gone)."""
        return self._transition(suggestion_id, "resolved")

    def implement(self, suggestion_id: str) -> Suggestion:
        """Mark an upgrade as implemented (shipped)."""
        return self._transition(suggestion_id, "implemented")

    def deprecate(self, suggestion_id: str) -> Suggestion:
        """Mark as deprecated (no longer relevant)."""
        return self._transition(suggestion_id, "deprecated")

    # ── Read Operations ───────────────────────────────────────────────

    def open_items(self, category: str | None = None) -> list[Suggestion]:
        """Get all open suggestions, optionally filtered by category."""
        pool = self._load()
        items = [s for s in pool if s.status == "open"]
        if category:
            items = [s for s in items if s.category == category]
        return sorted(items, key=lambda s: -s.confidence)

    def fixes(self) -> list[Suggestion]:
        """Get open fix items (active problems)."""
        return self.open_items("fix")

    def upgrades(self) -> list[Suggestion]:
        """Get open upgrade items (design improvements)."""
        return self.open_items("upgrade")

    def patches(self) -> list[Suggestion]:
        """Get open patch items."""
        return self.open_items("patch")

    def all_open(self) -> list[Suggestion]:
        """Get everything that's open."""
        return self.open_items()

    def stats(self) -> dict[str, Any]:
        """Pool summary stats."""
        pool = self._load()
        open_items = [s for s in pool if s.status == "open"]
        return {
            "total": len(pool),
            "open": len(open_items),
            "by_category": {
                "fix": len([s for s in open_items if s.category == "fix"]),
                "upgrade": len([s for s in open_items if s.category == "upgrade"]),
                "patch": len([s for s in open_items if s.category == "patch"]),
            },
            "by_status": _count_by_attr(pool, "status"),
            "avg_age_days": round(
                sum(s.age_days() for s in open_items) / len(open_items), 1
            ) if open_items else 0,
            "stale_count": len([s for s in open_items if s.is_stale()]),
            "recurring": len([s for s in open_items if s.seen_count > 3]),
        }

    # ── Feedback Loop ─────────────────────────────────────────────────

    def as_signal(self) -> dict[str, Any]:
        """Export the pool as a signal for the next heartbeat.

        This is the FEEDBACK LOOP. The crow reads its own previous
        suggestions to check: is this still happening? Is it resolved?
        Should the confidence go up because it keeps recurring?
        """
        open_items = self.open_items()
        return {
            "pool_size": len(open_items),
            "fixes": [
                {"id": s.id, "title": s.title, "seen_count": s.seen_count,
                 "age_days": round(s.age_days(), 1), "confidence": s.confidence}
                for s in open_items if s.category == "fix"
            ],
            "upgrades": [
                {"id": s.id, "title": s.title, "seen_count": s.seen_count,
                 "age_days": round(s.age_days(), 1)}
                for s in open_items if s.category == "upgrade"
            ],
            "patches": [
                {"id": s.id, "title": s.title, "seen_count": s.seen_count,
                 "age_days": round(s.age_days(), 1)}
                for s in open_items if s.category == "patch"
            ],
            "recurring_patterns": [
                s.title for s in open_items if s.seen_count > 3
            ],
            "stale_items": [
                {"id": s.id, "title": s.title, "age_days": round(s.age_days(), 1)}
                for s in open_items if s.is_stale()
            ],
        }

    # ── Lifecycle Management ──────────────────────────────────────────

    def sweep(self) -> dict[str, int]:
        """Run lifecycle maintenance.

        - Auto-deprecate stale items
        - Archive resolved/implemented/deprecated items
        - Return counts of what was cleaned
        """
        pool = self._load()
        now = time.time()
        archived = 0
        deprecated = 0

        active: list[Suggestion] = []
        to_archive: list[Suggestion] = []

        for s in pool:
            # Auto-deprecate stale open items
            if s.status == "open" and s.is_stale():
                s.status = "deprecated"
                s.resolved_at = now
                deprecated += 1

            # Archive non-open items older than 7 days
            if s.status != "open" and s.resolved_at:
                if (now - s.resolved_at) > 7 * 86400:
                    to_archive.append(s)
                    archived += 1
                    continue

            active.append(s)

        # Write archive
        if to_archive:
            self._append_archive(to_archive)

        self._save(active)

        return {"deprecated": deprecated, "archived": archived, "remaining": len(active)}

    # ── Delivery Report ───────────────────────────────────────────────

    def report(self, max_items: int = 10) -> str:
        """Generate a human-readable suggestion report.

        This is what gets delivered to the operator on schedule.
        """
        open_items = self.open_items()
        if not open_items:
            return "fixit.bot: Pool is empty. No suggestions pending."

        lines = [
            "fixit.bot — Suggestion Report",
            f"Time: {time.strftime('%Y-%m-%d %H:%M')}",
            f"Open: {len(open_items)} items",
            "",
        ]

        # Fixes first (active problems)
        fixes = [s for s in open_items if s.category == "fix"]
        if fixes:
            lines.append("FIXES (active problems):")
            for s in fixes[:max_items]:
                recur = f" (seen {s.seen_count}x)" if s.seen_count > 1 else ""
                lines.append(f"  [{s.confidence:.0%}] {s.title}{recur}")
                if s.command:
                    lines.append(f"    Fix: {s.command}")
            lines.append("")

        # Patches
        patches = [s for s in open_items if s.category == "patch"]
        if patches:
            lines.append("PATCHES (incremental):")
            for s in patches[:max_items]:
                lines.append(f"  [{s.confidence:.0%}] {s.title}")
            lines.append("")

        # Upgrades
        upgrades = [s for s in open_items if s.category == "upgrade"]
        if upgrades:
            lines.append("UPGRADES (design improvements):")
            for s in upgrades[:max_items]:
                age = f" ({s.age_days():.0f}d old)" if s.age_days() > 7 else ""
                lines.append(f"  [{s.confidence:.0%}] {s.title}{age}")
            lines.append("")

        # Recurring patterns (keep coming back)
        recurring = [s for s in open_items if s.seen_count > 3]
        if recurring:
            lines.append("RECURRING (keeps coming back):")
            for s in recurring:
                lines.append(f"  {s.title} — seen {s.seen_count}x over {s.age_days():.0f} days")
            lines.append("")

        # Stale items
        stale = [s for s in open_items if s.is_stale()]
        if stale:
            lines.append(f"STALE ({len(stale)} items past deprecation age)")
            lines.append("")

        return "\n".join(lines)

    # ── Internal ──────────────────────────────────────────────────────

    def _load(self) -> list[Suggestion]:
        if self.pool_path.exists():
            try:
                data = json.loads(self.pool_path.read_text())
                return [Suggestion.from_dict(d) for d in data]
            except (json.JSONDecodeError, KeyError):
                pass
        return []

    def _save(self, pool: list[Suggestion]) -> None:
        self.pool_path.write_text(json.dumps(
            [s.to_dict() for s in pool], indent=2
        ))

    def _find_similar(self, pool: list[Suggestion], title: str, frame: str) -> Optional[Suggestion]:
        """Find an existing suggestion with a similar title and same frame."""
        title_lower = title.lower()
        for s in pool:
            if s.status != "open":
                continue
            # Exact title match or high overlap
            if s.title.lower() == title_lower:
                return s
            # Same frame + significant word overlap
            if s.frame == frame:
                words_new = set(title_lower.split())
                words_old = set(s.title.lower().split())
                if len(words_new) > 2 and len(words_new & words_old) / len(words_new) > 0.7:
                    return s
        return None

    def _transition(self, suggestion_id: str, new_status: str) -> Suggestion:
        pool = self._load()
        for s in pool:
            if s.id == suggestion_id:
                s.status = new_status
                s.resolved_at = time.time()
                s.updated_at = time.time()
                self._save(pool)
                return s
        raise ValueError(f"Suggestion {suggestion_id} not found")

    def _append_archive(self, items: list[Suggestion]) -> None:
        archive: list[dict] = []
        if self.archive_path.exists():
            try:
                archive = json.loads(self.archive_path.read_text())
            except (json.JSONDecodeError, OSError):
                pass
        archive.extend(s.to_dict() for s in items)
        # Cap archive at 500 items
        archive = archive[-500:]
        self.archive_path.write_text(json.dumps(archive, indent=2))


def _count_by_attr(items: list[Suggestion], attr: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in items:
        val = getattr(item, attr, "unknown")
        counts[val] = counts.get(val, 0) + 1
    return counts
