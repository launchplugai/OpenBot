"""Heartbeat — the autonomous pulse of fixit.bot.

The heartbeat runs at a regular interval (default: 15 minutes).
Each beat:
  1. Collects signals from pre-selected categories
  2. Runs ONE reasoning frame (rotated each beat, not all 6)
  3. Dumps findings into the suggestion pool
  4. Reads the pool BACK as input (feedback loop)
  5. Sweeps the pool (auto-deprecate stale, archive resolved)
  6. On delivery schedule, generates a report

Design constraints:
  - ONE frame per beat (keeps each beat fast and cheap)
  - Categories only run if something CHANGED (skip unchanged)
  - Single Haiku call per beat (~$0.0005, <2s)
  - Pool feedback means the crow checks its own past work
  - Report delivery on a separate, slower cadence (e.g. every 2 hours)
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from fixit.categories import (
    CategoryResult,
    LintCategory,
    LogCategory,
    ActiveWorkCategory,
    DriftCategory,
    ResourceCategory,
)
from fixit.engine import Crow
from fixit.frames import FRAMES
from fixit.suggestions import SuggestionPool

logger = logging.getLogger("fixit.heartbeat")


@dataclass
class HeartbeatConfig:
    """Configuration for the heartbeat daemon."""

    # Timing
    beat_interval: int = 900            # seconds between beats (15 min)
    report_interval: int = 7200         # seconds between reports (2 hours)

    # Categories to run
    lint_paths: list[str] = field(default_factory=list)
    log_units: list[str] = field(default_factory=list)
    log_files: list[str] = field(default_factory=list)
    repo_path: str = "."
    config_paths: list[str] = field(default_factory=list)
    session_dir: Optional[str] = None

    # Plugin (if set, overrides manual category config)
    plugin: Optional[str] = None

    # Thresholds
    min_confidence: float = 0.6         # don't pool anything below this
    report_threshold: float = 0.5       # include in report above this

    # Limits
    max_findings_per_beat: int = 5      # cap findings per beat

    # Delivery
    report_path: Optional[str] = None   # write report to this file
    report_callback: Optional[str] = None  # shell command to run on report

    @classmethod
    def from_dict(cls, d: dict) -> HeartbeatConfig:
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})

    @classmethod
    def from_file(cls, path: str | Path) -> HeartbeatConfig:
        p = Path(path)
        if p.exists():
            data = json.loads(p.read_text())
            return cls.from_dict(data)
        return cls()


@dataclass
class BeatResult:
    """Result of a single heartbeat."""

    timestamp: float
    frame_used: str
    categories_checked: list[str]
    categories_changed: list[str]
    findings_added: int
    findings_merged: int
    pool_size: int
    sweep_result: dict
    report_generated: bool = False
    duration_ms: int = 0


class Heartbeat:
    """The autonomous heartbeat daemon.

    Usage:
        hb = Heartbeat(config)
        hb.run_forever()        # blocking loop

        # Or single beat (for cron/testing):
        result = hb.beat()
    """

    def __init__(self, config: HeartbeatConfig | None = None, data_dir: str | None = None):
        self.config = config or HeartbeatConfig()
        self.data_dir = Path(data_dir or "~/.fixit").expanduser()
        self.pool = SuggestionPool(self.data_dir / "pool")
        self.state_path = self.data_dir / "heartbeat-state.json"

        # Frame rotation: cycle through all 6, one per beat
        self._frame_index = self._load_frame_index()
        self._last_report_time = self._load_last_report_time()

        # Build categories from config
        self._categories = self._build_categories()

    def beat(self) -> BeatResult:
        """Run a single heartbeat. This is the core loop iteration."""
        start = time.monotonic()
        now = time.time()

        # 1. Pick the frame for this beat (rotate)
        frame = FRAMES[self._frame_index % len(FRAMES)]
        self._frame_index += 1
        self._save_state()

        logger.info(f"Beat: frame={frame.name}, categories={len(self._categories)}")

        # 2. Collect from all categories
        category_results: list[CategoryResult] = []
        categories_changed: list[str] = []

        for cat in self._categories:
            try:
                result = cat.collect()
                category_results.append(result)
                if result.changed:
                    categories_changed.append(result.category)
            except Exception as e:
                logger.warning(f"Category {cat.name} failed: {e}")

        # 3. Read the pool back as input signal (FEEDBACK LOOP)
        pool_signal = self.pool.as_signal()

        # 4. Build signals for the crow
        signals: dict[str, Any] = {
            "timestamp": now,
            "heartbeat": {
                "beat_number": self._frame_index,
                "frame": frame.name,
                "categories_changed": categories_changed,
            },
            "pool_feedback": pool_signal,
        }
        for cr in category_results:
            signals[cr.category] = cr.data

        # 5. Run the single frame through the crow
        crow = Crow(
            target=self.config.repo_path,
            data_dir=str(self.data_dir),
        )

        # Add heartbeat-specific context
        crow.add_context(
            f"This is heartbeat beat #{self._frame_index}. "
            f"Running frame: {frame.name}. "
            f"Categories that changed since last beat: {categories_changed or 'none'}."
        )
        crow.add_context(
            f"Current suggestion pool has {pool_signal['pool_size']} open items. "
            f"Recurring patterns: {pool_signal.get('recurring_patterns', [])}"
        )

        if self.config.plugin:
            crow.load_plugin(self.config.plugin)

        prescriptions = crow.scan(frames=[frame.name], save=True)

        # 6. Filter and categorize findings into the pool
        added = 0
        merged = 0

        for rx in prescriptions:
            if rx.confidence < self.config.min_confidence:
                continue
            if added >= self.config.max_findings_per_beat:
                break

            # Categorize: high blast + high confidence = fix
            # Design-level suggestions = upgrade
            # Everything else = patch
            category = _categorize_prescription(rx)

            existing = self.pool._find_similar(self.pool._load(), rx.title, rx.frame)
            if existing and existing.status == "open":
                merged += 1
            else:
                added += 1

            self.pool.add(
                category=category,
                title=rx.title,
                explanation=rx.explanation,
                frame=rx.frame,
                confidence=rx.confidence,
                blast_radius=rx.blast_radius,
                command=rx.command,
                tags=rx.tags,
            )

        # 7. Sweep the pool (auto-deprecate, archive)
        sweep_result = self.pool.sweep()

        # 8. Check if it's time for a delivery report
        report_generated = False
        if self._is_report_due():
            self._deliver_report()
            self._last_report_time = now
            self._save_state()
            report_generated = True

        duration_ms = int((time.monotonic() - start) * 1000)

        result = BeatResult(
            timestamp=now,
            frame_used=frame.name,
            categories_checked=[cr.category for cr in category_results],
            categories_changed=categories_changed,
            findings_added=added,
            findings_merged=merged,
            pool_size=len(self.pool.all_open()),
            sweep_result=sweep_result,
            report_generated=report_generated,
            duration_ms=duration_ms,
        )

        logger.info(
            f"Beat done: {duration_ms}ms, +{added} new, ~{merged} merged, "
            f"pool={result.pool_size}, frame={frame.name}"
        )

        return result

    def run_forever(self) -> None:
        """Run the heartbeat in a blocking loop."""
        logger.info(
            f"Heartbeat starting: interval={self.config.beat_interval}s, "
            f"report_interval={self.config.report_interval}s"
        )

        while True:
            try:
                result = self.beat()
                logger.info(f"Next beat in {self.config.beat_interval}s")
            except KeyboardInterrupt:
                logger.info("Heartbeat stopped by user.")
                break
            except Exception as e:
                logger.error(f"Beat failed: {e}")

            time.sleep(self.config.beat_interval)

    def report(self) -> str:
        """Generate the current suggestion report."""
        return self.pool.report()

    def pool_stats(self) -> dict[str, Any]:
        """Get pool statistics."""
        stats = self.pool.stats()
        stats["frame_index"] = self._frame_index
        stats["next_frame"] = FRAMES[self._frame_index % len(FRAMES)].name
        stats["last_report"] = self._last_report_time
        return stats

    # ── Internal ──────────────────────────────────────────────────────

    def _build_categories(self) -> list:
        """Build category collectors from config."""
        cats: list = []

        if self.config.lint_paths:
            cats.append(LintCategory(self.config.lint_paths))

        if self.config.log_units or self.config.log_files:
            cats.append(LogCategory(
                units=self.config.log_units,
                log_files=self.config.log_files,
            ))

        if self.config.repo_path:
            cats.append(ActiveWorkCategory(self.config.repo_path))

        if self.config.config_paths:
            cats.append(DriftCategory(
                config_paths=self.config.config_paths,
                snapshot_path=str(self.data_dir / "drift-snapshot.json"),
            ))

        # Resource is always on — it's cheap
        cats.append(ResourceCategory(
            session_dir=self.config.session_dir,
        ))

        return cats

    def _is_report_due(self) -> bool:
        """Is it time to deliver a report?"""
        if self._last_report_time is None:
            return True  # first beat always generates a report
        return (time.time() - self._last_report_time) >= self.config.report_interval

    def _deliver_report(self) -> None:
        """Generate and deliver a suggestion report."""
        report_text = self.pool.report()

        # Write to file if configured
        if self.config.report_path:
            report_file = Path(self.config.report_path)
            report_file.parent.mkdir(parents=True, exist_ok=True)
            report_file.write_text(report_text)
            logger.info(f"Report written to {report_file}")

        # Run callback if configured (e.g., send to Telegram)
        if self.config.report_callback:
            import subprocess
            try:
                subprocess.run(
                    self.config.report_callback,
                    input=report_text,
                    shell=True,
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
                logger.info("Report callback executed")
            except (subprocess.TimeoutExpired, OSError) as e:
                logger.warning(f"Report callback failed: {e}")

        # Always write to the standard report location
        standard_report = self.data_dir / "latest-report.txt"
        standard_report.write_text(report_text)

    def _load_frame_index(self) -> int:
        state = self._load_state()
        return state.get("frame_index", 0)

    def _load_last_report_time(self) -> Optional[float]:
        state = self._load_state()
        return state.get("last_report_time")

    def _load_state(self) -> dict:
        if self.state_path.exists():
            try:
                return json.loads(self.state_path.read_text())
            except (json.JSONDecodeError, OSError):
                pass
        return {}

    def _save_state(self) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        state = {
            "frame_index": self._frame_index,
            "last_report_time": self._last_report_time,
            "last_beat": time.time(),
        }
        self.state_path.write_text(json.dumps(state, indent=2))


def _categorize_prescription(rx) -> str:
    """Decide if a prescription is a fix, upgrade, or patch.

    fix:     High confidence + high blast = active problem, fix now
    upgrade: Design-level suggestion, architectural change
    patch:   Everything else — incremental improvement
    """
    # Active problems: high confidence AND (high blast OR error-related tags)
    if rx.confidence >= 0.8 and rx.blast_radius == "high":
        return "fix"
    if rx.confidence >= 0.85 and any(t in rx.tags for t in ("error", "crash", "security", "leak")):
        return "fix"

    # Design improvements: from certain frames + lower urgency
    if rx.frame in ("removal", "analogy", "constraint") and rx.blast_radius != "high":
        return "upgrade"
    if any(t in rx.tags for t in ("architecture", "design", "refactor", "optimization")):
        return "upgrade"

    return "patch"
