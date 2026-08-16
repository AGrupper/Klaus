"""Routine triggers: the real wake and sleep moments, plus their fallback.

/trigger/morning and /trigger/nightly are fired by iOS Shortcuts when Amit
actually wakes or sets his Sleep Focus, which is why they exist separately from
the cron backstops that catch a missed trigger. /internal/routine-fallback is
the Cloud Tasks callback that publishes a deterministic review when Claude does
not answer in time.
"""
from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

from interfaces.flags import _flag_enabled, _routine_cutover_enabled
from interfaces.routes._verify import (
    _verify_cron_request,
    _verify_morning_trigger_request,
    _verify_trigger_request,
)

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/internal/routine-fallback")
async def internal_routine_fallback(request: Request) -> JSONResponse:
    """Cloud Tasks target for the ten-minute no-model review fallback."""
    await _verify_cron_request(request)
    body = await request.json()
    correlation_id = str(body.get("correlation_id") or "")
    if not correlation_id or len(correlation_id) > 128:
        raise HTTPException(
            status_code=400, detail={"error": "invalid correlation_id"}
        )
    from core.subscription_routines import build_subscription_routine_coordinator

    result = await build_subscription_routine_coordinator().publish_timeout_fallback(
        correlation_id
    )
    return JSONResponse(content=result)


async def _start_subscription_routine(
    routine: str, target_date: str, trigger: str,
) -> JSONResponse:
    """Fire a subscription-backed routine and preserve the trigger API contract."""
    from core.subscription_routines import build_subscription_routine_coordinator

    loop = asyncio.get_running_loop()
    coordinator = build_subscription_routine_coordinator()
    result = await loop.run_in_executor(
        None, coordinator.start, routine, target_date, trigger,
    )
    status_code = 202 if result.get("accepted") else 503
    return JSONResponse(status_code=status_code, content=result)


@router.post("/trigger/nightly")
async def trigger_nightly(request: Request) -> JSONResponse:
    """Receive the iOS Sleep-Focus automation and enqueue the nightly review.

    Triggered when Amit's phone winds down (organic), so there is no fixed schedule.
    Authenticated via the shared-secret NIGHTLY_TRIGGER_TOKEN.

    Acknowledges immediately (202) and starts the remote Claude Routine —
    never a Starlette BackgroundTask.
    This closes the D-32 defect: composing here used to run in a BackgroundTask,
    which runs AFTER the response and gets CPU-throttled by Cloud Run (the
    mistaken belief that "the request is still in-flight, so CPU stays
    allocated" does not hold for BackgroundTasks — that is the whole point of
    them running after the response). The response contract for the happy path
    is unchanged, so Amit's existing iOS Shortcut keeps working without
    modification. Idempotent downstream: if the nightly already sent for
    tonight (e.g. the backstop beat it), run_nightly no-ops.

    Returns:
        JSONResponse: ``{"accepted": true}`` with HTTP 202 on successful
            enqueue, or ``{"accepted": false, "error": "dispatch unavailable"}``
            with HTTP 503 if Cloud Tasks enqueue fails — the caller (iOS
            Shortcut) can retry.
    """
    await _verify_trigger_request(request)
    target = nightly_target_date_now()
    if _routine_cutover_enabled("nightly"):
        return await _start_subscription_routine("nightly", target, "focus")
    raise HTTPException(
        status_code=503,
        detail={"error": "Claude nightly Routine cutover is unavailable"},
    )


def nightly_target_date_now() -> str:
    """The wind-down date for 'now' in Asia/Jerusalem (import-light helper)."""
    return datetime.now(ZoneInfo("Asia/Jerusalem")).date().isoformat()


# D-31 dark-ship sequencing (closed in plan 33-12/33-13): this route shipped
# dark until Amit's iOS wake-up automation was confirmed firing live in
# production; the legacy */10 6-10 polling cron then retired in plan 33-13
# once that confirmation landed — this is now the sole morning trigger, with
# no cron backstop (D-09).
@router.post("/trigger/morning")
async def trigger_morning(request: Request) -> JSONResponse:
    """Receive the iOS wake-up automation and enqueue the morning briefing.

    Triggered on Amit's phone waking up — the mirror of the existing
    Sleep-Focus-on → /trigger/nightly automation (D-08). The exact iOS
    mechanism varies by version (Wake Up on public iOS before 27, Sleep
    Focus from iOS 27 — see docs/sleep_focus_off_shortcut.md §3.0).
    Authenticated via the dedicated MORNING_TRIGGER_TOKEN (D-13 — least
    privilege, no shared secret with the nightly trigger).

    Acknowledges immediately (202) and starts the remote Claude Routine —
    never a Starlette BackgroundTask. The routine coordinator's correlation
    record makes a snooze/second alarm/Focus toggle safe to retry.

    Returns:
        JSONResponse: ``{"accepted": true}`` with HTTP 202 on successful
            enqueue, or ``{"accepted": false, "error": "dispatch unavailable"}``
            with HTTP 503 if Cloud Tasks enqueue fails — the caller (iOS
            Shortcut) can retry.
    """
    await _verify_morning_trigger_request(request)
    today_iso = datetime.now(ZoneInfo("Asia/Jerusalem")).date().isoformat()
    if _routine_cutover_enabled("morning"):
        return await _start_subscription_routine("morning", today_iso, "wake")
    raise HTTPException(
        status_code=503,
        detail={"error": "Claude morning Routine cutover is unavailable"},
    )
