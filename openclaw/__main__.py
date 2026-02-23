"""Entry point: python -m openclaw"""

import os
import sys

import uvicorn

from openclaw.config import load_config


def main():
    config = load_config(os.environ.get("OPENCLAW_CONFIG"))
    gw = config.get("gateway", {})
    host = gw.get("host", "0.0.0.0")
    port = int(gw.get("port", 18789))

    print(f"OpenClaw gateway starting on {host}:{port}")
    uvicorn.run(
        "openclaw.app:app",
        host=host,
        port=port,
        log_level="info",
    )


if __name__ == "__main__":
    main()
