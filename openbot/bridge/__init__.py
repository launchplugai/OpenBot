"""
OpenBot Bridge - OpenClaw-compatible agent loop interface.

Provides a strict, allowlisted interface for external orchestration
tools to interact with OpenBot safely.

All outputs are JSON-only with sanitized content and size caps.
"""

__version__ = "0.1.0"

from .hooks import ALLOWLIST, sanitize_output, cap_size
from .tool import BridgeTool
from .triage import local_triage

__all__ = [
    "ALLOWLIST",
    "sanitize_output",
    "cap_size",
    "BridgeTool",
    "local_triage",
]

