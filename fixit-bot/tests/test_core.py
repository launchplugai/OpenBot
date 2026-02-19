"""Core tests for fixit.bot — verify the crow's plumbing works."""

import json
import tempfile
from pathlib import Path

from fixit.engine import Crow
from fixit.frames import FRAMES
from fixit.memory import CorvidCache, TrainingSample
from fixit.prescription import Prescription
from fixit.signals import FileSystemSignal, EnvVarsSignal, GitSignal


def test_prescription_creation():
    rx = Prescription(
        frame="inversion",
        title="Test finding",
        explanation="This is a test",
        confidence=0.85,
        blast_radius="medium",
    )
    assert rx.severity() == "warning"
    assert "INVERSION" in str(rx).upper()


def test_prescription_critical():
    rx = Prescription(
        frame="edge",
        title="Critical thing",
        explanation="Very bad",
        confidence=0.9,
        blast_radius="high",
    )
    assert rx.severity() == "critical"


def test_prescription_json_roundtrip():
    rx = Prescription(
        frame="temporal",
        title="Key expires",
        explanation="In 30 days",
        confidence=0.75,
        blast_radius="high",
        reversible=False,
        command="rotate-keys.sh",
        tags=["security"],
    )
    d = rx.to_dict()
    rx2 = Prescription.from_dict(d)
    assert rx2.title == rx.title
    assert rx2.confidence == rx.confidence
    assert rx2.tags == ["security"]


def test_all_frames_exist():
    assert len(FRAMES) == 6
    names = {f.name for f in FRAMES}
    assert names == {"inversion", "constraint", "analogy", "temporal", "removal", "edge"}


def test_frame_prompts_not_empty():
    for frame in FRAMES:
        assert len(frame.prompt) > 100, f"Frame {frame.name} has a short prompt"
        assert "JSON" in frame.prompt, f"Frame {frame.name} doesn't request JSON output"


def test_corvid_cache_store_and_load():
    with tempfile.TemporaryDirectory() as td:
        cache = CorvidCache(td)
        sample = cache.store(
            signals={"test": "data"},
            prescriptions=[{"title": "finding", "confidence": 0.8}],
        )
        assert sample.id.startswith("scan-")
        assert sample.label is None

        loaded = cache.load(sample.id)
        assert loaded.id == sample.id
        assert loaded.signals == {"test": "data"}


def test_corvid_cache_label_promotes():
    with tempfile.TemporaryDirectory() as td:
        cache = CorvidCache(td)
        sample = cache.store(signals={}, prescriptions=[])
        assert sample.leitner_box == 1

        labeled = cache.label(sample.id, "good_find")
        assert labeled.leitner_box == 2
        assert labeled.label == "good_find"


def test_corvid_cache_label_demotes_noise():
    with tempfile.TemporaryDirectory() as td:
        cache = CorvidCache(td)
        sample = cache.store(signals={}, prescriptions=[])

        # Promote first
        cache.label(sample.id, "good_find")  # box 2
        cache.label(sample.id, "good_find")  # box 3

        # Noise demotes to box 1
        demoted = cache.label(sample.id, "noise")
        assert demoted.leitner_box == 1


def test_corvid_cache_unlabeled():
    with tempfile.TemporaryDirectory() as td:
        cache = CorvidCache(td)
        cache.store(signals={"a": 1}, prescriptions=[])
        cache.store(signals={"b": 2}, prescriptions=[])

        unlabeled = cache.unlabeled()
        assert len(unlabeled) == 2


def test_corvid_cache_stats():
    with tempfile.TemporaryDirectory() as td:
        cache = CorvidCache(td)
        s1 = cache.store(signals={}, prescriptions=[])
        s2 = cache.store(signals={}, prescriptions=[])
        cache.label(s1.id, "good_find")

        stats = cache.stats()
        assert stats["total_scans"] == 2
        assert stats["labeled"] == 1
        assert stats["stage"] == 0  # <100 labeled


def test_filesystem_signal_collects():
    with tempfile.TemporaryDirectory() as td:
        # Create a test file
        (Path(td) / "test.json").write_text('{"key": "value"}')

        sig = FileSystemSignal(td, watch=["*.json"])
        data = sig.collect()
        assert data["file_count"] == 1
        assert data["total_bytes"] > 0


def test_env_signal_collects():
    import os
    os.environ["FIXIT_TEST_KEY"] = "test-value-12345"
    try:
        sig = EnvVarsSignal(watch=["FIXIT_TEST_*"])
        data = sig.collect()
        assert data["matched_sensitive"] == 1
        assert "FIXIT_TEST_KEY" in data["vars"]
        # Value should be masked
        assert "12345" not in data["vars"]["FIXIT_TEST_KEY"]["masked_value"] or \
               data["vars"]["FIXIT_TEST_KEY"]["masked_value"].startswith("test")
    finally:
        del os.environ["FIXIT_TEST_KEY"]


def test_crow_scan_no_api_key():
    """Crow should work without an API key (returns empty prescriptions)."""
    with tempfile.TemporaryDirectory() as td:
        crow = Crow(target=td, api_key="", data_dir=td)
        crow.add_signal(FileSystemSignal(td))

        prescriptions = crow.scan()
        # Should complete without error, even with no API key
        assert isinstance(prescriptions, list)


def test_crow_status():
    with tempfile.TemporaryDirectory() as td:
        crow = Crow(target=td, data_dir=td)
        status = crow.status()
        assert "stage" in status
        assert "total_scans" in status
        assert status["stage"] == 0


def test_parse_prescriptions():
    """Test that the engine can parse Haiku-style JSON responses."""
    crow = Crow()
    response = json.dumps([{
        "title": "Test finding",
        "explanation": "Something is weird",
        "confidence": 0.8,
        "blast_radius": "medium",
        "reversible": True,
        "command": "echo fix",
        "tags": ["test"],
    }])

    rxs = crow._parse_prescriptions("inversion", response)
    assert len(rxs) == 1
    assert rxs[0].title == "Test finding"
    assert rxs[0].frame == "inversion"


def test_parse_prescriptions_wrapped_in_markdown():
    """Haiku sometimes wraps JSON in ```json blocks."""
    crow = Crow()
    response = '```json\n[{"title": "Wrapped", "explanation": "test", "confidence": 0.7}]\n```'

    rxs = crow._parse_prescriptions("edge", response)
    assert len(rxs) == 1
    assert rxs[0].title == "Wrapped"


def test_parse_prescriptions_filters_low_confidence():
    crow = Crow()
    response = json.dumps([
        {"title": "High", "explanation": "yes", "confidence": 0.8},
        {"title": "Low", "explanation": "no", "confidence": 0.3},
    ])

    rxs = crow._parse_prescriptions("removal", response)
    assert len(rxs) == 1
    assert rxs[0].title == "High"


def test_plugin_openbot_loads():
    from fixit.plugins import load_plugin
    plugin = load_plugin("openbot")
    assert plugin.name == "openbot"
    assert len(plugin.signals()) > 0
    assert len(plugin.context()) > 0
