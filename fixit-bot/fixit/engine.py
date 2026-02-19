"""The Crow Engine — lateral thinking diagnostics with learning.

This is the brain. <500 lines. Intelligence is in the prompts
and the training data, not the plumbing.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Optional

from fixit.frames import FRAMES, Frame
from fixit.memory import CorvidCache, TrainingSample
from fixit.prescription import Prescription
from fixit.signals.base import Signal


# Default data directory
DEFAULT_DATA_DIR = os.path.expanduser("~/.fixit")


class Crow:
    """The fixit.bot engine. Scans signals through reasoning frames.

    Starts with Haiku as teacher. Collects training data.
    Eventually graduates to its own model.

    Usage:
        crow = Crow("/path/to/system")
        crow.add_signal(FileSystemSignal("/etc/", watch=["*.conf"]))
        prescriptions = crow.scan()
    """

    def __init__(
        self,
        target: str = ".",
        data_dir: str | None = None,
        api_key: str | None = None,
        model: str = "claude-haiku-4-5-20251001",
    ):
        self.target = Path(target)
        self.data_dir = Path(data_dir or DEFAULT_DATA_DIR)
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
        self.model = model
        self.signals: list[Signal] = []
        self.context_hints: list[str] = []
        self.cache = CorvidCache(self.data_dir / "training")

    def add_signal(self, signal: Signal) -> Crow:
        """Add a signal source for the crow to observe."""
        self.signals.append(signal)
        return self

    def add_context(self, hint: str) -> Crow:
        """Add domain knowledge the crow should consider."""
        self.context_hints.append(hint)
        return self

    def load_plugin(self, name: str) -> Crow:
        """Load a named plugin (registers its signals and context)."""
        from fixit.plugins import load_plugin
        plugin = load_plugin(name)
        for sig in plugin.signals():
            self.add_signal(sig)
        for hint in plugin.context():
            self.add_context(hint.text)
        return self

    def scan(
        self,
        frames: list[str] | None = None,
        save: bool = True,
    ) -> list[Prescription]:
        """Run a full scan: collect signals, apply frames, return prescriptions.

        Args:
            frames: List of frame names to run. None = all six.
            save: Whether to save the scan as a training sample.

        Returns:
            List of Prescription objects, sorted by confidence descending.
        """
        # 1. Collect all signals
        signal_data = self._collect_signals()

        # 2. Pick frames
        active_frames = FRAMES
        if frames:
            active_frames = [f for f in FRAMES if f.name in frames]

        # 3. Run each frame
        all_prescriptions: list[Prescription] = []
        for frame in active_frames:
            try:
                rxs = self._run_frame(frame, signal_data)
                all_prescriptions.extend(rxs)
            except Exception as e:
                # Frame failure shouldn't kill the whole scan
                all_prescriptions.append(Prescription(
                    frame=frame.name,
                    title=f"Frame {frame.name} failed: {type(e).__name__}",
                    explanation=str(e),
                    confidence=0.0,
                    blast_radius="low",
                    tags=["internal_error"],
                ))

        # 4. Sort by confidence
        all_prescriptions.sort(key=lambda rx: -rx.confidence)

        # 5. Save as training sample
        if save:
            self.cache.store(
                signals=signal_data,
                prescriptions=[rx.to_dict() for rx in all_prescriptions],
            )

        return all_prescriptions

    def label(self, sample_id: str, verdict: str) -> TrainingSample:
        """Label a training sample with operator feedback.

        Verdicts: good_find, noise, critical, wrong_frame
        """
        return self.cache.label(sample_id, verdict)

    def status(self) -> dict[str, Any]:
        """Get the crow's current development status."""
        stats = self.cache.stats()
        stats["model"] = self.model
        stats["target"] = str(self.target)
        stats["signal_count"] = len(self.signals)
        stats["context_hints"] = len(self.context_hints)
        return stats

    def _collect_signals(self) -> dict[str, Any]:
        """Collect state from all registered signals."""
        data: dict[str, Any] = {
            "timestamp": time.time(),
            "target": str(self.target),
        }

        for signal in self.signals:
            try:
                data[signal.name] = signal.collect()
            except Exception as e:
                data[signal.name] = {"error": str(e)}

        return data

    def _run_frame(self, frame: Frame, signals: dict[str, Any]) -> list[Prescription]:
        """Run a single reasoning frame against signals via Haiku."""

        # Build the user message with signals + context
        context_block = ""
        if self.context_hints:
            hints = "\n".join(f"- {h}" for h in self.context_hints)
            context_block = f"\n\nDomain knowledge:\n{hints}"

        user_msg = f"System signals:\n```json\n{json.dumps(signals, indent=2, default=str)}\n```{context_block}"

        # Call Haiku
        response_text = self._call_haiku(frame.prompt, user_msg)

        # Parse response into prescriptions
        return self._parse_prescriptions(frame.name, response_text)

    def _call_haiku(self, system_prompt: str, user_message: str) -> str:
        """Call Haiku via the Anthropic API. Minimal, no dependencies beyond stdlib."""

        if not self.api_key:
            # No API key — return empty (the crow is blind until it gets eyes)
            return "[]"

        try:
            import anthropic
            client = anthropic.Anthropic(api_key=self.api_key)
            response = client.messages.create(
                model=self.model,
                max_tokens=2048,
                system=system_prompt,
                messages=[{"role": "user", "content": user_message}],
            )
            return response.content[0].text
        except ImportError:
            # Fallback: raw HTTP (no anthropic SDK)
            return self._call_haiku_raw(system_prompt, user_message)
        except Exception as e:
            return json.dumps([{
                "title": f"API error: {type(e).__name__}",
                "explanation": str(e),
                "confidence": 0.0,
                "blast_radius": "low",
                "reversible": True,
                "command": None,
                "tags": ["api_error"],
            }])

    def _call_haiku_raw(self, system_prompt: str, user_message: str) -> str:
        """Fallback: call Anthropic API with just urllib (zero dependencies)."""
        import urllib.request

        body = json.dumps({
            "model": self.model,
            "max_tokens": 2048,
            "system": system_prompt,
            "messages": [{"role": "user", "content": user_message}],
        })

        req = urllib.request.Request(
            "https://api.anthropic.com/v1/messages",
            data=body.encode(),
            headers={
                "Content-Type": "application/json",
                "x-api-key": self.api_key,
                "anthropic-version": "2023-06-01",
            },
        )

        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read())
                return data["content"][0]["text"]
        except Exception:
            return "[]"

    def _parse_prescriptions(self, frame_name: str, response: str) -> list[Prescription]:
        """Parse Haiku's JSON response into Prescription objects."""

        # Extract JSON array from response (may be wrapped in markdown)
        text = response.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            text = "\n".join(lines[1:-1])  # strip ```json and ```

        try:
            findings = json.loads(text)
        except json.JSONDecodeError:
            # Try to find JSON array in the response
            start = text.find("[")
            end = text.rfind("]") + 1
            if start >= 0 and end > start:
                try:
                    findings = json.loads(text[start:end])
                except json.JSONDecodeError:
                    return []
            else:
                return []

        prescriptions = []
        for finding in findings:
            if not isinstance(finding, dict):
                continue
            try:
                rx = Prescription(
                    frame=frame_name,
                    title=finding.get("title", "Untitled"),
                    explanation=finding.get("explanation", ""),
                    confidence=float(finding.get("confidence", 0.5)),
                    blast_radius=finding.get("blast_radius", "low"),
                    reversible=finding.get("reversible", True),
                    command=finding.get("command"),
                    tags=finding.get("tags", []),
                )
                if rx.confidence >= 0.5:
                    prescriptions.append(rx)
            except (TypeError, ValueError):
                continue

        return prescriptions
