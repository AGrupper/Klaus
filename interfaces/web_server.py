"""Cloud Run webhook server for Klaus.

This module is the cloud entry point for the Klaus agent when deployed on
Google Cloud Run.  It exposes a minimal FastAPI application with two routes:

    GET  /healthz            — liveness/startup probe (no auth, no init).
    POST /telegram-webhook   — receives Telegram Updates via webhook.

The ``AgentOrchestrator`` and the python-telegram-bot ``Application`` are
created lazily inside the FastAPI lifespan handler so that ``/healthz`` can
respond on cold start *before* any heavyweight initialisation completes.

Container entry point:
    uvicorn interfaces.web_server:app --host 0.0.0.0 --port ${PORT:-8080} --workers 1

Single worker is required: ``ConversationManager`` is an in-process singleton.
Multiple workers would split per-user conversation history across processes,
causing the agent to lose context mid-conversation.
"""
from __future__ import annotations

import asyncio
import hmac
import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from typing import AsyncGenerator
from zoneinfo import ZoneInfo

from dotenv import load_dotenv
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from telegram import Update
from telegram.ext import Application

from core.main import AgentOrchestrator
from interfaces._router import MessageRouter, parse_allowed_user_ids

# WHY: override=True ensures .env values win even when the shell has already
# exported the variable — the default behaviour silently ignores .env in that
# case, which causes confusing "wrong token" failures in local dev.
load_dotenv(override=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s"
)

logger = logging.getLogger(__name__)

# ------------------------------------------------------------------ #
# Module-level singletons (populated during lifespan startup)        #
# ------------------------------------------------------------------ #

# WHY: these are module-level so the /telegram-webhook handler can reference
# them without passing objects through FastAPI's dependency system, keeping
# the routing code straightforward and easy to follow.
_orchestrator: AgentOrchestrator | None = None
_router: MessageRouter | None = None
_application: Application | None = None


# ------------------------------------------------------------------ #
# FastAPI lifespan                                                    #
# ------------------------------------------------------------------ #

@asynccontextmanager
async def lifespan(fastapi_app: FastAPI) -> AsyncGenerator[None, None]:
    """Initialise and shut down the Klaus singletons around the server lifetime.

    Runs once when the Cloud Run container becomes ready to serve traffic.
    Keeping all heavyweight initialisation here (rather than at import time)
    means ``/healthz`` responds immediately even if Firestore, Anthropic, or
    Google OAuth are still waking up.

    Args:
        fastapi_app: The ``FastAPI`` instance (provided by the framework; unused
                     directly but required by the lifespan protocol).

    Yields:
        None — control returns to FastAPI, which starts serving requests.
    """
    global _orchestrator, _router, _application  # noqa: PLW0603

    telegram_bot_token = os.environ["TELEGRAM_BOT_TOKEN"]

    # WHY: ``Application.initialize()`` registers the Bot, sets up the
    # internal request queue, and validates the token with the Telegram API.
    # We must await it before any Update can be deserialized via app.bot.
    _application = Application.builder().token(telegram_bot_token).build()
    await _application.initialize()
    logger.info("Telegram Application initialised.")

    # WHY: ``AgentOrchestrator`` loads both LLM clients and reads prompt files
    # from disk — doing this at startup avoids per-request latency on the first
    # real message while still not blocking the health probe.
    _orchestrator = AgentOrchestrator()
    logger.info("AgentOrchestrator initialised.")

    # Build the router with the allow-listed user IDs from the environment.
    _router = MessageRouter(
        orchestrator=_orchestrator,
        allowed_user_ids=parse_allowed_user_ids(),
    )
    logger.info("MessageRouter initialised.")

    yield  # Server is live and handling requests from here.

    # ---- Shutdown ----
    # WHY: graceful shutdown flushes any in-flight Telegram API calls and
    # releases the underlying HTTP connections cleanly.
    await _application.shutdown()
    logger.info("Telegram Application shut down.")


# ------------------------------------------------------------------ #
# FastAPI application                                                 #
# ------------------------------------------------------------------ #

