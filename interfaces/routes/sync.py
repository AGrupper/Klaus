"""Device ingestion webhook.

/cron/healthkit-sync is pushed to by an iOS Shortcut carrying Amit's nutrition
samples, so unlike the Cloud Scheduler jobs it authenticates with a shared
secret rather than an OIDC token. Writes are idempotent on (start_date,
food_item) because HealthKit re-sends samples it has already sent.
"""
from __future__ import annotations

import logging
import os

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

from interfaces.routes._verify import _log_cron_run, _verify_healthkit_request

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/cron/healthkit-sync")
async def cron_healthkit_sync(request: Request) -> JSONResponse:
    """Push-driven webhook from the iPhone Shortcut "Lifesum closed" automation.

    Phase 19.1 — HEALTHKIT-04 / HEALTHKIT-05; CONTEXT.md D-09 / D-10.

    Upsert-only and independent of any conversation runtime. The route's only
    sink is ``MealStore.upsert``; Claude reads the data later through MCP.

    Flow:
      1. Verify the shared-secret bearer (or honour CRON_DEV_BYPASS).
      2. Parse the JSON body.
      3. Delegate to mcp_tools.healthkit_tool.ingest_payload — Pydantic
         validation + per-sample normalize + MealStore.upsert with Pattern-C
         per-item try/except.
      4. Record success/failure via _log_cron_run; re-raise on exception so
         Cloud Run sees the 500 and the heartbeat staleness streak ticks up.

    Returns:
        JSONResponse: ``{"upserted": N}`` on HTTP 200.

    Raises:
        HTTPException 401: Missing or malformed Authorization header.
        HTTPException 403: Bad bearer token.
        HTTPException 422: Pydantic ValidationError on the payload body.
        HTTPException 500: HEALTHKIT_WEBHOOK_TOKEN env unset, or an
                           uncaught error in the ingest path.
    """
    await _verify_healthkit_request(request)
    # WHY: lazy import — same convention as every other /cron/* route. Keeps
    # /health cold-start fast and the Pydantic model out of the module-load
    # graph until a real request arrives.
    import mcp_tools.healthkit_tool as _hk  # noqa: PLC0415
    from memory.firestore_db import MealStore  # noqa: PLC0415
    from pydantic import ValidationError  # noqa: PLC0415

    try:
        payload_json = await request.json()
        # WHY: MealStore needs project_id + database (mirrors the pattern in
        # core/autonomous.py:321 — there's no zero-arg constructor; sourcing
        # from env keeps the handler aligned with every other Firestore
        # store-construction site in the codebase).
        store = MealStore(
            project_id=os.environ.get("GCP_PROJECT_ID", ""),
            database=os.environ.get("FIRESTORE_DATABASE", "(default)"),
        )
        try:
            result = _hk.ingest_payload(payload_json, store)
        except ValidationError as ve:
            _log_cron_run("healthkit-sync", ok=False)
            raise HTTPException(
                status_code=422,
                detail={"error": "Payload validation failed", "errors": ve.errors()},
            )
        _log_cron_run("healthkit-sync", ok=True)
    except HTTPException:
        raise
    except Exception:
        _log_cron_run("healthkit-sync", ok=False)
        raise
    return JSONResponse(content={"upserted": result["upserted_count"]})
