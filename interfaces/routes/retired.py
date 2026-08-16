"""Quarantine tombstones for runtimes that were removed, not merely disconnected.

Every route here answers 410 Gone. They are deliberate and load-bearing: the
production drift audit reads them back from /health/inventory, and
test_runtime_subtraction asserts the exact (method, path) -> endpoint map, which
is what proves the cloud-agent and Hub-chat runtimes were subtracted rather than
left dormant behind a feature flag.

Do not delete or repurpose these paths. See ops/policies/quarantine.json.
"""
from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse

router = APIRouter()


@router.post("/telegram-webhook")
@router.post("/internal/process-update")
@router.post("/internal/process-occasion")
@router.post("/cron/proactive-alerts")
@router.post("/cron/reflect")
@router.post("/cron/autonomous-tick")
@router.post("/cron/ingest-chats")
@router.post("/cron/ingest-chat-exports")
async def retired_cloud_agent_runtime() -> JSONResponse:
    """Quarantine removed Cloud-hosted conversation and reasoning routes."""
    return JSONResponse(
        status_code=410,
        content={"detail": {"error": "Cloud agent runtime retired; use Claude"}},
    )


@router.post("/internal/process-hub-message")
@router.post("/api/chat")
@router.post("/api/chat/upload")
@router.get("/api/chat/messages")
@router.post("/api/chat/regenerate")
@router.post("/api/chat/stop")
async def retired_hub_chat_runtime() -> JSONResponse:
    """Quarantine removed Hub chat and attachment routes."""
    return JSONResponse(
        status_code=410,
        content={"detail": {"error": "Hub chat retired; use the configured Claude Project"}},
    )