app = FastAPI(
    title="Klaus – Cloud Run webhook server",
    description="Telegram webhook entry point for the Klaus personal AI agent.",
    lifespan=lifespan,
)


# ------------------------------------------------------------------ #
# Routes                                                              #
# ------------------------------------------------------------------ #

@app.get("/health")
async def health_check() -> JSONResponse:
    """Liveness and startup probe used by Cloud Run.

    Returns ``{"status": "ok"}`` with HTTP 200 immediately, with no
    authentication and no dependency on the orchestrator.  Cloud Run will
    stop sending traffic to an instance that fails this check.

    Returns:
        JSONResponse: ``{"status": "ok"}`` with HTTP status 200.
    """
    return JSONResponse(content={"status": "ok"})


@app.post("/telegram-webhook")
async def telegram_webhook(
    request: Request,
    x_telegram_bot_api_secret_token: str | None = Header(default=None),
) -> JSONResponse:
    """Receive and dispatch a Telegram Update sent by the Telegram Bot API.

    Telegram calls this endpoint for every incoming message, command, or
    callback when webhook mode is active.  The endpoint:

    1. Validates the ``X-Telegram-Bot-Api-Secret-Token`` header via constant-time
       comparison to prevent timing-based token disclosure.
    2. Deserialises the JSON body into a python-telegram-bot ``Update`` object.
    3. Delegates the Update to ``MessageRouter.handle_update``.

    Args:
        request:
            The raw FastAPI ``Request`` object, used to read the JSON body.
        x_telegram_bot_api_secret_token:
            Value of the ``X-Telegram-Bot-Api-Secret-Token`` header injected
            by Telegram on every webhook call.  Compared against
            ``TELEGRAM_WEBHOOK_SECRET`` from the environment.

    Returns:
        JSONResponse: ``{"ok": true}`` with HTTP 200 on success.

    Raises:
        HTTPException 401: If the secret token header is absent or incorrect.
        HTTPException 500: If the singletons are not yet initialised (should
                           never happen in normal operation because Cloud Run
                           waits for the lifespan startup to complete before
                           routing traffic).
    """
    # ---- Token validation ----
    expected_secret = os.environ.get("TELEGRAM_WEBHOOK_SECRET", "")

    # WHY: ``hmac.compare_digest`` does a constant-time string comparison.
    # A plain ``==`` leaks timing information: an attacker who sends thousands
    # of probes can measure how many characters match, and eventually reconstruct
    # the secret.  ``compare_digest`` always takes the same amount of time
    # regardless of how many characters match.
    provided_secret = x_telegram_bot_api_secret_token or ""
    token_is_valid = hmac.compare_digest(provided_secret, expected_secret)

    if not token_is_valid:
        logger.warning(
            "Rejected webhook request — invalid or missing secret token."
        )
        raise HTTPException(
            status_code=401,
            detail={"error": "Unauthorised: invalid or missing secret token."},
        )

    # ---- Singleton guard ----
    # WHY: in normal Cloud Run operation the lifespan startup always completes
    # before traffic is routed, so this branch should never fire.  The guard is
    # a defensive safety net for unusual startup edge cases.
    if _application is None or _router is None:
        logger.error(
            "Webhook received before singletons were initialised — "
            "this should not happen in normal Cloud Run operation."
        )
        raise HTTPException(
            status_code=500,
            detail={"error": "Server is still initialising; please retry."},
        )

    # ---- Deserialise the Update ----
    request_json: dict = await request.json()

    # WHY: ``Update.de_json`` is the canonical python-telegram-bot factory for
    # converting raw Telegram JSON into a typed ``Update`` object.  The ``bot``
    # argument is required because some nested objects (e.g. ``Message``) call
    # back to the bot for helper methods like ``reply_text``.
    update = Update.de_json(data=request_json, bot=_application.bot)

    # ---- Dispatch ----
    await _router.handle_update(update)

    return JSONResponse(content={"ok": True})


