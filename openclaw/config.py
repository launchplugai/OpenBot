"""Configuration loader for OpenClaw gateway."""

import os
from pathlib import Path

import yaml


DEFAULT_CONFIG_PATH = "/data/.openclaw/config.yaml"
FALLBACK_CONFIG_PATH = os.path.join(
    os.path.dirname(__file__), "..", "vps-setup", "openclaw-config.yaml"
)


def load_config(path: str | None = None) -> dict:
    """Load gateway config from YAML. Falls back to defaults if missing."""
    candidates = [
        path,
        os.environ.get("OPENCLAW_CONFIG"),
        DEFAULT_CONFIG_PATH,
        FALLBACK_CONFIG_PATH,
    ]
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            with open(candidate) as f:
                return yaml.safe_load(f)

    # Minimal default config
    return {
        "gateway": {"host": "0.0.0.0", "port": 18789},
        "agents": {
            "ralph": {
                "role": "repository-auditor",
                "description": "Clones and tests target repos via openbot run",
                "command": "openbot run",
            },
            "ira": {
                "role": "infrastructure-monitor",
                "description": "Health checks and system status via openbot doctor",
                "command": "openbot doctor",
            },
            "tess": {
                "role": "test-analyst",
                "description": "Parses receipts and identifies regressions",
                "command": "receipt-analysis",
            },
        },
        "services": {
            "dna-matrix": {"url": "http://localhost:8000", "health": "/health"},
            "openbot": {
                "cli": "/usr/local/bin/openbot",
                "config": "/etc/openbot/config.yaml",
            },
        },
    }
