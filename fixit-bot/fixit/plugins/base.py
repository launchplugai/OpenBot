"""Plugin base class — the interface for teaching the crow about a stack."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from fixit.signals.base import Signal


@dataclass
class ContextHint:
    """A piece of domain knowledge about the stack."""
    text: str


class Plugin(ABC):
    """Base class for stack-specific plugins."""

    name: str = "base"
    version: str = "0.0.0"

    @abstractmethod
    def signals(self) -> list[Signal]:
        """Return signal sources for this stack."""
        ...

    @abstractmethod
    def context(self) -> list[ContextHint]:
        """Return domain knowledge hints for this stack."""
        ...