# ------------------------------------------------------------------ #
# Cloud Scheduler OIDC verification                                  #
# ------------------------------------------------------------------ #

async def _verify_cron_request(request: Request) -> None:
    """Verify a Cloud Scheduler OIDC bearer token, or skip in dev mode.

    Reads three env vars:
      CRON_DEV_BYPASS         — set to "true" to skip auth in local dev.
      CLOUD_RUN_URL           — OIDC audience (the Cloud Run service URL).
      CLOUD_SCHEDULER_SA_EMAIL — expected service-account email in the token.

    Raises:
        HTTPException 401: Token missing, invalid, or wrong audience.
        HTTPException 403: Token valid but service account does not match.
    """
    if os.getenv("CRON_DEV_BYPASS", "false").lower() == "true":
        logger.info("CRON_DEV_BYPASS=true — skipping OIDC verification")
        return

    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(
            status_code=401,
            detail={"error": "Missing or malformed Authorization header"},
        )

    token = auth_header.removeprefix("Bearer ").strip()
    cloud_run_url = os.environ["CLOUD_RUN_URL"]
    expected_sa = os.environ["CLOUD_SCHEDULER_SA_EMAIL"]

    try:
        from google.auth.transport.requests import Request as GoogleRequest
        from google.oauth2.id_token import verify_oauth2_token

        payload = verify_oauth2_token(token, GoogleRequest(), audience=cloud_run_url)
    except Exception as exc:
        logger.warning("Cron OIDC verification failed: %s", exc)
        raise HTTPException(
            status_code=401,
            detail={"error": "Invalid OIDC token"},
        )

    if payload.get("email") != expected_sa:
        raise HTTPException(
            status_code=403,
            detail={"error": "Unexpected service account in OIDC token"},
        )


def _log_cron_run(job_id: str, ok: bool, *, backlog_done: bool | None = None) -> None:
    """Best-effort liveness ledger write for a cron endpoint. Never raises."""
    try:
        from memory.firestore_db import record_cron_run
        record_cron_run(job_id, ok, backlog_done=backlog_done)
    except Exception:
        logger.warning("Failed to record cron run for %s", job_id, exc_info=True)


# ------------------------------------------------------------------ #
# Five Fingers cron routes                                           #
# ------------------------------------------------------------------ #

@app.post("/cron/five-fingers-morning")
async def cron_five_fingers_morning(request: Request) -> JSONResponse:
    """Receive Cloud Scheduler morning tick and run the Five Fingers morning flow.

    Schedule: 30 10 * * 0,1,3,4  (Asia/Jerusalem)
    Authenticated via OIDC bearer token from Cloud Scheduler.

    Returns:
        JSONResponse: ``{"ok": true}`` with HTTP 200.
    """
    await _verify_cron_request(request)
    if _application is None:
        raise HTTPException(status_code=500, detail={"error": "Not initialised"})
    import core.five_fingers as _five_fingers
    try:
        today = datetime.now(ZoneInfo("Asia/Jerusalem")).date().isoformat()
        await _five_fingers.run_morning_endpoint(_application.bot, today)
        _log_cron_run("five-fingers", ok=True)
    except Exception:
        _log_cron_run("five-fingers", ok=False)
        raise
    return JSONResponse(content={"ok": True})


@app.post("/cron/proactive-alerts")
async def cron_proactive_alerts(request: Request) -> JSONResponse:
    """Receive Cloud Scheduler evening tick and run the proactive alerts scan.

    Schedule: 30 21 * * *  (Asia/Jerusalem)
    Authenticated via OIDC bearer token from Cloud Scheduler.

    Returns:
        JSONResponse: ``{"ok": true}`` with HTTP 200.
    """
    await _verify_cron_request(request)
    if _application is None:
        raise HTTPException(status_code=500, detail={"error": "Not initialised"})
    import core.proactive_alerts as _proactive
    try:
        tomorrow = (datetime.now(ZoneInfo("Asia/Jerusalem")) + timedelta(days=1)).date().isoformat()
        await _proactive.run_proactive_alerts(_application.bot, tomorrow)
        _log_cron_run("proactive-alerts", ok=True)
    except Exception:
        _log_cron_run("proactive-alerts", ok=False)
        raise
    return JSONResponse(content={"ok": True})


