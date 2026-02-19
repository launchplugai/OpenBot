"""Tests for the heartbeat, suggestion pool, and categories."""

import json
import os
import tempfile
import time
from pathlib import Path

from fixit.categories import (
    LintCategory,
    LogCategory,
    ActiveWorkCategory,
    DriftCategory,
    ResourceCategory,
)
from fixit.heartbeat import Heartbeat, HeartbeatConfig, _categorize_prescription
from fixit.prescription import Prescription
from fixit.suggestions import SuggestionPool, Suggestion


# ── Suggestion Pool ───────────────────────────────────────────────────

def test_pool_add_and_retrieve():
    with tempfile.TemporaryDirectory() as td:
        pool = SuggestionPool(td)
        s = pool.add(
            category="fix",
            title="Anthropic key in shell env",
            explanation="Causes provider auto-discovery",
            frame="inversion",
            confidence=0.9,
            blast_radius="medium",
        )
        assert s.id.startswith("sg-")
        assert s.status == "open"
        assert s.category == "fix"

        fixes = pool.fixes()
        assert len(fixes) == 1
        assert fixes[0].title == "Anthropic key in shell env"


def test_pool_dedup_merges():
    with tempfile.TemporaryDirectory() as td:
        pool = SuggestionPool(td)
        s1 = pool.add(category="fix", title="Same problem", explanation="a",
                       frame="edge", confidence=0.7)
        s2 = pool.add(category="fix", title="Same problem", explanation="b",
                       frame="edge", confidence=0.9)

        # Should merge, not create a second item
        assert len(pool.fixes()) == 1
        merged = pool.fixes()[0]
        assert merged.seen_count == 2
        assert merged.confidence == 0.9  # took the higher confidence


def test_pool_resolve_removes_from_open():
    with tempfile.TemporaryDirectory() as td:
        pool = SuggestionPool(td)
        s = pool.add(category="fix", title="Broken config", explanation="test",
                      frame="temporal", confidence=0.8)

        pool.resolve(s.id)
        assert len(pool.fixes()) == 0


def test_pool_implement_removes_upgrade():
    with tempfile.TemporaryDirectory() as td:
        pool = SuggestionPool(td)
        s = pool.add(category="upgrade", title="Add monitoring", explanation="test",
                      frame="removal", confidence=0.7)

        pool.implement(s.id)
        assert len(pool.upgrades()) == 0


def test_pool_auto_deprecate():
    with tempfile.TemporaryDirectory() as td:
        pool = SuggestionPool(td)
        s = pool.add(category="fix", title="Old problem", explanation="test",
                      frame="edge", confidence=0.6)

        # Manually age it past 14 days
        items = pool._load()
        items[0].created_at = time.time() - (15 * 86400)
        pool._save(items)

        result = pool.sweep()
        assert result["deprecated"] == 1
        assert len(pool.fixes()) == 0


def test_pool_as_signal_feedback():
    with tempfile.TemporaryDirectory() as td:
        pool = SuggestionPool(td)
        pool.add(category="fix", title="Problem A", explanation="a",
                 frame="inversion", confidence=0.9)
        pool.add(category="upgrade", title="Improvement B", explanation="b",
                 frame="removal", confidence=0.7)

        signal = pool.as_signal()
        assert signal["pool_size"] == 2
        assert len(signal["fixes"]) == 1
        assert len(signal["upgrades"]) == 1


def test_pool_stats():
    with tempfile.TemporaryDirectory() as td:
        pool = SuggestionPool(td)
        pool.add(category="fix", title="F1", explanation="", frame="edge", confidence=0.8)
        pool.add(category="upgrade", title="U1", explanation="", frame="removal", confidence=0.7)
        pool.add(category="patch", title="P1", explanation="", frame="analogy", confidence=0.6)

        stats = pool.stats()
        assert stats["open"] == 3
        assert stats["by_category"]["fix"] == 1
        assert stats["by_category"]["upgrade"] == 1
        assert stats["by_category"]["patch"] == 1


def test_pool_report():
    with tempfile.TemporaryDirectory() as td:
        pool = SuggestionPool(td)
        pool.add(category="fix", title="Critical thing", explanation="bad",
                 frame="inversion", confidence=0.95, command="fix.sh")

        report = pool.report()
        assert "Critical thing" in report
        assert "fix.sh" in report


def test_suggestion_lifecycle():
    s = Suggestion(
        id="sg-test",
        category="fix",
        title="Test",
        explanation="test",
        frame="edge",
        confidence=0.8,
        blast_radius="medium",
        created_at=time.time() - (10 * 86400),
    )
    assert s.age_days() > 9
    assert not s.is_stale()  # fix threshold is 14 days

    s.created_at = time.time() - (15 * 86400)
    assert s.is_stale()  # now past threshold


# ── Categories ────────────────────────────────────────────────────────

def test_lint_category_finds_broken_json():
    with tempfile.TemporaryDirectory() as td:
        (Path(td) / "good.json").write_text('{"valid": true}')
        (Path(td) / "bad.json").write_text('{broken json')

        cat = LintCategory([td])
        result = cat.collect()
        assert result.changed
        assert result.data["by_type"].get("json_syntax", 0) >= 1


