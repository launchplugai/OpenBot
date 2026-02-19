"""Prescription — a single actionable finding from a scan."""

from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from typing import Optional


@dataclass
class Prescription:
    """One thing the crow noticed, and what to do about it."""

    frame: str                          # which reasoning frame found this
    title: str                          # one-line summary
    explanation: str                    # why this is weird
    confidence: float                   # 0.0–1.0
    blast_radius: str = "low"           # low | medium | high
    reversible: bool = True             # can we undo the fix?
    command: Optional[str] = None       # suggested fix (shell command)
    tags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2)

    @classmethod
    def from_dict(cls, d: dict) -> Prescription:
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})

    def severity(self) -> str:
        """Human-readable severity from confidence + blast."""
        if self.confidence >= 0.85 and self.blast_radius == "high":
            return "critical"
        if self.confidence >= 0.7:
            return "warning"
        return "info"

    def __str__(self) -> str:
        icon = {"critical": "!!", "warning": "!", "info": "."}[self.severity()]
        rev = "yes" if self.reversible else "NO"
        lines = [
            f"[{self.confidence:.0%}] {self.frame.upper()}: {self.title}",
            f"  {self.explanation}",
            f"  Blast: {self.blast_radius} | Reversible: {rev}",
        ]
        if self.command:
            lines.append(f"  Fix: {self.command}")
        return "\n".join(lines)
