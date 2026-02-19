"""Signal adapters — eyes and ears for the crow."""

from fixit.signals.base import Signal
from fixit.signals.filesystem import FileSystemSignal
from fixit.signals.process import ProcessSignal
from fixit.signals.env import EnvVarsSignal
from fixit.signals.http import HttpSignal
from fixit.signals.git import GitSignal

__all__ = [
    "Signal",
    "FileSystemSignal",
    "ProcessSignal",
    "EnvVarsSignal",
    "HttpSignal",
    "GitSignal",
]