def test_lint_category_finds_todo_markers():
    with tempfile.TemporaryDirectory() as td:
        (Path(td) / "code.py").write_text("# TODO: fix this\nx = 1\n# FIXME: broken\n")

        cat = LintCategory([td])
        result = cat.collect()
        assert result.data["by_type"].get("marker", 0) >= 2


def test_lint_category_finds_syntax_errors():
    with tempfile.TemporaryDirectory() as td:
        (Path(td) / "broken.py").write_text("def foo(\n  pass\n")

        cat = LintCategory([td])
        result = cat.collect()
        assert result.data["by_type"].get("python_syntax", 0) >= 1


def test_log_category_extracts_questions():
    with tempfile.TemporaryDirectory() as td:
        log_file = Path(td) / "test.log"
        log_file.write_text("2026-02-19 ERROR: connection refused to port 18789\n")

        cat = LogCategory(log_files=[str(log_file)])
        result = cat.collect()
        assert result.data["error_count"] >= 1
        assert len(result.data["questions_from_logs"]) >= 1
        assert any("running" in q.lower() for q in result.data["questions_from_logs"])


def test_active_work_category():
    # Test against a known git repo (this repo)
    repo = str(Path(__file__).parent.parent.parent)
    if not (Path(repo) / ".git").exists():
        return  # skip if not in a git repo

    cat = ActiveWorkCategory(repo)
    result = cat.collect()
    assert "branch" in result.data


def test_drift_category_detects_changes():
    with tempfile.TemporaryDirectory() as td:
        config = Path(td) / "config.json"
        snapshot = Path(td) / "snapshot.json"

        # First beat: create baseline
        config.write_text('{"version": 1}')
        cat = DriftCategory([str(config)], str(snapshot))
        r1 = cat.collect()
        assert r1.data["drift_count"] == 1  # new file

        # Second beat: no change
        r2 = cat.collect()
        assert r2.data["drift_count"] == 0

        # Third beat: config changed
        config.write_text('{"version": 2}')
        r3 = cat.collect()
        assert r3.data["drift_count"] == 1
        assert r3.data["changes_since_last_beat"][0]["change"] == "modified"


def test_resource_category_runs():
    cat = ResourceCategory()
    result = cat.collect()
    # Should at least have the data dict
    assert isinstance(result.data, dict)


# ── Heartbeat ─────────────────────────────────────────────────────────

def test_heartbeat_single_beat():
    with tempfile.TemporaryDirectory() as td:
        config = HeartbeatConfig(
            beat_interval=1,
            report_interval=1,
            lint_paths=[td],
            repo_path=td,
        )
        hb = Heartbeat(config=config, data_dir=td)

        # Create a file to lint
        (Path(td) / "test.json").write_text('{"ok": true}')

        result = hb.beat()
        assert result.frame_used in [f.name for f in __import__("fixit.frames", fromlist=["FRAMES"]).FRAMES]
        assert result.duration_ms >= 0
        assert isinstance(result.pool_size, int)


def test_heartbeat_rotates_frames():
    with tempfile.TemporaryDirectory() as td:
        config = HeartbeatConfig(beat_interval=1, report_interval=99999)
        hb = Heartbeat(config=config, data_dir=td)

        frames_used = []
        for _ in range(6):
            result = hb.beat()
            frames_used.append(result.frame_used)

        # Should have used all 6 different frames
        assert len(set(frames_used)) == 6


def test_heartbeat_generates_report():
    with tempfile.TemporaryDirectory() as td:
        config = HeartbeatConfig(
            beat_interval=1,
            report_interval=0,  # always generate report
            report_path=str(Path(td) / "report.txt"),
        )
        hb = Heartbeat(config=config, data_dir=td)

        result = hb.beat()
        assert result.report_generated

        report_file = Path(td) / "report.txt"
        assert report_file.exists()


def test_heartbeat_state_persists():
    with tempfile.TemporaryDirectory() as td:
        config = HeartbeatConfig(beat_interval=1)

        # First heartbeat
        hb1 = Heartbeat(config=config, data_dir=td)
        hb1.beat()
        hb1.beat()
        idx_after = hb1._frame_index

        # Second heartbeat (new instance, same data dir)
        hb2 = Heartbeat(config=config, data_dir=td)
        assert hb2._frame_index == idx_after  # continued from where we left off


def test_heartbeat_config_from_file():
    with tempfile.TemporaryDirectory() as td:
        config_file = Path(td) / "config.json"
        config_file.write_text(json.dumps({
            "beat_interval": 60,
            "report_interval": 3600,
            "lint_paths": ["/tmp"],
            "plugin": "openbot",
        }))

        config = HeartbeatConfig.from_file(str(config_file))
        assert config.beat_interval == 60
        assert config.plugin == "openbot"


# ── Categorization ────────────────────────────────────────────────────

def test_categorize_high_blast_high_confidence_is_fix():
    rx = Prescription(
        frame="inversion", title="t", explanation="e",
        confidence=0.9, blast_radius="high",
    )
    assert _categorize_prescription(rx) == "fix"


def test_categorize_removal_frame_is_upgrade():
    rx = Prescription(
        frame="removal", title="t", explanation="e",
        confidence=0.7, blast_radius="low",
    )
    assert _categorize_prescription(rx) == "upgrade"


def test_categorize_default_is_patch():
    rx = Prescription(
        frame="edge", title="t", explanation="e",
        confidence=0.7, blast_radius="medium",
    )
    assert _categorize_prescription(rx) == "patch"
