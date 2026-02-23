"""OpenClaw Gateway — Agent coordination server for OpenBot.

Runs on port 18789 by default. Provides:
  GET  /status          — gateway health and uptime
  GET  /agents          — list configured agents
  GET  /agents/{name}   — agent detail
  POST /agents/{name}/run — dispatch an agent
  GET  /runs            — recent run history
  GET  /runs/{id}       — single run detail
  GET  /services        — upstream service health
  GET  /services/{name} — single service health
"""

import datetime
import os

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse

from openclaw import __version__
from openclaw.agents import AgentCoordinator
from openclaw.config import load_config
from openclaw.services import ServiceChecker

# ---------------------------------------------------------------------------
# Boot
# ---------------------------------------------------------------------------

config = load_config(os.environ.get("OPENCLAW_CONFIG"))
gateway_cfg = config.get("gateway", {})

app = FastAPI(
    title="OpenClaw Gateway",
    version=__version__,
    docs_url="/docs",
    redoc_url=None,
)

coordinator = AgentCoordinator(config.get("agents", {}))
service_checker = ServiceChecker(config.get("services", {}))

_started_at = datetime.datetime.utcnow().isoformat() + "Z"


# ---------------------------------------------------------------------------
# Status
# ---------------------------------------------------------------------------

@app.get("/status")
async def status():
    """Gateway health check — always returns 200 if the process is alive."""
    return {
        "status": "ok",
        "version": __version__,
        "started_at": _started_at,
        "gateway": {
            "host": gateway_cfg.get("host", "0.0.0.0"),
            "port": gateway_cfg.get("port", 18789),
        },
        "agents_configured": len(coordinator.agents),
        "total_runs": len(coordinator.history),
    }


@app.get("/health")
async def health():
    """Alias for /status (compatibility)."""
    return await status()


# ---------------------------------------------------------------------------
# Agents
# ---------------------------------------------------------------------------

@app.get("/agents")
async def list_agents():
    return {"agents": coordinator.list_agents()}


@app.get("/agents/{name}")
async def get_agent(name: str):
    agent = coordinator.get_agent(name)
    if not agent:
        raise HTTPException(status_code=404, detail=f"Agent '{name}' not found")
    return agent


@app.post("/agents/{name}/run")
async def run_agent(name: str, args: list[str] | None = None):
    """Dispatch an agent. Optionally pass extra CLI args."""
    try:
        run = await coordinator.dispatch(name, args)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return run.to_dict()


# ---------------------------------------------------------------------------
# Runs
# ---------------------------------------------------------------------------

@app.get("/runs")
async def list_runs(limit: int = 20):
    return {"runs": coordinator.recent_runs(limit)}


@app.get("/runs/{run_id}")
async def get_run(run_id: str):
    run = coordinator.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found")
    return run.to_dict()


# ---------------------------------------------------------------------------
# Services
# ---------------------------------------------------------------------------

@app.get("/services")
async def list_services():
    results = await service_checker.check_all()
    return {"services": results}


@app.get("/services/{name}")
async def get_service(name: str):
    result = await service_checker.check_one(name)
    if result.get("status") == "unknown":
        raise HTTPException(status_code=404, detail=result.get("error"))
    return result


# ---------------------------------------------------------------------------
# Error handlers
# ---------------------------------------------------------------------------

@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    return JSONResponse(
        status_code=500,
        content={"error": "internal_error", "detail": str(exc)},
    )
