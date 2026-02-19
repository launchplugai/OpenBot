"""Base signal class — all signal adapters inherit from this."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class Signal(ABC):
    """A source of system state that the crow can observe."""

    name: str = "base"

    @abstractmethod
    def collect(self) -> dict[str, Any]:
        """Collect current signal state. Returns a dict of observations."""
        ...

    def describe(self) -> str:
        """Human-readable description of what this signal observes."""
        return f"{self.name} signal"