@app.post("/cron/reflect")
async def cron_reflect(request: Request) -> JSONResponse:
    """Daily reflection — gather the day, write a journal entry, evolve self_state.

    Schedule: 0 22 * * *  (Asia/Jerusalem)
    Authenticated via OIDC bearer token from Cloud Scheduler.

    Returns:
        JSONResponse: ``{"ok": true}`` with HTTP 200.
    """
    await _verify_cron_request(request)
    import asyncio as _asyncio
    import core.reflection as _reflection
    try:
        today = datetime.now(ZoneInfo("Asia/Jerusalem")).date().isoformat()
        loop = _asyncio.get_running_loop()
        await loop.run_in_executor(None, _reflection.run_reflection, today)
        _log_cron_run("reflect", ok=True)
    except Exception:
        _log_cron_run("reflect", ok=False)
        raise
    return JSONResponse(content={"ok": True})


@app.post("/cron/autonomous-tick")
async def cron_autonomous_tick(request: Request) -> JSONResponse:
    """Autonomous tick — judgment-driven proactive outreach.

    Schedule: */20 7-21 * * *  (Asia/Jerusalem) — 43 ticks/day.
    Authenticated via OIDC bearer token from Cloud Scheduler.

    Flow (Phase 18 — AUTO-06):
      1. Verify OIDC bearer (or honour CRON_DEV_BYPASS in local dev).
      2. Guard: _application must be initialised (mirrors cron_proactive_alerts
         and cron_morning_briefing_tick — the bot is required to send).
      3. Delegate to core.autonomous.run_autonomous_tick, which runs the full
         3-layer pipeline (gather → triage → compose) and only on success
         appends to outreach_log (D-10).
      4. Record success or failure to the heartbeat liveness ledger via
         _log_cron_run('autonomous-tick', ok=...). Failure path re-raises so
         Cloud Run logs the 500 and the consecutive_failures streak ticks up.

    Returns:
        JSONResponse: ``{"ok": true}`` with HTTP 200.
    """
    await _verify_cron_request(request)
    if _application is None:
        raise HTTPException(status_code=500, detail={"error": "Not initialised"})
    # WHY: imported inside the handler so the heavy core.autonomous module
    # (which pulls in tick_brain + the orchestrator graph) does not load at
    # web_server import time — keeps /health cold-start fast.
    import core.autonomous as _auto
    try:
        now = datetime.now(ZoneInfo("Asia/Jerusalem"))
        # run_autonomous_tick is async — it wraps the sync _run_smart_loop
        # in an executor internally, so the route just awaits the coroutine.
        await _auto.run_autonomous_tick(_application.bot, now)
        _log_cron_run("autonomous-tick", ok=True)
    except Exception:
        _log_cron_run("autonomous-tick", ok=False)
        raise
    return JSONResponse(content={"ok": True})


@app.post("/cron/five-fingers-evening")
async def cron_five_fingers_evening(request: Request) -> JSONResponse:
    """Receive Cloud Scheduler evening tick and run the Five Fingers evening flow.

    Schedule: 15 21 * * 0,3  (Asia/Jerusalem)
    Authenticated via OIDC bearer token from Cloud Scheduler.

    Returns:
        JSONResponse: ``{"ok": true}`` with HTTP 200.
    """
    await _verify_cron_request(request)
    if _application is None:
        raise HTTPException(status_code=500, detail={"error": "Not initialised"})
    import core.five_fingers as _five_fingers
    try:
        today = datetime.now(ZoneInfo("Asia/Jerusalem")).date().isoformat()
        await _five_fingers.run_evening_endpoint(_application.bot, today)
        _log_cron_run("five-fingers", ok=True)
    except Exception:
        _log_cron_run("five-fingers", ok=False)
        raise
    return JSONResponse(content={"ok": True})


