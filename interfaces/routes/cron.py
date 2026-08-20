"""Scheduled jobs driven by Cloud Scheduler.

Ingestion (Garmin runs and biometrics, Hevy strength, the Things mirror), the
deterministic alert pass, the weekly training review, the heartbeat, and the two
backstops that publish a routine if its real trigger never fired.

Every job records its outcome through _log_cron_run so a silent failure shows up
as a stale ledger entry rather than as nothing at all.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

from interfaces.routes._verify import _log_cron_run, _verify_cron_request
from interfaces.routes.triggers import (
    _routine_cutover_enabled,
    _start_subscription_routine,
    night_just_ended,
)

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/cron/nightly-backstop")
async def cron_nightly_backstop(request: Request) -> JSONResponse:
    """Safety-net for the nightly review if the Sleep-Focus trigger never fired.

    Schedule: 30 1 * * *  (Asia/Jerusalem) — half an hour after the night it
    covers has closed (``_NIGHT_ROLLOVER_HOUR``). That ordering is the whole
    point: run it *before* the rollover and it claims the night Amit has not
    gone to bed for yet, which silently swallowed his real Sleep-Focus trigger
    for three nights. Authenticated via OIDC bearer.
    Idempotent: run_nightly no-ops if the trigger already sent tonight's review, so
    on a normal night this fires, sees "already sent", and does nothing.

    The backstop starts the same remote Claude Routine instead of composing
    anything in Cloud Run. Its result record remains idempotent, and this
    route's cron log reflects only whether the remote run was accepted.

    Returns:
        JSONResponse: ``{"accepted": true}`` with HTTP 202 on successful enqueue,
            or ``{"accepted": false, "error": "dispatch unavailable"}`` with
            HTTP 503 if Cloud Tasks enqueue fails — Cloud Scheduler retries.
    """
    await _verify_cron_request(request)
    target = night_just_ended()
    if _routine_cutover_enabled("nightly"):
        response = await _start_subscription_routine("nightly", target, "backstop")
        _log_cron_run("nightly-backstop", ok=response.status_code == 202)
        return response
    _log_cron_run("nightly-backstop", ok=False)
    raise HTTPException(
        status_code=503,
        detail={"error": "Claude nightly Routine cutover is unavailable"},
    )


@router.post("/cron/morning-backstop")
async def cron_morning_backstop(request: Request) -> JSONResponse:
    """10:30 Asia/Jerusalem backstop for the subscription morning routine."""
    await _verify_cron_request(request)
    if not _routine_cutover_enabled("morning"):
        return JSONResponse(
            status_code=409,
            content={"accepted": False, "error": "morning subscription cutover disabled"},
        )
    today_iso = datetime.now(ZoneInfo("Asia/Jerusalem")).date().isoformat()
    response = await _start_subscription_routine("morning", today_iso, "backstop")
    _log_cron_run("morning-backstop", ok=response.status_code == 202)
    return response


@router.post("/cron/schedule-reminders")
async def cron_schedule_reminders(request: Request) -> JSONResponse:
    """Arm every routine's reminder for the coming day.

    Schedule: 10 0 * * *  (Asia/Jerusalem) — just after midnight, so every
    anchor_time it schedules is still ahead of it.

    The write paths in interfaces/routes/routines_hub.py already schedule a
    reminder the moment Amit arms one, which is what makes "remind me in two
    minutes" work. This job is the repair pass: it re-arms routines for the new
    day and heals anything the write path failed to enqueue. Idempotent — it
    cancels and recreates through the same one-doc-per-routine store.
    """
    await _verify_cron_request(request)
    from core.routines.reminders import schedule_all

    try:
        result = await asyncio.to_thread(schedule_all)
        _log_cron_run("schedule-reminders", ok=True)
    except Exception:
        _log_cron_run("schedule-reminders", ok=False)
        raise
    return JSONResponse(content={"ok": True, **result})


@router.post("/cron/deterministic-alerts")
async def cron_deterministic_alerts(request: Request) -> JSONResponse:
    """Run the deterministic rules with no legacy runtime dependency.

    Schedule: */30 * * * *  (Asia/Jerusalem). Round the clock on purpose — the
    day opens on Amit's wake trigger at whatever hour that lands, so the window
    lives in ``alert_window_open`` and not in this cron expression. Outside the
    window the pass costs one indexed query and returns.
    """
    await _verify_cron_request(request)
    from core.routines.alerts import run_rule_evaluator

    try:
        result = await run_rule_evaluator()
        _log_cron_run("deterministic-alerts", ok=True)
    except Exception:
        _log_cron_run("deterministic-alerts", ok=False)
        raise
    return JSONResponse(content={"ok": True, **result})


@router.post("/cron/weekly-training-review")
async def cron_weekly_training_review(request: Request) -> JSONResponse:
    """Start the Sunday Claude subscription routine after OIDC verification."""
    await _verify_cron_request(request)
    today = datetime.now(ZoneInfo("Asia/Jerusalem")).date().isoformat()
    if _routine_cutover_enabled("weekly"):
        response = await _start_subscription_routine("weekly", today, "cron")
        _log_cron_run("weekly-training-review", ok=response.status_code == 202)
        return response
    _log_cron_run("weekly-training-review", ok=False)
    raise HTTPException(
        status_code=503,
        detail={"error": "Claude weekly Routine cutover is unavailable"},
    )


@router.post("/cron/strength-sync")
async def cron_strength_sync(request: Request) -> JSONResponse:
    """Receive Cloud Scheduler daily tick and run a bounded Hevy strength-sync batch.

    Schedule: 0 5 * * *  (Asia/Jerusalem)
    Authenticated via OIDC bearer token from Cloud Scheduler.

    Pull-only with no conversation-runtime dependency. The only sink is
    StrengthSessionStore (via core.ingest.strength.run_one_batch). On the first
    run this backfills full Hevy history over several ticks; thereafter it applies
    incremental workout events. Re-run until the response shows done:true.

    Returns:
        JSONResponse: batch status dict (ok, mode, processed, [deleted], done).
    """
    await _verify_cron_request(request)
    import asyncio as _asyncio
    import core.ingest.strength as _strength
    try:
        loop = _asyncio.get_running_loop()
        result = await loop.run_in_executor(None, _strength.run_one_batch)
        _log_cron_run("strength-sync", ok=bool(result.get("ok")), backlog_done=result.get("done"))
        return JSONResponse(content=result)
    except Exception:
        _log_cron_run("strength-sync", ok=False)
        raise


@router.post("/cron/things-sync")
async def cron_things_sync(request: Request) -> JSONResponse:
    """Receive a Cloud Scheduler tick and refresh the Things 3 mirror.

    Schedule: */30 6-23 * * *  (Asia/Jerusalem)
    Authenticated via OIDC bearer token from Cloud Scheduler.

    Pull-only with no conversation-runtime dependency. The only sink is the
    Firestore mirror (via core.ingest.things.run_one_batch).

    A backstop, not the primary path: ThingsTaskStore checks the journal head on
    every read and pulls its own delta, so conversational reads are already fresh.
    This keeps the mirror warm for cold starts, and keeps the fallback that reads
    degrade to hours old rather than days when Things Cloud is unreachable.

    Returns:
        JSONResponse: status dict (ok, mode, cursor, entities, open_todos, done).
    """
    await _verify_cron_request(request)
    import asyncio as _asyncio
    import core.ingest.things as _things
    try:
        loop = _asyncio.get_running_loop()
        result = await loop.run_in_executor(None, _things.run_one_batch)
        _log_cron_run("things-sync", ok=bool(result.get("ok")), backlog_done=result.get("done"))
        return JSONResponse(content=result)
    except Exception:
        _log_cron_run("things-sync", ok=False)
        raise


@router.post("/cron/run-sync")
async def cron_run_sync(request: Request) -> JSONResponse:
    """Receive Cloud Scheduler daily tick and run a bounded Garmin run-detail batch.

    Schedule: 15 5 * * *  (Asia/Jerusalem) — staggered after strength-sync (05:00)
    to spread Garmin login load.
    Authenticated via OIDC bearer token from Cloud Scheduler.

    Pull-only with no conversation-runtime dependency. The only sink is
    RunDetailStore (via core.ingest.run.run_one_batch). On the first run this
    backfills per-run detail over several ticks; thereafter it pulls detail for
    new runs only. Kept a SEPARATE job from strength-sync so a Garmin rate-limit
    never marks the Hevy sync failed. Re-run until the response shows done:true.

    Returns:
        JSONResponse: batch status dict (ok, mode, processed, remaining, done).
    """
    await _verify_cron_request(request)
    import asyncio as _asyncio
    import core.ingest.run as _run
    try:
        loop = _asyncio.get_running_loop()
        result = await loop.run_in_executor(None, _run.run_one_batch)
        _log_cron_run("run-sync", ok=bool(result.get("ok")), backlog_done=result.get("done"))
        return JSONResponse(content=result)
    except Exception:
        _log_cron_run("run-sync", ok=False)
        raise


@router.post("/cron/biometric-sync")
async def cron_biometric_sync(request: Request) -> JSONResponse:
    """Receive Cloud Scheduler daily tick and run a bounded Garmin biometrics batch.

    Schedule: 30 5 * * *  (Asia/Jerusalem) — staggered after run-sync (05:15)
    to spread Garmin login load.
    Authenticated via OIDC bearer token from Cloud Scheduler.

    Pull-only with no conversation-runtime dependency. The only sink is
    the Postgres daily_biometrics table (via core.ingest.biometric.run_one_batch),
    which powers rolling HRV/resting-HR baselines. On the first run this
    backfills ~90 days over several ticks; thereafter it heals today+yesterday
    and pulls any missed days. Re-run until the response shows done:true.

    Returns:
        JSONResponse: batch status dict (ok, mode, processed, remaining, done).
    """
    await _verify_cron_request(request)
    import asyncio as _asyncio
    import core.ingest.biometric as _biometric
    try:
        loop = _asyncio.get_running_loop()
        result = await loop.run_in_executor(None, _biometric.run_one_batch)
        _log_cron_run("biometric-sync", ok=bool(result.get("ok")), backlog_done=result.get("done"))
        return JSONResponse(content=result)
    except Exception:
        _log_cron_run("biometric-sync", ok=False)
        raise


@router.post("/cron/heartbeat")
async def cron_heartbeat(request: Request) -> JSONResponse:
    """Receive Cloud Scheduler hourly tick and run one heartbeat health check.

    Schedule: 0 * * * *  (Asia/Jerusalem)
    Authenticated via OIDC bearer token from Cloud Scheduler.

    Returns:
        JSONResponse: ``{"ok": true}`` with HTTP 200.
    """
    await _verify_cron_request(request)
    from core.routines.heartbeat import collect_deterministic_signals

    try:
        signals = await asyncio.to_thread(collect_deterministic_signals)
        _log_cron_run("heartbeat", ok=True)
    except Exception:
        _log_cron_run("heartbeat", ok=False)
        raise
    return JSONResponse(content={"ok": True, "signals": [signal.__dict__ for signal in signals]})
