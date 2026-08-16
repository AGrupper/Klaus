"""Liveness and capability reporting.

`/health` must stay dependency-free: Cloud Run uses it as the startup probe, so
anything it touches becomes something that can stop a revision going live.
`/health/inventory` is the opposite — it reports what this running revision
actually has, and the production drift audit reads it.
"""
from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse

router = APIRouter()


@router.get("/health")
async def health_check() -> JSONResponse:
    """Liveness and startup probe used by Cloud Run.

    Returns ``{"status": "ok"}`` with HTTP 200 immediately, with no
    authentication and no dependency on the orchestrator.  Cloud Run will
    stop sending traffic to an instance that fails this check.

    Returns:
        JSONResponse: ``{"status": "ok"}`` with HTTP status 200.
    """
    return JSONResponse(content={"status": "ok"})


@router.get("/health/inventory")
async def health_inventory() -> JSONResponse:
    """Expose non-sensitive live capability metadata for drift audits."""
    # Lazy: the composition root imports this module, so a top-level
    # import back into it would be a cycle.
    from interfaces.web_server import _runtime_inventory

    return JSONResponse(content={"status": "ok", **_runtime_inventory()})
