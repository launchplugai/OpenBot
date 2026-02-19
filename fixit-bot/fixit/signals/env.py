"""Environment variable signal — observe what's in the env."""

from __future__ import annotations

import os
from fnmatch import fnmatch
from typing import Any

from fixit.signals.base import Signal


class EnvVarsSignal(Signal):
    """Watch environment variables for keys, leaks, and misconfigs."""

    name = "env"

    def __init__(self, watch: list[str] | None = None):
        self.watch = watch or ["*_API_KEY", "*_SECRET", "*_TOKEN", "*_KEY"]

    def collect(self) -> dict[str, Any]:
        matched = {}
        for key, val in os.environ.items():
            if any(fnmatch(key, pat) for pat in self.watch):
                # Mask the value — never expose secrets in signals
                if len(val) > 8:
                    masked = f"{val[:4]}...{val[-4:]}"
                else:
                    masked = "***"
                matched[key] = {
                    "masked_value": masked,
                    "length": len(val),
                    "looks_like_key": val.startswith(("sk-", "pk-", "key-", "token-")),
                }

        return {
            "total_env_vars": len(os.environ),
            "matched_sensitive": len(matched),
            "vars": matched,
            "watch_patterns": self.watch,
        }

    def describe(self) -> str:
        return f"Environment variables (patterns: {self.watch})"
