"""Corvid Cache — the crow's long-term memory and training data store.

Every scan produces a training sample. Operators label them.
The spacer schedules reviews. The trainer learns from them.
All of it lives here, in flat JSON files. Simple is the game.
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Optional


@dataclass
class TrainingSample:
    """One scan + its prescriptions + operator labels."""

    id: str
    timestamp: float
    signals: dict[str, Any]
    prescriptions: list[dict]
    label: Optional[str] = None          # good_find | noise | critical | wrong_frame
    label_timestamp: Optional[float] = None
    leitner_box: int = 1                 # 1-5 (spaced repetition)
    review_count: int = 0
    next_review_after: Optional[float] = None

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> TrainingSample:
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


class CorvidCache:
    """Persistent storage for training data. Flat JSON files."""

    def __init__(self, data_dir: str | Path):
        self.data_dir = Path(data_dir)
        self.samples_dir = self.data_dir / "samples"
        self.index_path = self.data_dir / "index.json"
        self.stats_path = self.data_dir / "stats.json"

        # Ensure dirs exist
        self.samples_dir.mkdir(parents=True, exist_ok=True)

    def store(self, signals: dict[str, Any], prescriptions: list[dict]) -> TrainingSample:
        """Store a new scan result as a training sample."""
        sample = TrainingSample(
            id=f"scan-{uuid.uuid4().hex[:12]}",
            timestamp=time.time(),
            signals=signals,
            prescriptions=prescriptions,
        )

        path = self.samples_dir / f"{sample.id}.json"
        path.write_text(json.dumps(sample.to_dict(), indent=2))

        self._update_index(sample)
        return sample

    def label(self, sample_id: str, verdict: str) -> TrainingSample:
        """Label a training sample with operator feedback."""
        sample = self.load(sample_id)
        sample.label = verdict
        sample.label_timestamp = time.time()
        sample.review_count += 1

        # Leitner box movement
        if verdict in ("good_find", "critical"):
            # Correct — promote to next box (less frequent review)
            sample.leitner_box = min(5, sample.leitner_box + 1)
        elif verdict == "noise":
            # Wrong — demote to box 1 (frequent review)
            sample.leitner_box = 1
        elif verdict == "wrong_frame":
            # Partially right — stay in current box
            pass

        # Schedule next review based on box
        intervals = {1: 0, 2: 3, 3: 10, 4: 50, 5: None}  # in scan-counts
        interval = intervals.get(sample.leitner_box, 0)
        if interval is not None:
            sample.next_review_after = time.time() + (interval * 300)  # ~5min per scan
        else:
            sample.next_review_after = None  # mastered — only on regression

        path = self.samples_dir / f"{sample.id}.json"
        path.write_text(json.dumps(sample.to_dict(), indent=2))

        self._update_index(sample)
        return sample

    def load(self, sample_id: str) -> TrainingSample:
        """Load a single training sample by ID."""
        path = self.samples_dir / f"{sample_id}.json"
        if not path.exists():
            raise FileNotFoundError(f"Sample {sample_id} not found")
        data = json.loads(path.read_text())
        return TrainingSample.from_dict(data)

    def unlabeled(self, limit: int = 10) -> list[TrainingSample]:
        """Get samples that haven't been labeled yet."""
        return self._query(lambda s: s.label is None, limit)

    def due_for_review(self, limit: int = 10) -> list[TrainingSample]:
        """Get samples due for spaced repetition review."""
        now = time.time()
        return self._query(
            lambda s: (
                s.label is not None
                and s.next_review_after is not None
                and s.next_review_after <= now
            ),
            limit,
        )

    def labeled_pairs(self) -> list[TrainingSample]:
        """Get all labeled samples (for training)."""
        return self._query(lambda s: s.label is not None, limit=0)

    def stats(self) -> dict[str, Any]:
        """Summary statistics for the crow's development."""
        index = self._load_index()
        samples = index.get("samples", {})

        total = len(samples)
        labeled = sum(1 for s in samples.values() if s.get("label"))
        by_label = {}
        by_box = {1: 0, 2: 0, 3: 0, 4: 0, 5: 0}

        for s in samples.values():
            if s.get("label"):
                by_label[s["label"]] = by_label.get(s["label"], 0) + 1
            box = s.get("leitner_box", 1)
            by_box[box] = by_box.get(box, 0) + 1

        # Calculate stage
        if labeled >= 5000:
            stage = 4
            stage_name = "Quantized local model"
        elif labeled >= 2000:
            stage = 3
            stage_name = "Full fine-tune"
        elif labeled >= 500:
            stage = 2
            stage_name = "LoRA adapter"
        elif labeled >= 100:
            stage = 1
            stage_name = "Few-shot prompting"
        else:
            stage = 0
            stage_name = "Imprinting (collecting data)"

        # Accuracy (if enough labels)
        good = by_label.get("good_find", 0) + by_label.get("critical", 0)
        fp_rate = by_label.get("noise", 0) / labeled if labeled > 0 else 0
        accuracy = good / labeled if labeled > 0 else 0

        return {
            "total_scans": total,
            "labeled": labeled,
            "unlabeled": total - labeled,
            "by_label": by_label,
            "leitner_boxes": by_box,
            "stage": stage,
            "stage_name": stage_name,
            "next_stage_at": [100, 500, 2000, 5000, None][min(stage, 4)],
            "accuracy": round(accuracy, 3),
            "false_positive_rate": round(fp_rate, 3),
        }

    def _query(self, predicate, limit: int) -> list[TrainingSample]:
        """Query samples by predicate."""
        results = []
        for path in sorted(self.samples_dir.glob("scan-*.json")):
            try:
                data = json.loads(path.read_text())
                sample = TrainingSample.from_dict(data)
                if predicate(sample):
                    results.append(sample)
                    if limit and len(results) >= limit:
                        break
            except (json.JSONDecodeError, KeyError):
                continue
        return results

    def _load_index(self) -> dict:
        """Load the index file."""
        if self.index_path.exists():
            try:
                return json.loads(self.index_path.read_text())
            except json.JSONDecodeError:
                pass
        return {"samples": {}}

    def _update_index(self, sample: TrainingSample) -> None:
        """Update the index with a sample's metadata."""
        index = self._load_index()
        index["samples"][sample.id] = {
            "timestamp": sample.timestamp,
            "label": sample.label,
            "leitner_box": sample.leitner_box,
            "review_count": sample.review_count,
        }
        index["last_updated"] = time.time()
        self.index_path.write_text(json.dumps(index, indent=2))
