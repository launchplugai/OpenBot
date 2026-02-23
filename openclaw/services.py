"""Service health checks for upstream dependencies."""

import asyncio
import datetime

import httpx


class ServiceChecker:
    """Checks health of configured services (DNA Matrix, etc.)."""

    def __init__(self, service_defs: dict):
        self.services = service_defs
        self._cache: dict[str, dict] = {}
        self._cache_ttl = 10  # seconds

    async def check_all(self) -> dict[str, dict]:
        tasks = {}
        for name, spec in self.services.items():
            url = spec.get("url")
            health = spec.get("health")
            if url and health:
                tasks[name] = self._check_http(name, url + health)
            else:
                # CLI-only service, check binary
                cli = spec.get("cli", "")
                tasks[name] = self._check_cli(name, cli)

        results = {}
        gathered = await asyncio.gather(
            *tasks.values(), return_exceptions=True
        )
        for name, result in zip(tasks.keys(), gathered):
            if isinstance(result, Exception):
                results[name] = {
                    "status": "error",
                    "error": str(result),
                    "checked_at": datetime.datetime.utcnow().isoformat() + "Z",
                }
            else:
                results[name] = result
        return results

    async def check_one(self, name: str) -> dict:
        spec = self.services.get(name)
        if not spec:
            return {"status": "unknown", "error": f"No service named '{name}'"}

        url = spec.get("url")
        health = spec.get("health")
        if url and health:
            return await self._check_http(name, url + health)
        cli = spec.get("cli", "")
        return await self._check_cli(name, cli)

    async def _check_http(self, name: str, url: str) -> dict:
        now = datetime.datetime.utcnow().isoformat() + "Z"
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(url)
                return {
                    "status": "healthy" if resp.status_code == 200 else "degraded",
                    "http_status": resp.status_code,
                    "url": url,
                    "checked_at": now,
                }
        except httpx.ConnectError:
            return {"status": "down", "url": url, "error": "connection refused", "checked_at": now}
        except httpx.TimeoutException:
            return {"status": "down", "url": url, "error": "timeout", "checked_at": now}
        except Exception as exc:
            return {"status": "error", "url": url, "error": str(exc), "checked_at": now}

    @staticmethod
    async def _check_cli(name: str, cli_path: str) -> dict:
        import shutil

        now = datetime.datetime.utcnow().isoformat() + "Z"
        binary = cli_path.split()[0] if cli_path else ""
        found = shutil.which(binary) is not None
        return {
            "status": "available" if found else "not_found",
            "binary": binary,
            "checked_at": now,
        }
