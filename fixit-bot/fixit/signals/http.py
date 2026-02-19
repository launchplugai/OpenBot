"""HTTP signal — probe an endpoint for health."""

from __future__ import annotations

import time
import urllib.request
import urllib.error
from typing import Any

from fixit.signals.base import Signal


class HttpSignal(Signal):
    """Probe an HTTP endpoint and report latency, status, body preview."""

    name = "http"

    def __init__(self, url: str, timeout: int = 10):
        self.url = url
        self.timeout = timeout

    def collect(self) -> dict[str, Any]:
        result: dict[str, Any] = {"url": self.url}

        start = time.monotonic()
        try:
            req = urllib.request.Request(self.url, method="GET")
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                elapsed_ms = round((time.monotonic() - start) * 1000)
                body = resp.read(1024).decode("utf-8", errors="replace")
                result["status"] = resp.status
                result["latency_ms"] = elapsed_ms
                result["body_preview"] = body[:200]
                result["headers"] = dict(resp.headers)
                result["reachable"] = True
        except urllib.error.HTTPError as e:
            elapsed_ms = round((time.monotonic() - start) * 1000)
            result["status"] = e.code
            result["latency_ms"] = elapsed_ms
            result["reachable"] = True
            result["error"] = str(e)
        except (urllib.error.URLError, OSError, TimeoutError) as e:
            elapsed_ms = round((time.monotonic() - start) * 1000)
            result["reachable"] = False
            result["latency_ms"] = elapsed_ms
            result["error"] = str(e)

        return result

    def describe(self) -> str:
        return f"HTTP endpoint: {self.url}"