@app.post("/cron/morning-briefing-tick")
async def cron_morning_briefing_tick(request: Request) -> JSONResponse:
    """Receive Cloud Scheduler 10-min tick and run the Garmin-sync detection logic.

    Schedule: */10 6-10 * * *  (Asia/Jerusalem)
    Authenticated via OIDC bearer token from Cloud Scheduler.

    Returns:
        JSONResponse: ``{"ok": true}`` with HTTP 200.
    """
    await _verify_cron_request(request)
    if _application is None:
        raise HTTPException(status_code=500, detail={"error": "Not initialised"})
    import core.morning_briefing as _morning
    try:
        await _morning.handle_tick(_application.bot)
        _log_cron_run("morning-briefing", ok=True)
    except Exception:
        _log_cron_run("morning-briefing", ok=False)
        raise
    return JSONResponse(content={"ok": True})


@app.post("/cron/ingest-chats")
async def cron_ingest_chats(request: Request) -> JSONResponse:
    """Receive Cloud Scheduler daily tick and run a bounded chat-log ingestion batch.

    Schedule: 0 4 * * *  (Asia/Jerusalem)
    Authenticated via OIDC bearer token from Cloud Scheduler.

    Processes up to BATCH_MAX_FILES files within BATCH_TIME_BUDGET_SEC.
    Re-run until the response shows done:true to drain the full backlog.

    Returns:
        JSONResponse: batch status dict with ok, processed, remaining, done.
    """
    await _verify_cron_request(request)
    import asyncio as _asyncio
    import core.chat_ingest as _ingest
    try:
        loop = _asyncio.get_running_loop()
        result = await loop.run_in_executor(None, _ingest.run_one_batch)
        _log_cron_run("ingest-chats", ok=True, backlog_done=result.get("done"))
        return JSONResponse(content=result)
    except Exception:
        _log_cron_run("ingest-chats", ok=False)
        raise


@app.post("/cron/ingest-chat-exports")
async def cron_ingest_chat_exports(request: Request) -> JSONResponse:
    """Receive Cloud Scheduler daily tick and run a bounded web-chat export ingestion batch.

    Schedule: 30 4 * * *  (Asia/Jerusalem)
    Authenticated via OIDC bearer token from Cloud Scheduler.

    Processes up to CHAT_EXPORT_BATCH_MAX_CONVERSATIONS conversations within
    CHAT_EXPORT_TIME_BUDGET_SEC from zips uploaded to chat-exports/ in GCS.
    Re-run until the response shows done:true to drain the full backlog.

    Returns:
        JSONResponse: batch status dict with ok, processed, remaining, done.
    """
    await _verify_cron_request(request)
    import asyncio as _asyncio
    import core.chat_export_ingest as _export_ingest
    try:
        loop = _asyncio.get_running_loop()
        result = await loop.run_in_executor(None, _export_ingest.run_one_batch)
        _log_cron_run("ingest-chat-exports", ok=True, backlog_done=result.get("done"))
        return JSONResponse(content=result)
    except Exception:
        _log_cron_run("ingest-chat-exports", ok=False)
        raise


@app.post("/cron/heartbeat")
async def cron_heartbeat(request: Request) -> JSONResponse:
    """Receive Cloud Scheduler hourly tick and run one heartbeat health check.

    Schedule: 0 * * * *  (Asia/Jerusalem)
    Authenticated via OIDC bearer token from Cloud Scheduler.

    Returns:
        JSONResponse: ``{"ok": true}`` with HTTP 200.
    """
    await _verify_cron_request(request)
    if _application is None:
        raise HTTPException(status_code=500, detail={"error": "Not initialised"})
    import core.heartbeat as _heartbeat
    try:
        await _heartbeat.run_tick(_application.bot)
        _log_cron_run("heartbeat", ok=True)
    except Exception:
        _log_cron_run("heartbeat", ok=False)
        raise
    return JSONResponse(content={"ok": True})
