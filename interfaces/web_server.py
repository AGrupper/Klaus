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
from collections import OrderedDict
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from typing import AsyncGenerator
from zoneinfo import ZoneInfo

from dotenv import load_dotenv
from fastapi import BackgroundTasks, Depends, FastAPI, Header, HTTPException, Query, Request, Response
from fastapi.responses import JSONResponse
from telegram import Update
from telegram.ext import Application

from core.main import AgentOrchestrator
from core.task_dispatch import enqueue_hub_message, enqueue_update
from interfaces._router import MessageRouter, parse_allowed_user_ids
from interfaces.hub_auth import require_hub_session  # HUB-01: used by /api/* Depends

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

# Recently accepted Telegram update_ids, used to drop webhook retries.
# WHY: Telegram re-delivers an Update if it doesn't get a 200 quickly. We now
# ACK before processing, but a retry can still arrive for an update we already
# accepted (e.g. the first ACK was lost in transit). In-process only — a cold
# start forgets it, which is fine because Telegram retries arrive within
# seconds of the original, never across container restarts.
_recent_update_ids: "OrderedDict[int, None]" = OrderedDict()
_RECENT_UPDATE_IDS_MAX = 256


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
    # Phase 20: expose the Bot on the orchestrator so non-callback code paths can
    # send messages. Button taps get the bot from the callback query, but a typed
    # training-note reply (core.training_checkin.attach_note /
    # attach_skipreason_other_note) reaches the bot only via the orchestrator.
    _orchestrator.bot = _application.bot
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


async def _handle_update_background(update: Update) -> None:
    """Fallback: process a Telegram Update in-process, off the critical path.

    WHY this is only a fallback: a Starlette BackgroundTask runs AFTER the
    response is sent, so no request is in flight while the agent turn runs
    and Cloud Run throttles the container CPU — the turn crawls (observed
    2026-06-12: an 18-minute reply). The primary path is Cloud Tasks
    (``core.task_dispatch.enqueue_update``), which re-delivers the update to
    /internal/process-update inside a tracked, full-CPU request. This path
    survives a Cloud Tasks outage or unset queue config: slow beats dropped.
    Errors are logged here since they can no longer surface in the response.
    """
    try:
        await _router.handle_update(update)
    except Exception:
        logger.exception(
            "Background processing failed for update_id=%s", update.update_id
        )


@app.post("/telegram-webhook")
async def telegram_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    x_telegram_bot_api_secret_token: str | None = Header(default=None),
) -> JSONResponse:
    """Receive and dispatch a Telegram Update sent by the Telegram Bot API.

    Telegram calls this endpoint for every incoming message, command, or
    callback when webhook mode is active.  The endpoint:

    1. Validates the ``X-Telegram-Bot-Api-Secret-Token`` header via constant-time
       comparison to prevent timing-based token disclosure.
    2. Deserialises the JSON body into a python-telegram-bot ``Update`` object.
    3. Drops the Update if its ``update_id`` was already accepted (Telegram
       webhook retry), then ACKs with 200 immediately and delegates the Update
       to ``MessageRouter.handle_update`` as a background task so a slow agent
       turn can never trigger a Telegram re-delivery.

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

    # ---- Retry dedup ----
    update_id = update.update_id
    if update_id in _recent_update_ids:
        logger.info(
            "Duplicate Telegram update_id=%s — already accepted, ignoring retry.",
            update_id,
        )
        return JSONResponse(content={"ok": True})
    _recent_update_ids[update_id] = None
    while len(_recent_update_ids) > _RECENT_UPDATE_IDS_MAX:
        _recent_update_ids.popitem(last=False)

    # ---- Dispatch ----
    # Primary: hand the update to Cloud Tasks so the agent turn runs inside
    # /internal/process-update — a tracked request with full CPU. Fallback:
    # in-process background task (throttled CPU, but the update is never
    # dropped) when the queue is unconfigured or Cloud Tasks errors.
    if not enqueue_update(request_json):
        background_tasks.add_task(_handle_update_background, update)

    return JSONResponse(content={"ok": True})


@app.post("/internal/process-update")
async def internal_process_update(request: Request) -> JSONResponse:
    """Cloud Tasks target: process one Telegram Update with full CPU.

    The webhook enqueues the raw update JSON via
    ``core.task_dispatch.enqueue_update``; Cloud Tasks POSTs it here with an
    OIDC token from the same service account the Cloud Scheduler crons use,
    verified by ``_verify_cron_request``. Because the agent turn runs inside
    this request, Cloud Run allocates full CPU for its whole duration —
    unlike a BackgroundTask, which runs after the response on throttled CPU.

    Raises:
        HTTPException 401/403: OIDC verification failed.
        HTTPException 500: Singletons not initialised (Cloud Tasks retries).
    """
    await _verify_cron_request(request)

    if _application is None or _router is None:
        logger.error("/internal/process-update before singletons initialised")
        raise HTTPException(
            status_code=500,
            detail={"error": "Server is still initialising; please retry."},
        )

    request_json: dict = await request.json()
    update = Update.de_json(data=request_json, bot=_application.bot)

    # WHY no try/except: the router already shields user-facing errors (it
    # replies with an apology and swallows orchestrator exceptions). Anything
    # that escapes is infrastructure-level — let it surface as a 500 so Cloud
    # Tasks retries the turn.
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


async def _verify_healthkit_request(request: Request) -> None:
    """Verify a shared-secret bearer token from the iPhone Shortcut.

    Reads HEALTHKIT_WEBHOOK_TOKEN env (sourced from Secret Manager binding
    klaus-healthkit-webhook-token; see DEPLOYMENT.md §23).

    Constant-time compare via hmac.compare_digest (RESEARCH.md Q5) — NEVER
    ``==`` — to prevent timing-side-channel token leaks. Failed attempts
    are logged at WARNING with a redacted token prefix so the secret is
    never written to logs in full (RESEARCH.md Security Domain row
    "Token leaked via log scraping").

    Raises:
        HTTPException 401: Missing / malformed Authorization header.
        HTTPException 403: Bearer present but does not match the secret.
        HTTPException 500: HEALTHKIT_WEBHOOK_TOKEN env unset (refuse-all).
    """
    if os.getenv("CRON_DEV_BYPASS", "false").lower() == "true":
        logger.info("CRON_DEV_BYPASS=true — skipping HealthKit auth")
        return

    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(
            status_code=401,
            detail={"error": "Missing or malformed Authorization header"},
        )

    received = auth_header.removeprefix("Bearer ").strip()
    expected = os.environ.get("HEALTHKIT_WEBHOOK_TOKEN", "")
    if not expected:
        # WHY: refuse-all on unset env var prevents a fail-open when the
        # Secret Manager mount silently fails. Surfaces as a 500 the
        # operator can detect via heartbeat staleness instead of letting
        # any random POST in.
        logger.error(
            "HEALTHKIT_WEBHOOK_TOKEN env unset — refusing all HealthKit auth"
        )
        raise HTTPException(
            status_code=500,
            detail={"error": "Server misconfigured"},
        )

    # WHY: hmac.compare_digest does a constant-time byte compare. A plain
    # `==` leaks timing information that lets an attacker reconstruct the
    # token byte-by-byte. Mandatory per RESEARCH.md Q5.
    if not hmac.compare_digest(received.encode(), expected.encode()):
        client = request.client.host if request.client else "?"
        redacted = (
            received[:4] + "..." + received[-4:] if len(received) >= 8 else "***"
        )
        logger.warning(
            "healthkit auth failed from %s (token_prefix=%s)", client, redacted,
        )
        raise HTTPException(
            status_code=403,
            detail={"error": "Invalid token"},
        )


async def _verify_trigger_request(request: Request) -> None:
    """Verify a shared-secret bearer token from the iOS Sleep-Focus Shortcut.

    The nightly review is triggered by an iPhone Personal Automation ("When Sleep
    Focus turns On → POST /trigger/nightly"). It carries a dedicated bearer token
    (NIGHTLY_TRIGGER_TOKEN, sourced from Secret Manager) rather than the Cloud
    Scheduler OIDC token — least privilege: a leaked HealthKit/cron credential must
    not be able to make Klaus send messages, and vice-versa.

    Mirrors _verify_healthkit_request exactly (constant-time compare, refuse-all on
    unset env, redacted-prefix logging).

    Raises:
        HTTPException 401: Missing / malformed Authorization header.
        HTTPException 403: Bearer present but does not match the secret.
        HTTPException 500: NIGHTLY_TRIGGER_TOKEN env unset (refuse-all).
    """
    if os.getenv("CRON_DEV_BYPASS", "false").lower() == "true":
        logger.info("CRON_DEV_BYPASS=true — skipping nightly-trigger auth")
        return

    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(
            status_code=401,
            detail={"error": "Missing or malformed Authorization header"},
        )

    received = auth_header.removeprefix("Bearer ").strip()
    expected = os.environ.get("NIGHTLY_TRIGGER_TOKEN", "")
    if not expected:
        # WHY: refuse-all on unset env prevents a fail-open if the Secret Manager
        # mount silently fails — surfaces as a 500 the operator can detect rather
        # than letting any random POST trigger a send.
        logger.error("NIGHTLY_TRIGGER_TOKEN env unset — refusing all nightly-trigger auth")
        raise HTTPException(status_code=500, detail={"error": "Server misconfigured"})

    if not hmac.compare_digest(received.encode(), expected.encode()):
        client = request.client.host if request.client else "?"
        redacted = received[:4] + "..." + received[-4:] if len(received) >= 8 else "***"
        logger.warning("nightly-trigger auth failed from %s (token_prefix=%s)", client, redacted)
        raise HTTPException(status_code=403, detail={"error": "Invalid token"})


def _log_cron_run(job_id: str, ok: bool, *, backlog_done: bool | None = None) -> None:
    """Best-effort liveness ledger write for a cron endpoint. Never raises."""
    try:
        from memory.firestore_db import record_cron_run
        record_cron_run(job_id, ok, backlog_done=backlog_done)
    except Exception:
        logger.warning("Failed to record cron run for %s", job_id, exc_info=True)





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


# NOTE: the standalone /cron/reflect (22:00) route was retired in WS2. The nightly
# review (_ensure_reflection) writes the journal/self_state when Amit winds down, and
# /cron/nightly-backstop (01:00) guarantees it on nights the Sleep-Focus trigger never
# fires — so a separate 22:00 reflect job would only duplicate that work (and overwrite
# the nightly's journal on early-wind-down nights). core.reflection.run_reflection lives
# on and is invoked by the nightly flow.


async def _run_nightly_background(target: str, trigger: str) -> None:
    """Compose + send the nightly review off the request's critical path.

    WHY: composing the nightly runs several LLM calls (reflection + tomorrow gather +
    compose) which can exceed the iOS Shortcut's HTTP timeout. Run as a FastAPI
    background task so the trigger route returns 202 immediately (the phone stops
    waiting) while the server finishes the work. The request is still in-flight while
    this runs, so Cloud Run keeps CPU allocated — no --no-cpu-throttling needed.
    Errors are logged + recorded here since they can no longer surface in the response.
    """
    import core.nightly_review as _nightly
    try:
        await _nightly.run_nightly(_application.bot, target, trigger=trigger)
        _log_cron_run("nightly-trigger", ok=True)
    except Exception:
        logger.exception("nightly background task failed for %s (%s)", target, trigger)
        _log_cron_run("nightly-trigger", ok=False)


@app.post("/trigger/nightly")
async def trigger_nightly(request: Request, background_tasks: BackgroundTasks) -> JSONResponse:
    """Receive the iOS Sleep-Focus automation and send the nightly review.

    Triggered when Amit's phone winds down (organic), so there is no fixed schedule.
    Authenticated via the shared-secret NIGHTLY_TRIGGER_TOKEN.

    Acknowledges immediately (202) and composes the nightly in the background so the
    iOS Shortcut never waits on the multi-LLM compose. Idempotent downstream: if the
    nightly already sent for tonight (e.g. the backstop beat it), run_nightly no-ops.

    Returns:
        JSONResponse: ``{"accepted": true}`` with HTTP 202.
    """
    await _verify_trigger_request(request)
    if _application is None:
        raise HTTPException(status_code=500, detail={"error": "Not initialised"})
    target = nightly_target_date_now()
    background_tasks.add_task(_run_nightly_background, target, "focus")
    return JSONResponse(status_code=202, content={"accepted": True})


def nightly_target_date_now() -> str:
    """The wind-down date for 'now' in Asia/Jerusalem (import-light helper)."""
    import core.nightly_review as _nightly
    return _nightly.nightly_target_date(datetime.now(ZoneInfo("Asia/Jerusalem")))


@app.post("/cron/nightly-backstop")
async def cron_nightly_backstop(request: Request) -> JSONResponse:
    """Safety-net for the nightly review if the Sleep-Focus trigger never fired.

    Schedule: 0 1 * * *  (Asia/Jerusalem) — ~01:00. Authenticated via OIDC bearer.
    Idempotent: run_nightly no-ops if the trigger already sent tonight's review, so
    on a normal night this fires, sees "already sent", and does nothing.

    Returns:
        JSONResponse: ``{"sent": true|false}`` with HTTP 200.
    """
    await _verify_cron_request(request)
    if _application is None:
        raise HTTPException(status_code=500, detail={"error": "Not initialised"})
    import core.nightly_review as _nightly
    try:
        target = _nightly.nightly_target_date(datetime.now(ZoneInfo("Asia/Jerusalem")))
        sent = await _nightly.run_nightly(_application.bot, target, trigger="backstop")
        _log_cron_run("nightly-backstop", ok=True)
    except Exception:
        _log_cron_run("nightly-backstop", ok=False)
        raise
    return JSONResponse(content={"sent": sent})


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


@app.post("/cron/weekly-training-review")
async def cron_weekly_training_review(request: Request) -> JSONResponse:
    """Weekly training review — Sunday 10:00 Asia/Jerusalem.

    Phase 20 — REVIEW-01.

    Flow:
      1. Verify OIDC bearer (or honour CRON_DEV_BYPASS in local dev).
      2. Guard: _application must be initialised (bot is required to send).
      3. Delegate to core.weekly_training_review.run_weekly_review, which
         gathers the previous Sun–Sat window (training_log, Garmin, biometrics,
         MealStore totals, athletic_goals), brain-composes the scorecard +
         narrative + suggestion, and always sends (D-24).
      4. Record success or failure to the heartbeat liveness ledger via
         _log_cron_run('weekly-training-review', ok=...). Re-raises on exception.

    Returns:
        JSONResponse: ``{"ok": true}`` with HTTP 200.
    """
    await _verify_cron_request(request)
    if _application is None:
        raise HTTPException(status_code=500, detail={"error": "Not initialised"})
    # WHY: imported inside the handler so the module does not load at
    # web_server import time — keeps /health cold-start fast.
    import core.weekly_training_review as _review  # lazy import — keeps /health cold-start fast
    try:
        today = datetime.now(ZoneInfo("Asia/Jerusalem")).date().isoformat()
        await _review.run_weekly_review(_application.bot, today)
        _log_cron_run("weekly-training-review", ok=True)
    except Exception:
        _log_cron_run("weekly-training-review", ok=False)
        raise
    return JSONResponse(content={"ok": True})


@app.post("/cron/healthkit-sync")
async def cron_healthkit_sync(request: Request) -> JSONResponse:
    """Push-driven webhook from the iPhone Shortcut "Lifesum closed" automation.

    Phase 19.1 — HEALTHKIT-04 / HEALTHKIT-05; CONTEXT.md D-09 / D-10.

    Upsert-only — judgment is deferred to the next */20 autonomous tick via
    ``meals_since_last_tick``. Deliberately does NOT depend on _application:
    no orchestrator, no Telegram, no LLM call. The route's only sink is
    ``MealStore.upsert``.

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


@app.post("/cron/strength-sync")
async def cron_strength_sync(request: Request) -> JSONResponse:
    """Receive Cloud Scheduler daily tick and run a bounded Hevy strength-sync batch.

    Schedule: 0 5 * * *  (Asia/Jerusalem)
    Authenticated via OIDC bearer token from Cloud Scheduler.

    Pull-only — no orchestrator, no Telegram, no LLM call. The only sink is
    StrengthSessionStore (via core.strength_ingest.run_one_batch). On the first
    run this backfills full Hevy history over several ticks; thereafter it applies
    incremental workout events. Re-run until the response shows done:true.

    Returns:
        JSONResponse: batch status dict (ok, mode, processed, [deleted], done).
    """
    await _verify_cron_request(request)
    import asyncio as _asyncio
    import core.strength_ingest as _strength
    try:
        loop = _asyncio.get_running_loop()
        result = await loop.run_in_executor(None, _strength.run_one_batch)
        _log_cron_run("strength-sync", ok=bool(result.get("ok")), backlog_done=result.get("done"))
        return JSONResponse(content=result)
    except Exception:
        _log_cron_run("strength-sync", ok=False)
        raise


@app.post("/cron/run-sync")
async def cron_run_sync(request: Request) -> JSONResponse:
    """Receive Cloud Scheduler daily tick and run a bounded Garmin run-detail batch.

    Schedule: 15 5 * * *  (Asia/Jerusalem) — staggered after strength-sync (05:00)
    to spread Garmin login load.
    Authenticated via OIDC bearer token from Cloud Scheduler.

    Pull-only — no orchestrator, no Telegram, no LLM call. The only sink is
    RunDetailStore (via core.run_ingest.run_one_batch). On the first run this
    backfills per-run detail over several ticks; thereafter it pulls detail for
    new runs only. Kept a SEPARATE job from strength-sync so a Garmin rate-limit
    never marks the Hevy sync failed. Re-run until the response shows done:true.

    Returns:
        JSONResponse: batch status dict (ok, mode, processed, remaining, done).
    """
    await _verify_cron_request(request)
    import asyncio as _asyncio
    import core.run_ingest as _run
    try:
        loop = _asyncio.get_running_loop()
        result = await loop.run_in_executor(None, _run.run_one_batch)
        _log_cron_run("run-sync", ok=bool(result.get("ok")), backlog_done=result.get("done"))
        return JSONResponse(content=result)
    except Exception:
        _log_cron_run("run-sync", ok=False)
        raise


@app.post("/cron/biometric-sync")
async def cron_biometric_sync(request: Request) -> JSONResponse:
    """Receive Cloud Scheduler daily tick and run a bounded Garmin biometrics batch.

    Schedule: 30 5 * * *  (Asia/Jerusalem) — staggered after run-sync (05:15)
    to spread Garmin login load.
    Authenticated via OIDC bearer token from Cloud Scheduler.

    Pull-only — no orchestrator, no Telegram, no LLM call. The only sink is
    the Postgres daily_biometrics table (via core.biometric_ingest.run_one_batch),
    which powers rolling HRV/resting-HR baselines. On the first run this
    backfills ~90 days over several ticks; thereafter it heals today+yesterday
    and pulls any missed days. Re-run until the response shows done:true.

    Returns:
        JSONResponse: batch status dict (ok, mode, processed, remaining, done).
    """
    await _verify_cron_request(request)
    import asyncio as _asyncio
    import core.biometric_ingest as _biometric
    try:
        loop = _asyncio.get_running_loop()
        result = await loop.run_in_executor(None, _biometric.run_one_batch)
        _log_cron_run("biometric-sync", ok=bool(result.get("ok")), backlog_done=result.get("done"))
        return JSONResponse(content=result)
    except Exception:
        _log_cron_run("biometric-sync", ok=False)
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


# --------------------------------------------------------------------------- #
# Hub auth routes — /api/auth/*                                               #
#                                                                             #
# These routes provide Google Sign-In session auth for the Klaus Hub (HUB-01).#
# They must be registered BEFORE the SPAStaticFiles mount (Pitfall 1).       #
# Existing /cron/* and /internal/* routes are untouched (HUB-04).            #
# --------------------------------------------------------------------------- #

@app.post("/api/auth/google")
async def api_auth_google(request: Request) -> JSONResponse:
    """Exchange a Google Identity Services ID token for a session cookie.

    Accepts JSON body: {"credential": "<GIS ID token>"}

    The GIS token is verified server-side via verify_oauth2_token (audience =
    GOOGLE_OAUTH_CLIENT_ID). On success, issues an itsdangerous HMAC-SHA256-signed
    httpOnly session cookie valid for 365 days (D-01 effectively permanent).

    Raises:
        HTTPException 401: Invalid or expired GIS token, or email not verified.
        HTTPException 403: Token valid but email is not the allowlisted account.
        HTTPException 500: GOOGLE_OAUTH_CLIENT_ID or HUB_SESSION_SECRET unset.
    """
    import interfaces.hub_auth as _hub_auth  # lazy import — Shared Pattern 5
    body = await request.json()
    credential = body.get("credential", "")
    if not credential:
        raise HTTPException(
            status_code=400,
            detail={"error": "Missing 'credential' in request body"},
        )

    email = _hub_auth.verify_google_id_token(credential)
    loop = asyncio.get_running_loop()
    session_version = await loop.run_in_executor(None, _hub_auth.get_session_version)
    cookie_value = _hub_auth.create_session_cookie(email, session_version)

    # The Set-Cookie MUST go on the response object we actually return. Setting it
    # on a separate injected `response: Response` and then returning a new
    # JSONResponse silently drops the header — FastAPI does not merge the two — so
    # the browser never stores the cookie and every subsequent /api/* call 401s.
    json_response = JSONResponse(content={"ok": True, "email": email})
    json_response.set_cookie(
        _hub_auth._COOKIE_NAME,
        cookie_value,
        max_age=365 * 86400,
        httponly=True,
        secure=True,
        samesite="strict",
        path="/",
    )
    return json_response


@app.post("/api/auth/logout")
async def api_auth_logout() -> JSONResponse:
    """Clear the session cookie (single-device sign-out, D-02).

    Does not bump session_version — only removes the cookie on this device.
    For sign-out-everywhere use /api/auth/revoke-all.
    """
    import interfaces.hub_auth as _hub_auth  # lazy import — Shared Pattern 5
    # delete_cookie must be on the returned response (see api_auth_google).
    json_response = JSONResponse(content={"ok": True})
    json_response.delete_cookie(_hub_auth._COOKIE_NAME, path="/")
    return json_response


@app.post("/api/auth/revoke-all")
async def api_auth_revoke_all(
    request: Request,
) -> JSONResponse:
    """Bump session_version to invalidate every previously-issued cookie (D-02).

    Also clears the cookie on the current device. After this call every existing
    session cookie (on every device) will fail the version check and return 401.

    Requires an active session cookie (Depends(require_hub_session) — enforced
    via the FastAPI dependency below). Intended for "lost phone" scenarios.

    Raises:
        HTTPException 401: No valid session cookie.
        HTTPException 500: HUB_SESSION_SECRET or Firestore unavailable.
    """
    import interfaces.hub_auth as _hub_auth  # lazy import — Shared Pattern 5
    _email: str = await _hub_auth.require_hub_session(request)  # auth gate
    loop = asyncio.get_running_loop()

    def _bump_version() -> None:
        project_id = os.environ.get("GCP_PROJECT_ID", "")
        database = os.environ.get("FIRESTORE_DATABASE", "(default)")
        if not project_id:
            raise ValueError("GCP_PROJECT_ID unset")
        from memory.firestore_db import UserProfileStore
        store = UserProfileStore(project_id=project_id, database=database)
        profile = store.load()
        new_version = int(profile.get("session_version", 0)) + 1
        store.update({"session_version": new_version})

    await loop.run_in_executor(None, _bump_version)
    # delete_cookie must be on the returned response (see api_auth_google).
    json_response = JSONResponse(content={"ok": True})
    json_response.delete_cookie(_hub_auth._COOKIE_NAME, path="/")
    return json_response


@app.get("/api/auth/me")
async def api_auth_me(request: Request) -> JSONResponse:
    """Return the signed-in email — used by the frontend to check session validity.

    Returns {"email": "..."} with HTTP 200 if the session cookie is valid.
    Returns HTTP 401 if no valid cookie is present.
    """
    import interfaces.hub_auth as _hub_auth  # lazy import — Shared Pattern 5
    email: str = await _hub_auth.require_hub_session(request)
    return JSONResponse(content={"email": email})


# --------------------------------------------------------------------------- #
# /api/today — read-only Today timeline aggregator (Plan 26-04, TIME-01..05, #
# TIME-08). Behind require_hub_session (HUB-01). All sync tool calls run via  #
# run_in_executor + asyncio.gather (Pitfall 2). Every Firestore-derived value #
# passes through _jsonsafe_doc before JSONResponse (Pitfall 4).               #
#                                                                              #
# MUST be registered BEFORE the SPA mount (Pitfall 1).                        #
# --------------------------------------------------------------------------- #

# Module-level in-process cache for Routes API results (TIME-05 / T-26-04-04).
# Key: (event_id, departure_iso) → (cache_epoch_seconds, result_dict | None)
# TTL: 30 minutes — avoids re-hitting the Routes API on D-05 refresh-on-focus.
_routes_cache: dict = {}
_ROUTES_CACHE_TTL_SECONDS = 1800  # 30 minutes


def _today_calendar(today_iso: str) -> dict:
    """Fetch today's calendar events — all-day pinned + timed sorted chronologically.

    TIME-01: all-day events are pinned at top; timed events sorted by start ascending.
    Returns {"all_day": [...], "timed": [...]} or {"all_day": [], "timed": []} on error.

    Each event dict carries: id, title, start, end, location (if present).
    """
    try:
        import core.auth_google as _auth  # lazy import — Shared Pattern 5
        from mcp_tools.calendar_tool import GoogleCalendarManager
        from datetime import date as _date, datetime as _dt
        from zoneinfo import ZoneInfo as _ZI

        tz = _ZI("Asia/Jerusalem")
        day_start = _dt.fromisoformat(today_iso).replace(
            hour=0, minute=0, second=0, tzinfo=tz
        )
        day_end = _dt.fromisoformat(today_iso).replace(
            hour=23, minute=59, second=59, tzinfo=tz
        )

        auth_manager = _auth.build_auth_manager_from_env()
        cal = GoogleCalendarManager(auth_manager)
        raw_events = cal.list_events(
            day_start.isoformat(),
            day_end.isoformat(),
            max_results=50,
        )

        all_day = []
        timed = []
        for ev in raw_events:
            start_str = ev.get("start", "")
            location = ev.get("location", "")
            entry = {
                "id": ev.get("id", ""),
                "title": ev.get("summary", ""),
                "start": start_str,
                "end": ev.get("end", ""),
            }
            if location:
                entry["location"] = location
            # All-day events have a date-only "start" (YYYY-MM-DD, length 10 with no 'T').
            if "T" not in start_str and len(start_str) == 10:
                # All-day events surface as title strings to match the frontend
                # contract (TodayData.calendar.all_day: string[]).
                all_day.append(entry["title"])
            else:
                timed.append(entry)

        # All-day events are pinned as-is; timed events are already sorted by startTime.
        return {"all_day": all_day, "timed": timed}
    except Exception:
        logger.warning("_today_calendar() failed", exc_info=True)
        return {"all_day": [], "timed": []}


def _today_garmin() -> dict | None:
    """Fetch today's Garmin morning stats — sleep, HRV, body battery, resting HR.

    TIME-02 stats half. Returns None when Garmin has not yet synced (D-06:
    client shows "Sleep stats syncing…").
    """
    try:
        from mcp_tools.garmin_tool import fetch_garmin_today  # lazy import
        data = fetch_garmin_today()
        # Field names match the frontend GarminStats contract
        # (frontend/src/api/today.ts): sleep (hours), hrv (ms), body_battery, resting_hr.
        return {
            "sleep": data.get("sleep_hours"),
            "hrv": data.get("hrv_overnight"),
            "body_battery": data.get("body_battery_morning"),
            "resting_hr": data.get("resting_hr"),
        }
    except Exception:
        logger.warning("_today_garmin() failed — Garmin may not have synced yet", exc_info=True)
        return None


def _today_weather() -> str | None:
    """Fetch a one-line weather summary string for Tel Aviv.

    TIME-02 weather half. Returns None on any error — client can show "—".
    """
    try:
        from mcp_tools.weather_tool import fetch_weather  # lazy import
        data = fetch_weather("Tel Aviv")
        current = data.get("current", {})
        today = data.get("today", {})
        cond = current.get("condition", "")
        temp = current.get("temp_c")
        high = today.get("max_c")
        low = today.get("min_c")
        rain = today.get("rain_chance")
        parts = []
        if cond:
            parts.append(cond)
        if temp is not None:
            parts.append(f"{temp}°C")
        if high is not None and low is not None:
            parts.append(f"H {high}°/L {low}°")
        if rain:
            parts.append(f"{rain}% rain")
        return ", ".join(parts) if parts else None
    except Exception:
        logger.warning("_today_weather() failed", exc_info=True)
        return None


_SLOT_LABELS: dict[str, str] = {
    "08:00": "Breakfast",
    "12:00": "Lunch",
    "20:00": "Dinner",
}


def _today_meals(today_iso: str) -> list[dict]:
    """Fetch today's meals as slot-label entries with macros.

    TIME-03: meals are rendered as canonical slot LABELS (Breakfast/Lunch/Dinner)
    derived from the canonical slot timestamps (08:00/12:00/20:00). Per CLAUDE.md §6
    invariant: these timestamps are NOT actual eating times — they are canonical
    slot identifiers written by the HealthKit/Lifesum pipeline. The returned dicts
    MUST NOT include any field named or framed as eaten_at or eating_time.
    """
    try:
        from memory.firestore_db import MealStore  # lazy import
        store = MealStore(
            project_id=os.environ.get("GCP_PROJECT_ID", ""),
            database=os.environ.get("FIRESTORE_DATABASE", "(default)"),
        )
        raw_meals = store.get_day(today_iso)
        result = []
        for meal in raw_meals:
            ts = meal.get("timestamp", "")
            # Derive the slot label from the HH:MM portion of the canonical timestamp.
            time_part = ""
            try:
                time_part = ts[11:16] if len(ts) >= 16 else ts[:5]
            except (IndexError, TypeError):
                pass
            slot_label = _SLOT_LABELS.get(time_part, "Meal")
            result.append({
                "slot_label": slot_label,         # canonical display label (TIME-03)
                # NOTE: deliberately no `slot_time` field on the wire — the client
                # contract (MealItem in today.ts) only declares slot_label + macros,
                # and per CLAUDE.md §6 the HH:MM slot identifier must never be
                # surfaced as (or risk being rendered as) an eating time.
                "macros": {
                    "kcal": meal.get("calories"),
                    "protein_g": meal.get("protein_g"),
                    "carbs_g": meal.get("carbs_g"),
                    "fat_g": meal.get("fat_g"),
                    "fiber_g": meal.get("fiber_g"),
                },
            })
        return result
    except Exception:
        logger.warning("_today_meals(%r) failed", today_iso, exc_info=True)
        return []


def _today_training(today_iso: str) -> dict | None:
    """Fetch today's training plan item + "Week N of 16 — {split name}" block context.

    TIME-04: uses BlockStore.get_current() (date-range resolution) mirroring the
    morning briefing block-fetch path (core/morning_briefing.py lines 399–420).
    Returns None when no block is active (pre/post-cycle) so the client can show
    the D-06 "no training block" placeholder.
    """
    try:
        from datetime import date as _date
        from memory.firestore_db import BlockStore, UserProfileStore  # lazy import

        project_id = os.environ.get("GCP_PROJECT_ID", "")
        database = os.environ.get("FIRESTORE_DATABASE", "(default)")

        block = None
        if project_id:
            bs = BlockStore(project_id=project_id, database=database)
            block = bs.get_current(today_iso)

        split_name = None
        if project_id:
            profile = UserProfileStore(project_id=project_id, database=database).load()
            # weekly_split is keyed by day name e.g. "Monday"
            try:
                from datetime import date as _d
                day_name = _d.fromisoformat(today_iso).strftime("%A")
                split_today = profile.get("weekly_split", {}).get(day_name) or {}
                am_slot = split_today.get("am") or {}
                split_name = am_slot.get("label")
            except Exception:
                pass

        if not block:
            return None

        # Derive week number the same way morning_briefing does — from plan_start_date 2026-06-21.
        try:
            plan_start = _date.fromisoformat("2026-06-21")
            today_date = _date.fromisoformat(today_iso)
            week_num = max(1, (today_date - plan_start).days // 7 + 1)
        except Exception:
            week_num = None

        block_context = None
        if week_num is not None:
            label = block.get("label") or "Training"
            if split_name:
                block_context = f"Week {week_num} of 16 — {split_name}"
            else:
                block_context = f"Week {week_num} of 16 — {label}"

        return {
            # "item" matches the frontend TrainingItem contract — the day's
            # workout name (split label, falling back to the block label).
            "item": split_name or block.get("label"),
            "block_context": block_context,
            "block_label": block.get("label"),
            "week_num": week_num,
            "split_name": split_name,
            "benchmark_due": block.get("benchmark_due", False),
        }
    except Exception:
        logger.warning("_today_training(%r) failed", today_iso, exc_info=True)
        return None


_COACH_NOTE_MAX_LEN = 280


def _sanitize_coach_note(note: str) -> str:
    """Strip control/format chars + inline Markdown markers and clamp.

    The coach note is the morning briefing's first line — first-party text, but
    it can carry Markdown (``#`` headers, ``**bold**``) or stray bidi/format
    control chars (LRM/RLM) that render oddly as a one-line plain-text note.
    React escapes HTML, so this is hardening, not XSS defense (CR-04).
    """
    import unicodedata
    from core.telegram_format import to_plain_text
    cleaned = "".join(
        ch for ch in str(note)
        if ch in ("\n", "\t") or not unicodedata.category(ch).startswith("C")
    )
    return to_plain_text(cleaned).lstrip("#").strip()[:_COACH_NOTE_MAX_LEN]


def _today_coach_note(today_iso: str) -> str | None:
    """Read the coach note written by the morning briefing from SelfStateStore.

    TIME-07 / D-06: returns `daily_note` ONLY when `daily_note_date` equals today's
    Asia/Jerusalem date. Returns None when the note is absent or stale — the client
    shows "Coach note coming after your morning briefing" per D-06.
    """
    try:
        from memory.firestore_db import SelfStateStore, _jsonsafe_doc as _jsd  # lazy import
        project_id = os.environ.get("GCP_PROJECT_ID", "")
        database = os.environ.get("FIRESTORE_DATABASE", "(default)")
        if not project_id:
            return None
        state_store = SelfStateStore(project_id=project_id, database=database)
        state = _jsd(state_store.get())
        note = state.get("daily_note")
        note_date = state.get("daily_note_date")
        if note and note_date == today_iso:
            return _sanitize_coach_note(note)
        return None
    except Exception:
        logger.warning("_today_coach_note() failed", exc_info=True)
        return None


def _today_routes(calendar: dict, today_iso: str) -> dict:
    """Attach leave_by + get_ready_at to timed events that have a location.

    TIME-05: calls routes_tool.get_travel_time() per located event. Results are
    cached 30 minutes in the module-level _routes_cache dict (T-26-04-04) so
    repeated /api/today calls (D-05 refresh-on-focus) don't exhaust Routes API quota.

    Returns the same calendar dict with leave_by/get_ready_at fields added to
    located timed events. All errors are swallowed per-event — one bad Routes call
    must not prevent the rest of the calendar from rendering.
    """
    import time as _time
    from datetime import datetime as _dt, timedelta as _td

    # Get Ready block before leaving (USER.md: 45 min prep before departure).
    _GET_READY_MINUTES = 45

    def _attach_leave_by(ev: dict, start_iso: str, duration_minutes) -> None:
        """Set ISO leave_by + get_ready_at on a located event (frontend contract).

        leave_by = event start − travel duration; get_ready_at = leave_by − 45 min.
        """
        if duration_minutes is None or not start_iso:
            return
        try:
            start_dt = _dt.fromisoformat(start_iso)
        except ValueError:
            return
        leave_by_dt = start_dt - _td(minutes=duration_minutes)
        ev["leave_by"] = leave_by_dt.isoformat()
        ev["get_ready_at"] = (leave_by_dt - _td(minutes=_GET_READY_MINUTES)).isoformat()

    try:
        from mcp_tools.routes_tool import get_travel_time  # lazy import

        now_epoch = _time.time()

        # Opportunistically evict expired keys (IN-03). The cache is only
        # TTL-checked on read, so without this it accumulates one stale entry
        # per past (event_id, start_iso) over a long-lived Cloud Run instance.
        # Pruning here (once per /api/today routes pass) bounds the growth to
        # roughly the set of events seen within one TTL window.
        expired = [
            k for k, (ts, _) in _routes_cache.items()
            if now_epoch - ts >= _ROUTES_CACHE_TTL_SECONDS
        ]
        for k in expired:
            del _routes_cache[k]

        timed_events = calendar.get("timed", [])
        for ev in timed_events:
            location = ev.get("location", "")
            if not location:
                continue
            event_id = ev.get("id", "")
            start_iso = ev.get("start", "")
            cache_key = (event_id, start_iso)

            # Check in-process TTL cache first (T-26-04-04).
            cached = _routes_cache.get(cache_key)
            if cached is not None:
                cache_ts, cached_result = cached
                if now_epoch - cache_ts < _ROUTES_CACHE_TTL_SECONDS:
                    if cached_result:
                        _attach_leave_by(ev, start_iso, cached_result.get("duration_minutes"))
                    continue

            try:
                result = get_travel_time(
                    origin="Tel Aviv",  # Amit's home base per USER.md
                    destination=location,
                    departure_time_iso=start_iso,
                )
                _routes_cache[cache_key] = (now_epoch, result)
                if result:
                    _attach_leave_by(ev, start_iso, result.get("duration_minutes"))
            except Exception:
                logger.warning(
                    "_today_routes: get_travel_time failed for event %s → %s",
                    event_id, location, exc_info=True
                )
                _routes_cache[cache_key] = (now_epoch, None)  # negative cache

        return calendar
    except Exception:
        logger.warning("_today_routes() failed", exc_info=True)
        return calendar


def _today_nutrition_totals(today_iso: str) -> dict:
    """Fetch today's nutrition running totals for the glance rail.

    TIME-08: uses MealStore.get_day_aggregate() to get server-computed totals.
    Returns {kcal, protein_g, carbs_g, fat_g, fiber_g} or {} when no meals logged.
    """
    try:
        from memory.firestore_db import MealStore  # lazy import
        store = MealStore(
            project_id=os.environ.get("GCP_PROJECT_ID", ""),
            database=os.environ.get("FIRESTORE_DATABASE", "(default)"),
        )
        agg = store.get_day_aggregate(today_iso)
        totals = agg.get("totals", {}) if agg else {}
        # Always return all five keys as numbers (default 0). A missing key or a
        # None value crashes the hub's NutritionStrip (.toFixed on undefined),
        # which blanks the whole SPA on a fresh day before any meal is logged.
        return {
            "kcal": totals.get("calories") or 0,
            "protein_g": totals.get("protein_g") or 0,
            "carbs_g": totals.get("carbs_g") or 0,
            "fat_g": totals.get("fat_g") or 0,
            "fiber_g": totals.get("fiber_g") or 0,
        }
    except Exception:
        logger.warning("_today_nutrition_totals(%r) failed", today_iso, exc_info=True)
        return {"kcal": 0, "protein_g": 0, "carbs_g": 0, "fat_g": 0, "fiber_g": 0}


@app.get("/api/today")
async def api_today(_email: str = Depends(require_hub_session)) -> JSONResponse:
    """Compose today's full timeline from all sources.

    TIME-01..05, TIME-08 — one endpoint that aggregates calendar events,
    Garmin stats, weather, meals (slot labels + macros), training plan +
    block context, traffic-aware leave-by times for located events, the
    morning coach note, and nutrition running totals.

    Invariants (CLAUDE.md §6):
      - All sync tool calls run via run_in_executor + asyncio.gather (Pitfall 2).
      - Every Firestore-derived value passes through _jsonsafe_doc (Pitfall 4).
      - Meals carry slot LABELS only — no eaten_at/eating_time fields (TIME-03).
      - coach_note is None before the morning briefing writes daily_note (D-06).

    Returns:
        JSONResponse: {"today", "calendar", "garmin", "weather", "meals",
                       "training", "coach_note", "nutrition_totals"}
    Raises:
        HTTPException 401: No valid session cookie (via require_hub_session).
    """
    from memory.firestore_db import _jsonsafe_doc  # lazy import — Shared Pattern 5

    loop = asyncio.get_running_loop()
    today_iso = datetime.now(ZoneInfo("Asia/Jerusalem")).date().isoformat()

    # Phase 1: run all independent sources concurrently (Pitfall 2 — never block the event loop).
    (
        calendar_data,
        garmin_data,
        weather_data,
        meal_data,
        training_data,
        nutrition_totals,
    ) = await asyncio.gather(
        loop.run_in_executor(None, _today_calendar, today_iso),
        loop.run_in_executor(None, _today_garmin),
        loop.run_in_executor(None, _today_weather),
        loop.run_in_executor(None, _today_meals, today_iso),
        loop.run_in_executor(None, _today_training, today_iso),
        loop.run_in_executor(None, _today_nutrition_totals, today_iso),
    )

    # Phase 2: routes depends on calendar output (per-event; cached TTL).
    calendar_with_routes = await loop.run_in_executor(
        None, _today_routes, calendar_data, today_iso
    )

    # Phase 3: coach note is a lightweight Firestore read (single cached doc).
    coach_note = await loop.run_in_executor(None, _today_coach_note, today_iso)

    # Assemble and JSON-safe the entire response (Pitfall 4 — _jsonsafe_doc on ALL Firestore data).
    payload = _jsonsafe_doc({
        "today": today_iso,
        "calendar": calendar_with_routes,
        "garmin": garmin_data,
        "weather": weather_data,
        "meals": meal_data,
        "training": training_data,
        "coach_note": coach_note,
        "nutrition_totals": nutrition_totals,
    })

    return JSONResponse(content=payload)


# --------------------------------------------------------------------------- #
# /api/health/* — read-only Health pages aggregators (Phase 30, HLTH-01..03). #
# Behind require_hub_session (HUB-01). All sync tool calls run via            #
# run_in_executor + asyncio.gather (Pitfall 2/3). Every Firestore/Postgres    #
# value passes through _jsonsafe_doc before JSONResponse (Pitfall 4).         #
#                                                                              #
# Range param is an ALLOWLIST, never int()-parsed from client input (Security #
# Domain V5 / T-30-02-01) — {7d,30d,90d,1y} maps to a fixed day count.        #
#                                                                              #
# MUST be registered BEFORE the SPA mount (Pitfall 1).                        #
# --------------------------------------------------------------------------- #

_VALID_RANGES: dict[str, int] = {"7d": 7, "30d": 30, "90d": 90, "1y": 365}
_WEEKLY_BUCKET_THRESHOLD_DAYS = 90  # D-07: >90d ranges bucket to weekly points
_MILEAGE_WEEKLY_THRESHOLD_DAYS = 7  # mileage buckets to weekly beyond the 7d view


def _resolve_range(range_param: str) -> int:
    """Map a client range string to a day count. Defaults to 30 on any invalid input.

    Allowlist `.get()` only — never `int()`-parse an arbitrary client-supplied
    value into date arithmetic (T-30-02-01).
    """
    return _VALID_RANGES.get(range_param, 30)


def _range_bounds(range_param: str) -> tuple[str, str]:
    """Resolve a range param to inclusive (start_iso, end_iso), Asia/Jerusalem 'today'."""
    days = _resolve_range(range_param)
    today = datetime.now(ZoneInfo("Asia/Jerusalem")).date()
    start = today - timedelta(days=days - 1)
    return start.isoformat(), today.isoformat()


def _week_axis_for_dates(date_isos: list[str]) -> list[tuple[tuple[int, int], str]]:
    """Ordered ``[((iso_year, iso_week), representative_label), ...]`` for a set of
    ISO dates — a shared weekly x-axis so series meant to be overlaid/index-aligned
    (HRV overnight+baseline, sleep score+duration) bucket onto the SAME weeks,
    with ``y=None`` filling any week a given series happens to lack (WR-04). Label
    = earliest date in each week, matching ``_weekly_bucket_points``.
    """
    from datetime import date as _date

    label: dict[tuple[int, int], str] = {}
    for x in date_isos:
        try:
            key = _date.fromisoformat(x).isocalendar()[:2]
        except (ValueError, TypeError):
            continue
        if key not in label or x < label[key]:
            label[key] = x
    return [(k, label[k]) for k in sorted(label.keys())]


def _weekly_bucket_points(
    points: list[dict],
    agg: str = "avg",
    week_axis: list[tuple[tuple[int, int], str]] | None = None,
) -> list[dict]:
    """Bucket ``{"x": date_iso, "y": number|None}`` points into weekly points.

    Keyed on ``date.fromisoformat(x).isocalendar()`` (year, week) per D-07 — call
    only when the resolved day count exceeds _WEEKLY_BUCKET_THRESHOLD_DAYS. Points
    with ``y=None`` never contribute to a bucket's aggregate (D-08 — a gap must
    never masquerade as a zero). agg="sum" sums the week's values instead of
    averaging (used for weekly mileage).

    Without ``week_axis`` a week with zero non-null contributions is omitted
    entirely (stays a gap). With ``week_axis`` (a fixed ordered week list from
    ``_week_axis_for_dates``) the output has exactly one point per axis week — the
    aggregate, or ``y=None`` for an empty week — so multiple series bucketed
    against the SAME axis stay index-aligned when overlaid (WR-04).
    """
    from datetime import date as _date

    buckets: dict[tuple[int, int], list[float]] = {}
    week_label: dict[tuple[int, int], str] = {}
    for p in points:
        y = p.get("y")
        if y is None:
            continue
        try:
            d = _date.fromisoformat(p["x"])
        except (KeyError, ValueError, TypeError):
            continue
        key = d.isocalendar()[:2]
        buckets.setdefault(key, []).append(float(y))
        if key not in week_label or p["x"] < week_label[key]:
            week_label[key] = p["x"]

    def _agg(vals: list[float]) -> float:
        return round(sum(vals) if agg == "sum" else sum(vals) / len(vals), 1)

    if week_axis is not None:
        return [
            {"x": lbl, "y": _agg(buckets[key]) if buckets.get(key) else None}
            for key, lbl in week_axis
        ]

    out = []
    for key in sorted(buckets.keys()):
        out.append({"x": week_label[key], "y": _agg(buckets[key])})
    return out


# --------------------------------------------------------------------------- #
# GET /api/health/training (HLTH-01) — mixed strength+run+benchmark log,      #
# block dividers, two trend series.                                          #
# --------------------------------------------------------------------------- #


def _health_training_strength(start: str, end: str) -> list[dict]:
    """Strength sessions in [start, end], newest-first. Never raises — [] on error."""
    try:
        from memory.firestore_db import StrengthSessionStore  # lazy import
        store = StrengthSessionStore(
            project_id=os.environ.get("GCP_PROJECT_ID", ""),
            database=os.environ.get("FIRESTORE_DATABASE", "(default)"),
        )
        return store.get_range(start, end)
    except Exception:
        logger.warning("_health_training_strength(%r, %r) failed", start, end, exc_info=True)
        return []


def _health_training_runs(start: str, end: str) -> list[dict]:
    """Runs in [start, end], newest-first. Never raises — [] on error."""
    try:
        from memory.firestore_db import RunDetailStore  # lazy import
        store = RunDetailStore(
            project_id=os.environ.get("GCP_PROJECT_ID", ""),
            database=os.environ.get("FIRESTORE_DATABASE", "(default)"),
        )
        return store.get_range(start, end)
    except Exception:
        logger.warning("_health_training_runs(%r, %r) failed", start, end, exc_info=True)
        return []


def _health_training_benchmarks(start: str, end: str) -> list[dict]:
    """Benchmarks in [start, end], each augmented with `previous_value`.

    previous_value is the prior same-facet result (via get_facet_history), i.e.
    the newest entry strictly older than this one's date — None when no prior
    exists. Never raises — [] on error.
    """
    try:
        from memory.firestore_db import BenchmarkStore  # lazy import
        store = BenchmarkStore(
            project_id=os.environ.get("GCP_PROJECT_ID", ""),
            database=os.environ.get("FIRESTORE_DATABASE", "(default)"),
        )
        benchmarks = store.get_range(start, end)
        result = []
        for b in benchmarks:
            facet = b.get("facet")
            prev_value = None
            if facet:
                # get_facet_history is newest-first; the first entry strictly
                # older than this benchmark's date is the "previous" result.
                history = store.get_facet_history(facet, n=1000)
                this_date = b.get("date", "")
                for h in history:
                    if h.get("date", "") < this_date:
                        prev_value = h.get("value")
                        break
            result.append({**b, "previous_value": prev_value})
        return result
    except Exception:
        logger.warning(
            "_health_training_benchmarks(%r, %r) failed", start, end, exc_info=True
        )
        return []


def _health_training_blocks() -> list[dict]:
    """All training blocks, sorted start_date ascending, each carrying a
    sequential 1-based block_number (BlockStore stores no number field) and its
    `label` (NOT `block_name`, which does not exist). Never raises — [] on error.
    """
    try:
        from memory.firestore_db import BlockStore  # lazy import
        store = BlockStore(
            project_id=os.environ.get("GCP_PROJECT_ID", ""),
            database=os.environ.get("FIRESTORE_DATABASE", "(default)"),
        )
        blocks = store.get_all()
        blocks_sorted = sorted(blocks, key=lambda b: b.get("start_date", ""))
        return [
            {**b, "block_number": i + 1, "label": b.get("label")}
            for i, b in enumerate(blocks_sorted)
        ]
    except Exception:
        logger.warning("_health_training_blocks() failed", exc_info=True)
        return []


@app.get("/api/health/training")
async def api_health_training(
    range: str = "30d",
    _email: str = Depends(require_hub_session),
) -> JSONResponse:
    """Mixed strength+run+benchmark training log + block dividers + trends.

    HLTH-01: one endpoint composing StrengthSessionStore/RunDetailStore/
    BenchmarkStore/BlockStore into a reverse-chronological interleaved log
    tagged by `modality`, plus two {x,y} trend series (run_mileage,
    run_trend) — daily for range<=90d, weekly-bucketed for >90d (D-07).

    Returns:
        JSONResponse: {"range", "entries", "blocks", "run_mileage", "run_trend"}
    Raises:
        HTTPException 401: No valid session cookie (via require_hub_session).
    """
    from memory.firestore_db import _jsonsafe_doc  # lazy import — Shared Pattern 5

    loop = asyncio.get_running_loop()
    start_iso, end_iso = _range_bounds(range)
    days = _resolve_range(range)

    strength, runs, benchmarks, blocks = await asyncio.gather(
        loop.run_in_executor(None, _health_training_strength, start_iso, end_iso),
        loop.run_in_executor(None, _health_training_runs, start_iso, end_iso),
        loop.run_in_executor(None, _health_training_benchmarks, start_iso, end_iso),
        loop.run_in_executor(None, _health_training_blocks),
    )

    entries = (
        [{**s, "modality": "strength"} for s in strength]
        + [{**r, "modality": "run"} for r in runs]
        + [{**b, "modality": "benchmark"} for b in benchmarks]
    )
    entries.sort(key=lambda e: e.get("date", ""), reverse=True)

    # Trend 1: run mileage — distance_m summed per date, surfaced in km. Running
    # mileage progression is the volume signal that matters here (strength
    # tonnage was dropped as low-signal per UAT); strength sessions still appear
    # in the interleaved log below.
    mileage_daily: dict[str, float] = {}
    for r in runs:
        d = r.get("date")
        dist_m = r.get("distance_m")
        if not d or dist_m is None:
            continue
        mileage_daily[d] = mileage_daily.get(d, 0.0) + dist_m
    mileage_points = [
        {"x": d, "y": round(m / 1000.0, 2)} for d, m in sorted(mileage_daily.items())
    ]

    # Trend 2: run pace — avg_pace_sec_per_km averaged per date (lower = faster).
    run_daily: dict[str, list[float]] = {}
    for r in runs:
        d = r.get("date")
        pace = r.get("avg_pace_sec_per_km")
        if not d or pace is None:
            continue
        run_daily.setdefault(d, []).append(pace)
    run_points = [
        {"x": d, "y": round(sum(vals) / len(vals), 1)}
        for d, vals in sorted(run_daily.items())
    ]

    # Mileage buckets to weekly beyond the 7-day view — a weekly progression is
    # the useful read at 30d/90d/1y, while 7d stays daily. Pace keeps the
    # standard >90d weekly threshold (D-07).
    run_mileage = (
        _weekly_bucket_points(mileage_points, agg="sum")
        if days > _MILEAGE_WEEKLY_THRESHOLD_DAYS
        else mileage_points
    )
    run_trend = (
        _weekly_bucket_points(run_points, agg="avg")
        if days > _WEEKLY_BUCKET_THRESHOLD_DAYS
        else run_points
    )

    payload = _jsonsafe_doc({
        "range": range,
        "entries": entries,
        "blocks": blocks,
        "run_mileage": run_mileage,
        "run_trend": run_trend,
    })
    return JSONResponse(content=payload)


# --------------------------------------------------------------------------- #
# GET /api/health/nutrition (HLTH-02) — macro trend series, slot-adherence    #
# grid, targets. The day-series math is EXTRACTED from                       #
# core.tools._handle_fetch_nutrition_trend (_compute_nutrition_averages /     #
# _nutrition_targets_and_protein_ratio) — shared, not reimplemented, so the   #
# chat tool and this route can never drift (RESEARCH.md Anti-Patterns).      #
# --------------------------------------------------------------------------- #

_NUTRITION_MACRO_KEYS = ("calories", "protein_g", "carbs_g", "fat_g", "fiber_g")

_SLOT_LABELS_HEALTH: dict[str, str] = _SLOT_LABELS  # alias — same canonical mapping as _today_meals

# Single per-day read pass cache (Pitfall 1 — MealStore has no range-read method;
# a 1y nutrition request would otherwise be ~365 sequential Firestore reads on
# every request). Reuses the exact TTL-dict shape as _routes_cache (T-30-02-03).
_nutrition_daily_cache: dict = {}


def _slot_label_for_meal(meal: dict) -> str:
    """Derive the canonical fueling-slot LABEL from a meal's timestamp.

    Mirrors _today_meals' inline slot-label derivation. Per CLAUDE.md §6: the
    HH:MM portion is a canonical slot identifier, NOT an eating time — only the
    LABEL (e.g. "Breakfast") may ever appear on the wire, never the HH:MM itself.
    """
    ts = meal.get("timestamp", "")
    try:
        time_part = ts[11:16] if len(ts) >= 16 else ts[:5]
    except (IndexError, TypeError):
        time_part = ""
    return _SLOT_LABELS_HEALTH.get(time_part, "Meal")


def _health_nutrition_daily(start: str, end: str) -> dict:
    """Single per-day Firestore pass feeding BOTH the macro series and the
    slot-adherence matrix (RESEARCH.md Pitfall 1 — never two independent
    ~365-read loops over the same range). TTL-cached per (start, end) so a
    repeated 1y request is served from cache (T-30-02-03 / mandatory for >90d).

    Returns {"day_records": [...], "missing_dates": [...], "slot_records": [...]}.
    day_records only contains dates WITH logged meals (D-08 — an unlogged day is
    a gap, never a zero-fill). Never raises — degrades to all-empty on error.
    """
    import time as _time
    from datetime import date as _date, timedelta as _td

    cache_key = (start, end)
    now_epoch = _time.time()
    cached = _nutrition_daily_cache.get(cache_key)
    if cached is not None:
        cache_ts, cached_result = cached
        if now_epoch - cache_ts < _ROUTES_CACHE_TTL_SECONDS:
            return cached_result

    try:
        from memory.firestore_db import MealStore  # lazy import
        store = MealStore(
            project_id=os.environ.get("GCP_PROJECT_ID", ""),
            database=os.environ.get("FIRESTORE_DATABASE", "(default)"),
        )
        start_d = _date.fromisoformat(start)
        end_d = _date.fromisoformat(end)
        dates = []
        d = start_d
        while d <= end_d:
            dates.append(d.isoformat())
            d += _td(days=1)

        day_records: list[dict] = []
        missing_dates: list[str] = []
        slot_records: list[dict] = []
        for d_iso in dates:
            meals = store.get_day(d_iso)
            if not meals:
                missing_dates.append(d_iso)  # D-08 — a gap, never a zero-fill
                continue
            totals = {
                k: sum(m.get(k) or 0 for m in meals) for k in _NUTRITION_MACRO_KEYS
            }
            day_records.append({"date": d_iso, "meal_count": len(meals), **totals})
            seen_slots: set[str] = set()
            for m in meals:
                label = _slot_label_for_meal(m)
                if label and label not in seen_slots:
                    seen_slots.add(label)
                    slot_records.append({"date": d_iso, "slot_label": label})

        result = {
            "day_records": day_records,
            "missing_dates": missing_dates,
            "slot_records": slot_records,
        }
    except Exception:
        logger.warning("_health_nutrition_daily(%r, %r) failed", start, end, exc_info=True)
        # Do NOT cache the degraded result — a transient Firestore error would
        # otherwise poison the nutrition page for the full TTL window (WR-01).
        return {"day_records": [], "missing_dates": [], "slot_records": []}

    _nutrition_daily_cache[cache_key] = (now_epoch, result)
    return result


def _health_nutrition_profile() -> dict:
    """UserProfileStore.load() — nutrition_targets + bodyweight_kg. {} on error."""
    try:
        from memory.firestore_db import UserProfileStore  # lazy import
        return UserProfileStore(
            project_id=os.environ.get("GCP_PROJECT_ID", ""),
            database=os.environ.get("FIRESTORE_DATABASE", "(default)"),
        ).load()
    except Exception:
        logger.warning("_health_nutrition_profile() failed", exc_info=True)
        return {}


def _resolve_calories_target(targets: dict) -> tuple[float | None, bool]:
    """Return (calories_target, derived_bool).

    Reads a stored `calories` key if present; else derives
    protein_g*4 + carbs_g*4 + fat_g*9 from whatever macro-gram target keys exist
    and tags the result as derived (RESEARCH.md Open Question A4 — the live
    `nutrition_targets` profile has NO literal `calories` key). Returns
    (None, False) when neither a stored key nor any macro-gram key exists —
    never silently omits the target line when derivation is possible.
    """
    if not targets:
        return None, False
    if targets.get("calories") is not None:
        return targets["calories"], False
    protein_g = targets.get("protein_g")
    carbs_g = targets.get("carbs_g")
    fat_g = targets.get("fat_g")
    if protein_g is None and carbs_g is None and fat_g is None:
        return None, False
    calories = (protein_g or 0) * 4 + (carbs_g or 0) * 4 + (fat_g or 0) * 9
    return round(calories, 0), True


def _health_nutrition_slots(daily: dict) -> dict:
    """Shape slot_records (from _health_nutrition_daily's single pass) into the
    D-13 per-slot-per-day hit matrix. Issues NO additional Firestore reads.

    Cells are keyed on slot LABEL only — never a derived clock time (CLAUDE.md §6).
    """
    slot_records = daily["slot_records"]
    labels = sorted({r["slot_label"] for r in slot_records})
    dates = sorted({r["date"] for r in slot_records})
    hit_set = {(r["date"], r["slot_label"]) for r in slot_records}
    grid = [
        {
            "slot_label": label,
            "cells": [{"date": d, "hit": (d, label) in hit_set} for d in dates],
        }
        for label in labels
    ]
    return {"slot_labels": labels, "dates": dates, "grid": grid}


@app.get("/api/health/nutrition")
async def api_health_nutrition(
    range: str = "30d",
    _email: str = Depends(require_hub_session),
) -> JSONResponse:
    """Per-day (or weekly >90d) macro series + slot-adherence grid + targets.

    HLTH-02: macro series/averages/targets/protein-g-per-kg math is shared with
    core.tools._handle_fetch_nutrition_trend (never reimplemented — RESEARCH.md
    Anti-Patterns). Unlogged days are gaps in `missing_dates`, never zero-filled
    (D-08). Slot adherence is keyed on slot LABEL only — no clock time on the
    wire (CLAUDE.md §6). The per-day Firestore pass is shared between the macro
    series and the slot grid and TTL-cached for >90d ranges (Pitfall 1).

    Returns:
        JSONResponse: {"range", "series", "missing_dates", "averages", "targets",
                       "avg_protein_g_per_kg", "slot_adherence"}
    Raises:
        HTTPException 401: No valid session cookie (via require_hub_session).
    """
    from memory.firestore_db import _jsonsafe_doc  # lazy import — Shared Pattern 5
    from core.tools import (  # lazy import — Shared Pattern 5
        _compute_nutrition_averages,
        _nutrition_targets_and_protein_ratio,
    )

    loop = asyncio.get_running_loop()
    start_iso, end_iso = _range_bounds(range)
    days = _resolve_range(range)

    daily, profile = await asyncio.gather(
        loop.run_in_executor(None, _health_nutrition_daily, start_iso, end_iso),
        loop.run_in_executor(None, _health_nutrition_profile),
    )

    day_records = daily["day_records"]
    missing_dates = daily.get("missing_dates", [])
    # Build each series over the FULL date range so an unlogged day is an
    # explicit {y: null} gap the LineChart splits on (D-08) — NOT an absent
    # point the line would bridge across. `missing_dates` alone is insufficient:
    # nothing on the client reconstructs the gaps from it (CR-01).
    record_by_date = {r["date"]: r for r in day_records}
    all_dates = sorted(record_by_date.keys() | set(missing_dates))
    points_by_key: dict[str, list[dict]] = {}
    for key in _NUTRITION_MACRO_KEYS:
        pts = [
            {"x": d, "y": record_by_date[d].get(key) if d in record_by_date else None}
            for d in all_dates
        ]
        if days > _WEEKLY_BUCKET_THRESHOLD_DAYS:
            pts = _weekly_bucket_points(pts, agg="avg")
        points_by_key[key] = pts

    averages = _compute_nutrition_averages(day_records, _NUTRITION_MACRO_KEYS)
    extra = _nutrition_targets_and_protein_ratio(profile, averages)
    targets = dict(extra.get("targets") or {})

    calories_target, derived = _resolve_calories_target(targets)
    if calories_target is not None:
        targets["calories"] = calories_target
        if derived:
            targets["calories_target_derived"] = True

    slot_adherence = _health_nutrition_slots(daily)

    payload = _jsonsafe_doc({
        "range": range,
        "series": points_by_key,
        "missing_dates": daily["missing_dates"],
        "averages": averages,
        "targets": targets,
        "avg_protein_g_per_kg": extra.get("avg_protein_g_per_kg"),
        "slot_adherence": slot_adherence,
    })
    return JSONResponse(content=payload)


# --------------------------------------------------------------------------- #
# GET /api/health/sleep (HLTH-03) — HRV/sleep/body-battery trend series +     #
# header stat row + pipeline_active guard. Postgres read is ALWAYS wrapped    #
# in run_in_executor (Pitfall 3 — the 2026-06-24 weekly-review-500 incident   #
# class: a synchronous psycopg2 call inside async def starves the event loop).#
# --------------------------------------------------------------------------- #


def _health_sleep_data(start: str, end: str) -> list[dict]:
    """daily_biometrics rows in [start, end], oldest-first. Never raises — [] on error.

    Thin wrapper over core.health_reads.fetch_biometric_range (itself never
    raises) so this module keeps the same lazy-import + try/except discipline
    as every other _health_* helper in this file.
    """
    try:
        from core.health_reads import fetch_biometric_range  # lazy import
        return fetch_biometric_range(start, end)
    except Exception:
        logger.warning("_health_sleep_data(%r, %r) failed", start, end, exc_info=True)
        return []


def _health_sleep_pipeline_active() -> bool:
    """True iff daily_biometrics has EVER had a row — distinct from "no rows in
    this specific range" (RESEARCH.md Pitfall 4 / D-19). Reuses
    fetch_biometric_range with a maximally wide bound rather than adding a new
    Postgres reader. Never raises — False on error.
    """
    try:
        from core.health_reads import fetch_biometric_range  # lazy import
        return bool(fetch_biometric_range("1970-01-01", "2099-12-31"))
    except Exception:
        logger.warning("_health_sleep_pipeline_active() failed", exc_info=True)
        return False


def _hrv_baseline_with_fallback(rows: list[dict]) -> dict[str, float | None]:
    """Per-date HRV baseline: prefer the stored `hrv_baseline` column (Garmin's
    own rolling weekly average); when that column is sparse (fewer than half of
    the given rows have a value), fall back to a rolling median of
    `hrv_overnight` over the prior <=7 days — mirrors
    core.recovery_metrics.compute_recovery_deviation's own fallback
    (`median(prior_hrv)`), reused rather than reinvented (RESEARCH.md Pitfall 5).

    Args:
        rows: daily_biometrics rows, sorted ascending by date (fetch_biometric_range's
              contract).

    Returns:
        {date: baseline_value_or_None} — one entry per row.
    """
    from statistics import median

    if not rows:
        return {}

    non_null = sum(1 for r in rows if r.get("hrv_baseline") is not None)
    sparse = non_null < (len(rows) / 2)

    out: dict[str, float | None] = {}
    if not sparse:
        for r in rows:
            out[r["date"]] = r.get("hrv_baseline")
        return out

    for i, r in enumerate(rows):
        prior = [
            rr["hrv_overnight"]
            for rr in rows[max(0, i - 7):i]
            if rr.get("hrv_overnight") is not None
        ]
        out[r["date"]] = round(median(prior), 1) if prior else None
    return out


@app.get("/api/health/sleep")
async def api_health_sleep(
    range: str = "30d",
    _email: str = Depends(require_hub_session),
) -> JSONResponse:
    """HRV/sleep/body-battery trend series + header stat row + pipeline_active.

    HLTH-03: reads Postgres daily_biometrics via run_in_executor (Pitfall 3 —
    never call psycopg2 synchronously inside async def). Missing days are
    gaps (null), never zero (D-08 — watch-not-worn != HRV of 0). `pipeline_active`
    is true iff the table has EVER had a row, distinct from "no rows in this
    specific range" (D-19 pipeline-not-live guard). range=1y (>90d) returns
    weekly-bucketed series (D-07). hrv_baseline falls back to a rolling median
    of hrv_overnight when the stored column is sparse (Pitfall 5).

    Returns:
        JSONResponse: {"range", "series", "header_stats", "pipeline_active"}
    Raises:
        HTTPException 401: No valid session cookie (via require_hub_session).
    """
    from memory.firestore_db import _jsonsafe_doc  # lazy import — Shared Pattern 5

    loop = asyncio.get_running_loop()
    start_iso, end_iso = _range_bounds(range)
    days = _resolve_range(range)

    rows, pipeline_active = await asyncio.gather(
        loop.run_in_executor(None, _health_sleep_data, start_iso, end_iso),
        loop.run_in_executor(None, _health_sleep_pipeline_active),
    )

    rows_sorted = sorted(rows, key=lambda r: r.get("date", ""))
    baseline_by_date = _hrv_baseline_with_fallback(rows_sorted)

    # WR-04: bucket every sleep series onto ONE shared week axis so the overlaid
    # pairs (HRV overnight+baseline, sleep score+duration) stay index-aligned —
    # an empty week in one series becomes a null point, never a dropped index
    # that would slide the dashed baseline off the overnight line.
    week_axis = (
        _week_axis_for_dates([r["date"] for r in rows_sorted])
        if days > _WEEKLY_BUCKET_THRESHOLD_DAYS
        else None
    )

    metric_keys = ["hrv_overnight", "sleep_score", "sleep_duration", "body_battery_max"]
    series: dict[str, list[dict]] = {}
    for key in metric_keys:
        pts = [{"x": r["date"], "y": r.get(key)} for r in rows_sorted]
        if week_axis is not None:
            pts = _weekly_bucket_points(pts, agg="avg", week_axis=week_axis)
        series[key] = pts

    baseline_points = [
        {"x": r["date"], "y": baseline_by_date.get(r["date"])} for r in rows_sorted
    ]
    if week_axis is not None:
        baseline_points = _weekly_bucket_points(baseline_points, agg="avg", week_axis=week_axis)
    series["hrv_baseline"] = baseline_points

    header_stats = None
    if rows_sorted:
        latest = rows_sorted[-1]
        header_stats = {
            "date": latest.get("date"),
            "hrv_overnight": latest.get("hrv_overnight"),
            "sleep_score": latest.get("sleep_score"),
            "body_battery_max": latest.get("body_battery_max"),
            "resting_hr": latest.get("resting_hr"),
            "training_readiness": latest.get("training_readiness"),
        }

    payload = _jsonsafe_doc({
        "range": range,
        "series": series,
        "header_stats": header_stats,
        "pipeline_active": pipeline_active,
    })
    return JSONResponse(content=payload)


# --------------------------------------------------------------------------- #
# Hub chat routes — /api/chat (Plan 26-05, CHAT-01..04)                       #
#                                                                             #
# POST /api/chat — append user message to shared Firestore conversation and   #
# enqueue the agent turn via Cloud Tasks full-CPU path (D-09 / CLAUDE.md:     #
# never a Starlette BackgroundTask). CHAT-01 / CHAT-02.                       #
#                                                                             #
# GET /api/chat/messages — return the full conversation window for polling    #
# and fast first paint (D-08 / CHAT-03 / CHAT-04).                           #
#                                                                             #
# POST /internal/process-hub-message — OIDC-gated Cloud Tasks target; runs   #
# the agent turn inside the tracked request with full CPU, appends the        #
# assistant reply to the shared conversation without a Telegram send (D-09).  #
#                                                                             #
# All three routes MUST be registered BEFORE the SPA mount (Pitfall 1).      #
# --------------------------------------------------------------------------- #


# POST /api/chat body validation (ASVS V5: non-empty, max length) is done
# inline in api_chat_send — web_server.py does not import pydantic at module
# level, and the check is equivalent (non-empty + max-length on the raw dict).
_CHAT_CONTENT_MAX_LEN = 4000  # ASVS V5 — reasonable upper bound for one message


# Process-lifetime cache for _resolve_hub_user_id (WR-06). The hub maps to a
# single, effectively-static account for the lifetime of the Cloud Run
# instance (set once by the 26-02 operator step) — re-resolving it on every
# chat send and every 2.5s poll costs a Firestore read + a lazy import for no
# benefit. None means "not yet resolved"; a successful resolution is cached
# and reused. A failed resolution (ValueError) is NOT cached, so a transient
# Firestore outage doesn't permanently wedge the hub once it recovers.
_hub_user_id_cache: int | None = None


def _resolve_hub_user_id() -> int:
    """Resolve the Telegram user_id to key FirestoreConversationStore.

    Reads UserProfileStore.telegram_user_id (set by 26-02 operator step).
    Falls back to the first id in TELEGRAM_ALLOWED_USER_IDS — the same
    convention used by core/autonomous.py and core/scheduled_message.py.

    WHY this approach: the hub always operates on Amit's single account; there
    is no per-hub-session telegram_user_id mapping needed for v5.0.

    The resolved value is memoized at module scope for the lifetime of the
    process (WR-06) — this is called on every /api/chat send and every
    2.5s /api/chat/messages poll, and the mapping never changes at runtime.
    """
    global _hub_user_id_cache
    if _hub_user_id_cache is not None:
        return _hub_user_id_cache

    try:
        project_id = os.environ.get("GCP_PROJECT_ID", "")
        database = os.environ.get("FIRESTORE_DATABASE", "(default)")
        if project_id:
            from memory.firestore_db import UserProfileStore  # lazy import
            profile = UserProfileStore(project_id=project_id, database=database).load()
            tid = profile.get("telegram_user_id")
            if tid is not None:
                _hub_user_id_cache = int(tid)
                return _hub_user_id_cache
    except Exception:
        logger.warning("_resolve_hub_user_id: UserProfileStore lookup failed", exc_info=True)

    # Fallback: first entry of TELEGRAM_ALLOWED_USER_IDS (mirrors autonomous.py convention)
    raw = os.environ.get("TELEGRAM_ALLOWED_USER_IDS", "").split(",")[0].strip()
    if raw:
        _hub_user_id_cache = int(raw)
        return _hub_user_id_cache
    raise ValueError("Cannot resolve hub user_id: telegram_user_id not in profile and TELEGRAM_ALLOWED_USER_IDS unset")


@app.post("/api/chat")
async def api_chat_send(
    request: Request,
    _email: str = Depends(require_hub_session),
) -> JSONResponse:
    """Receive a hub chat message and enqueue the agent turn via Cloud Tasks.

    CHAT-01: appends the user message to the shared FirestoreConversationStore
    keyed on telegram_user_id — the same document the Telegram path uses —
    so hub + Telegram share one continuous conversation (one Klaus).

    CHAT-02: the agent turn is enqueued to Cloud Tasks via enqueue_hub_message
    which targets /internal/process-hub-message. NEVER runs the agent turn in
    a Starlette BackgroundTask (D-09 / CLAUDE.md invariant: CPU-throttled after
    response → 18-minute replies observed 2026-06-12).

    Returns:
        JSONResponse: {"ok": True} on success.
        JSONResponse: {"ok": False, "error": "..."} with HTTP 503 if Cloud
                      Tasks enqueue fails. Clients should retry.

    Raises:
        HTTPException 400: Missing or empty content, or content too long.
        HTTPException 401: No valid session cookie (via require_hub_session).
    """
    body = await request.json()
    content = body.get("content", "")

    # Input validation (ASVS V5 / T-26-05-04)
    if not content or not content.strip():
        raise HTTPException(status_code=400, detail={"error": "content must be non-empty"})
    if len(content) > _CHAT_CONTENT_MAX_LEN:
        raise HTTPException(
            status_code=400,
            detail={"error": f"content exceeds maximum length of {_CHAT_CONTENT_MAX_LEN} characters"},
        )

    # Resolve the hub user_id (keyed on telegram_user_id per CHAT-01)
    loop = asyncio.get_running_loop()
    try:
        user_id = await loop.run_in_executor(None, _resolve_hub_user_id)
    except ValueError as exc:
        logger.error("api_chat_send: cannot resolve user_id: %s", exc)
        raise HTTPException(status_code=500, detail={"error": "Server misconfigured: user identity unresolvable"})

    # Enqueue the agent turn via Cloud Tasks full-CPU path (CHAT-01/02 / D-09).
    # We do NOT append the user message here: the worker's handle_message
    # (core/main.py) appends BOTH the user turn and the assistant reply to the
    # shared FirestoreConversationStore. Appending here too would double the user
    # turn; appending BEFORE a failed enqueue would strand a user message with no
    # agent turn → a permanent "Klaus is thinking…" plus a double-send on retry
    # (CR-03). Enqueue is the single atomic effect — on failure nothing is
    # persisted and the client safely retries.
    # NEVER use background_tasks.add_task — it runs after the response and gets
    # CPU-throttled by Cloud Run.
    ok = await loop.run_in_executor(None, enqueue_hub_message, content, user_id)
    if not ok:
        logger.error("api_chat_send: enqueue_hub_message returned False (user_id=%s)", user_id)
        return JSONResponse(
            status_code=503,
            content={"ok": False, "error": "Could not dispatch the message — please retry"},
        )

    return JSONResponse(content={"ok": True})


@app.get("/api/chat/messages")
async def api_chat_messages(
    chat_visible: int = 0,
    limit: int = Query(50, ge=1, le=200),
    before: int | None = Query(None, ge=0),
    _email: str = Depends(require_hub_session),
) -> JSONResponse:
    """Return a page of the conversation for polling / infinite scroll-up.

    UAT gap-closure (2026-07): previously this route returned the ENTIRE
    stored window (up to max_messages ~100) on every 2.5s poll, and the
    client sliced the newest 50 client-side. That shipped the whole history
    over the wire on every poll tick. Now the server does the windowing:

      - No `before`: return the newest `limit` messages (the poll tail).
      - `before=<seq>`: return the `limit` messages immediately OLDER than
        that seq (message list "load earlier messages" / scroll-to-top).

    `has_more` in the response tells the client whether an even-older page
    exists so it can stop trying once the true start of history is reached.

    Storage note: FirestoreConversationStore keeps the whole conversation as
    ONE array field on a single document (see memory/firestore_conversation
    .py) — there is no native Firestore query/pagination primitive to push
    this down to (it isn't a per-message subcollection). So this route still
    reads the full stored array (bounded at max_messages, currently 100) in
    one document read and slices in Python; the wire savings for the 2.5s
    poll come from only ever sending `limit` messages to the client, not
    from a cheaper backend read. A `before` cursor of `seq` can drift once
    the stored array is truncated at max_messages (oldest messages evicted,
    remaining seqs shift) — an inherent limitation of the capped single-doc
    array schema. That's the same drift the existing unread-badge math
    already tolerates (see frontend/src/hooks/useUnread.ts).

    Each message dict carries a stable-for-the-current-window `seq` index
    (absolute position in the full stored array at read time) so the client
    can compute the unread badge (CHAT-04 / D-11) and page cursors:
      badge = latest_seq + 1 - last_seen_seq

    Phase 29 (D-02): `?chat_visible=1` reports that the hub chat view is
    genuinely on-screen (the client only ever sends this while its own
    isVisible flag is true — see frontend/src/hooks/useChat.ts). This marks
    the server-side visibility window (core.scheduled_message
    .mark_chat_visible) so send_and_inject suppresses push while Amit is
    looking at the chat. This route itself is read-only and never pushes.

    Returns:
        JSONResponse: {"messages": [{"seq": int, "role": str, "content": str}, ...],
                       "has_more": bool}

    Raises:
        HTTPException 401: No valid session cookie (via require_hub_session).
    """
    from memory.firestore_db import _jsonsafe_doc  # lazy import — Shared Pattern 5 + Pitfall 4

    if chat_visible == 1:
        from core.scheduled_message import mark_chat_visible  # lazy import
        mark_chat_visible()

    loop = asyncio.get_running_loop()
    try:
        user_id = await loop.run_in_executor(None, _resolve_hub_user_id)
    except ValueError as exc:
        logger.error("api_chat_messages: cannot resolve user_id: %s", exc)
        raise HTTPException(status_code=500, detail={"error": "Server misconfigured: user identity unresolvable"})

    def _get_messages() -> tuple[list[dict], bool]:
        from memory.firestore_conversation import FirestoreConversationStore  # lazy import
        project_id = os.environ.get("GCP_PROJECT_ID", "")
        database = os.environ.get("FIRESTORE_DATABASE", "(default)")
        store = FirestoreConversationStore(project_id=project_id, database=database)
        # get_full (not get): the hub shows the whole continuous conversation,
        # not just the active session window the agent uses (CR-02).
        msgs = store.get_full(user_id)
        # Add stable (for this read) seq index for unread badge + pagination.
        numbered = [{"seq": i, **msg} for i, msg in enumerate(msgs)]

        if before is not None:
            older = [m for m in numbered if m["seq"] < before]
            window = older[-limit:]
            has_more = len(older) > len(window)
        else:
            window = numbered[-limit:]
            has_more = len(numbered) > len(window)
        return window, has_more

    messages, has_more = await loop.run_in_executor(None, _get_messages)

    # _jsonsafe_doc on the full response (Pitfall 4 / T-26-05-06)
    payload = _jsonsafe_doc({"messages": messages, "has_more": has_more})
    return JSONResponse(content=payload)


@app.post("/internal/process-hub-message")
async def internal_process_hub_message(request: Request) -> JSONResponse:
    """Cloud Tasks target: run one hub chat agent turn with full CPU.

    POST /api/chat enqueues the hub message via enqueue_hub_message; Cloud
    Tasks POSTs it here with an OIDC token from the same service account the
    Cloud Scheduler crons use, verified by _verify_cron_request.

    The agent turn runs INSIDE this tracked request via asyncio.to_thread so
    Cloud Run allocates full CPU for its duration — unlike a BackgroundTask,
    which runs after the response on throttled CPU (D-09 / CLAUDE.md invariant).

    Reply is appended to the shared FirestoreConversationStore by
    handle_message itself; the hub polls /api/chat/messages to receive it.

    Phase 29 (PUSH-02/03, D-01/D-08): the reply is ALSO pushed + mirrored to
    Telegram (while the mirror flag is on) via the Plan-1 lazy-Bot
    send_and_inject path (core.scheduled_message), so a hub reply reaches
    Amit even when the hub tab isn't open. inject_into_conversation=False —
    handle_message already appended the reply; re-injecting would double it
    (CR-03 class bug).

    Raises:
        HTTPException 401/403: OIDC verification failed (T-26-05-02).
        HTTPException 500: Orchestrator not initialised (Cloud Tasks retries).
    """
    # OIDC gate — same verification as /internal/process-update (T-26-05-02)
    await _verify_cron_request(request)

    # Singleton guard — orchestrator must be initialised (lifespan startup)
    if _orchestrator is None:
        logger.error("/internal/process-hub-message before orchestrator initialised")
        raise HTTPException(
            status_code=500,
            detail={"error": "Server is still initialising; please retry."},
        )

    request_json: dict = await request.json()
    content = request_json.get("content", "")
    # Reject a missing/zero user_id explicitly rather than silently defaulting
    # to 0 (WR-04) — a malformed payload would otherwise run the agent turn
    # against the phantom conversation document "0" and the reply would never
    # be visible to the real user. This endpoint is OIDC-gated and only ever
    # called by enqueue_hub_message (which always supplies a resolved int),
    # so this guard should be unreachable in practice — but fail loudly
    # rather than silently misrouting if that assumption is ever violated.
    raw_user_id = request_json.get("user_id")
    if not raw_user_id:
        raise HTTPException(status_code=400, detail={"error": "missing user_id"})
    user_id = int(raw_user_id)

    # Run the agent turn inside this tracked request (full CPU — D-09).
    # handle_message is the single writer: it appends BOTH the user turn and the
    # assistant reply to the shared FirestoreConversationStore (core/main.py
    # lines 481/501), with no Telegram send on this hub path — the client polls
    # /api/chat/messages to receive the reply. We do NOT append here (doing so
    # double-wrote the assistant reply, CR-03).
    # asyncio.to_thread is safe: handle_message uses thread-local tool_registry.
    reply_text = await asyncio.to_thread(_orchestrator.handle_message, content, user_id)

    # Phase 29 (PUSH-02/03, D-01/D-08): push + mirror this reply too. bot=None
    # lets send_and_inject lazily build/reuse its own module-level Bot (this
    # route has no bot instance of its own). inject_into_conversation=False —
    # handle_message already wrote the reply above (CR-03).
    try:
        from core.scheduled_message import send_and_inject  # lazy import
        await send_and_inject(
            None, reply_text, message_class="chat_reply", inject_into_conversation=False
        )
    except Exception:
        logger.warning(
            "internal_process_hub_message: push/mirror delivery failed for user_id=%s",
            user_id,
            exc_info=True,
        )

    return JSONResponse(content={"ok": True})


# --------------------------------------------------------------------------- #
# Task + Task-list routes — /api/tasks/* and /api/task-lists/*                #
# Plan 27-02, TASK-01 / TASK-07                                               #
#                                                                             #
# All routes are behind Depends(require_hub_session) (T-27-AC).              #
# All sync Firestore calls run via loop.run_in_executor (Pitfall 2).         #
# All Firestore output passes through _jsonsafe_doc (Pitfall 4).             #
# Place BEFORE the SPA mount so these routes are reachable (Pitfall 1).      #
# --------------------------------------------------------------------------- #

from pydantic import BaseModel, Field  # noqa: E402 (lazy placement — keeps cold-start fast)
from typing import Literal  # noqa: E402


class RecurrenceInput(BaseModel):
    """Recurrence rule for a task (matches TaskStore + the recurrence engine).

    ``every_n`` is only meaningful for the ``every_n_days`` cadence. The engine
    (``_advance_once``) reads ``every_n``/``every_n_days`` tolerantly.
    """

    cadence: Literal["daily", "weekdays", "weekly", "monthly", "every_n_days"]
    anchor: Literal["schedule", "completion"] = "schedule"
    every_n: int | None = Field(None, ge=1, le=365)


class CreateTaskInput(BaseModel):
    """Pydantic model for POST /api/tasks bodies (ASVS V5 / T-27-IV).

    Field constraints mirror the RESEARCH § Security Domain definition:
      - title: 1..500 chars (non-empty, bounded)
      - notes: optional ≤10 000 chars
      - due_date: YYYY-MM-DD or None
      - due_time: HH:MM (24h) or None
      - priority: one of the four legal values
      - list_id: free string or None (defaults to "inbox" in the route)
      - recurrence: optional recurrence rule or None
    """

    title: str = Field(..., min_length=1, max_length=500)
    notes: str | None = Field(None, max_length=10_000)
    due_date: str | None = Field(None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    due_time: str | None = Field(None, pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    priority: Literal["none", "low", "medium", "high"] = "none"
    list_id: str | None = None  # None → coerced to "inbox" in the route
    recurrence: RecurrenceInput | None = None


class UpdateTaskInput(BaseModel):
    """Pydantic model for PATCH /api/tasks/{id} bodies (all fields optional)."""

    title: str | None = Field(None, min_length=1, max_length=500)
    notes: str | None = Field(None, max_length=10_000)
    due_date: str | None = Field(None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    due_time: str | None = Field(None, pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    priority: Literal["none", "low", "medium", "high"] | None = None
    list_id: str | None = None
    recurrence: RecurrenceInput | None = None


class CreateListInput(BaseModel):
    """Pydantic model for POST /api/task-lists bodies."""

    name: str = Field(..., min_length=1, max_length=200)


# ------------------------------------------------------------------
# /api/tasks routes
# ------------------------------------------------------------------

@app.post("/api/tasks")
async def api_create_task(
    body: CreateTaskInput,
    _email: str = Depends(require_hub_session),
) -> JSONResponse:
    """Create a new task in TaskStore.

    POST /api/tasks with a CreateTaskInput body.  list_id defaults to "inbox"
    when None is supplied (Inbox is implicit — no Firestore doc exists for it).

    Returns:
        JSONResponse: The created task dict (id, title, status, …).
    Raises:
        HTTPException 401: No valid session cookie.
        HTTPException 422: Pydantic validation failure (T-27-IV).
    """
    from memory.firestore_db import TaskStore, _jsonsafe_doc  # lazy import — Shared Pattern 5

    task_dict = body.model_dump(exclude_none=False)
    # Coerce None list_id → "inbox" (D-07 from RESEARCH: Inbox is implicit)
    if not task_dict.get("list_id"):
        task_dict["list_id"] = "inbox"

    loop = asyncio.get_running_loop()
    store = TaskStore(
        project_id=os.environ.get("GCP_PROJECT_ID", ""),
        database=os.environ.get("FIRESTORE_DATABASE", "(default)"),
    )
    task = await loop.run_in_executor(None, store.create, task_dict)
    return JSONResponse(content=_jsonsafe_doc(task))


@app.get("/api/tasks/summary")
async def api_tasks_summary(
    _email: str = Depends(require_hub_session),
) -> JSONResponse:
    """Return due-today + overdue counts in Asia/Jerusalem.

    GET /api/tasks/summary — TASK-07.

    WHY this route is declared before /api/tasks: FastAPI registers routes in
    declaration order.  The literal path /api/tasks/summary must match before
    the parametric /api/tasks/{task_id} would shadow it.

    Returns:
        JSONResponse: {"due_today": int, "overdue": int}
    Raises:
        HTTPException 401: No valid session cookie.
    """
    from memory.firestore_db import TaskStore, _jsonsafe_doc  # lazy import

    today_iso = datetime.now(ZoneInfo("Asia/Jerusalem")).date().isoformat()
    loop = asyncio.get_running_loop()
    store = TaskStore(
        project_id=os.environ.get("GCP_PROJECT_ID", ""),
        database=os.environ.get("FIRESTORE_DATABASE", "(default)"),
    )
    summary = await loop.run_in_executor(None, store.get_summary, today_iso)
    return JSONResponse(content=_jsonsafe_doc(summary))


@app.get("/api/tasks")
async def api_list_tasks(
    list_id: str | None = None,
    _email: str = Depends(require_hub_session),
) -> JSONResponse:
    """List active tasks, optionally filtered by list_id.

    GET /api/tasks?list_id=<id> — TASK-01.

    Returns:
        JSONResponse: {"tasks": [...]}
    Raises:
        HTTPException 401: No valid session cookie.
    """
    from memory.firestore_db import TaskStore, _jsonsafe_doc  # lazy import

    loop = asyncio.get_running_loop()
    store = TaskStore(
        project_id=os.environ.get("GCP_PROJECT_ID", ""),
        database=os.environ.get("FIRESTORE_DATABASE", "(default)"),
    )
    tasks = await loop.run_in_executor(None, lambda: store.list(list_id=list_id))
    return JSONResponse(content=_jsonsafe_doc({"tasks": tasks}))


@app.patch("/api/tasks/{task_id}")
async def api_update_task(
    task_id: str,
    body: UpdateTaskInput,
    _email: str = Depends(require_hub_session),
) -> JSONResponse:
    """Partially update a task.

    PATCH /api/tasks/{task_id} — TASK-01.

    Returns:
        JSONResponse: The updated task dict.
    Raises:
        HTTPException 401: No valid session cookie.
        HTTPException 422: Pydantic validation failure (T-27-IV).
    """
    from memory.firestore_db import TaskStore, _jsonsafe_doc  # lazy import

    # Only pass fields that were explicitly provided (exclude unset so None
    # values don't overwrite set fields that weren't sent in this PATCH).
    patch = body.model_dump(exclude_unset=True)
    loop = asyncio.get_running_loop()
    store = TaskStore(
        project_id=os.environ.get("GCP_PROJECT_ID", ""),
        database=os.environ.get("FIRESTORE_DATABASE", "(default)"),
    )
    updated = await loop.run_in_executor(None, store.update, task_id, patch)
    # store.update re-fetches and returns the doc; guard None so a missing task
    # never reaches _jsonsafe_doc(None) (which would 500 — the old edit bug).
    return JSONResponse(content=_jsonsafe_doc(updated or {}))


@app.post("/api/tasks/{task_id}/complete")
async def api_complete_task(
    task_id: str,
    _email: str = Depends(require_hub_session),
) -> JSONResponse:
    """Soft-mark a task as completing and generate the next recurring instance.

    POST /api/tasks/{task_id}/complete — D-07.

    Returns:
        JSONResponse: {"next_id": str | None}
    Raises:
        HTTPException 401: No valid session cookie.
    """
    from memory.firestore_db import TaskStore, _jsonsafe_doc  # lazy import

    completed_on_iso = datetime.now(ZoneInfo("Asia/Jerusalem")).date().isoformat()
    loop = asyncio.get_running_loop()
    store = TaskStore(
        project_id=os.environ.get("GCP_PROJECT_ID", ""),
        database=os.environ.get("FIRESTORE_DATABASE", "(default)"),
    )
    result = await loop.run_in_executor(None, store.complete, task_id, completed_on_iso)
    return JSONResponse(content=_jsonsafe_doc(result))


@app.post("/api/tasks/{task_id}/undo")
async def api_undo_task(
    task_id: str,
    _email: str = Depends(require_hub_session),
) -> JSONResponse:
    """Revert a completing task back to active.

    POST /api/tasks/{task_id}/undo — D-07.

    Returns:
        JSONResponse: {"ok": True}
    Raises:
        HTTPException 401: No valid session cookie.
    """
    from memory.firestore_db import TaskStore  # lazy import

    loop = asyncio.get_running_loop()
    store = TaskStore(
        project_id=os.environ.get("GCP_PROJECT_ID", ""),
        database=os.environ.get("FIRESTORE_DATABASE", "(default)"),
    )
    await loop.run_in_executor(None, store.undo_complete, task_id)
    return JSONResponse(content={"ok": True})


@app.post("/api/tasks/{task_id}/soft-delete")
async def api_soft_delete_task(
    task_id: str,
    _email: str = Depends(require_hub_session),
) -> JSONResponse:
    """Soft-mark a task as 'completing' for the delete→undo→hard-delete flow.

    POST /api/tasks/{task_id}/soft-delete — D-13/D-14.

    Unlike /complete this NEVER generates a recurring next instance. It opens
    the undo window and satisfies the hard-delete gate (T-27-REP); /undo
    reverts it to active if the user taps Undo.

    Returns:
        JSONResponse: {"ok": True}
    Raises:
        HTTPException 401: No valid session cookie.
    """
    from memory.firestore_db import TaskStore  # lazy import

    loop = asyncio.get_running_loop()
    store = TaskStore(
        project_id=os.environ.get("GCP_PROJECT_ID", ""),
        database=os.environ.get("FIRESTORE_DATABASE", "(default)"),
    )
    await loop.run_in_executor(None, store.soft_delete, task_id)
    return JSONResponse(content={"ok": True})


@app.post("/api/tasks/{task_id}/hard-delete")
async def api_hard_delete_task(
    task_id: str,
    _email: str = Depends(require_hub_session),
) -> JSONResponse:
    """Hard-delete a task from Firestore — only allowed when status='completing'.

    POST /api/tasks/{task_id}/hard-delete — T-27-REP.

    A replayed or forged hard-delete of an active task is rejected with 409:
    the task must first go through the soft-complete flow so the UI always has
    an undo window before the doc is permanently removed.

    Returns:
        JSONResponse: {"ok": True}
    Raises:
        HTTPException 401: No valid session cookie.
        HTTPException 409: Task is not in 'completing' state (T-27-REP).
    """
    from memory.firestore_db import TaskStore  # lazy import

    loop = asyncio.get_running_loop()
    store = TaskStore(
        project_id=os.environ.get("GCP_PROJECT_ID", ""),
        database=os.environ.get("FIRESTORE_DATABASE", "(default)"),
    )

    task = await loop.run_in_executor(None, store.get, task_id)
    if task is None or task.get("status") != "completing":
        raise HTTPException(
            status_code=409,
            detail={"error": "task not in completing state"},
        )

    await loop.run_in_executor(None, store.delete, task_id)
    return JSONResponse(content={"ok": True})


# ------------------------------------------------------------------
# /api/task-lists routes
# ------------------------------------------------------------------

@app.post("/api/task-lists")
async def api_create_task_list(
    body: CreateListInput,
    _email: str = Depends(require_hub_session),
) -> JSONResponse:
    """Create a user-defined task list.

    POST /api/task-lists — TASK-02.

    Returns:
        JSONResponse: The created list dict (id, name).
    Raises:
        HTTPException 401: No valid session cookie.
    """
    from memory.firestore_db import TaskListStore, _jsonsafe_doc  # lazy import

    loop = asyncio.get_running_loop()
    store = TaskListStore(
        project_id=os.environ.get("GCP_PROJECT_ID", ""),
        database=os.environ.get("FIRESTORE_DATABASE", "(default)"),
    )
    created = await loop.run_in_executor(None, store.create, body.name)
    return JSONResponse(content=_jsonsafe_doc(created))


@app.get("/api/task-lists")
async def api_list_task_lists(
    _email: str = Depends(require_hub_session),
) -> JSONResponse:
    """List all user-defined task lists, with the implicit Inbox prepended.

    GET /api/task-lists — TASK-02.

    WHY Inbox is prepended: the "inbox" list_id is implicit (no Firestore doc);
    TaskListStore.list() never returns it.  The route always inserts it at
    position 0 so the frontend can render a stable "Inbox" entry without
    special-casing an empty-document fallback.

    Returns:
        JSONResponse: {"lists": [{"id": "inbox", "name": "Inbox"}, ...user lists]}
    Raises:
        HTTPException 401: No valid session cookie.
    """
    from memory.firestore_db import TaskListStore, _jsonsafe_doc  # lazy import

    loop = asyncio.get_running_loop()
    store = TaskListStore(
        project_id=os.environ.get("GCP_PROJECT_ID", ""),
        database=os.environ.get("FIRESTORE_DATABASE", "(default)"),
    )
    user_lists = await loop.run_in_executor(None, store.list)
    # Prepend implicit Inbox (decision from 27-01: Inbox has no Firestore doc)
    lists = [{"id": "inbox", "name": "Inbox"}, *user_lists]
    return JSONResponse(content=_jsonsafe_doc({"lists": lists}))


@app.patch("/api/task-lists/{list_id}")
async def api_rename_task_list(
    list_id: str,
    body: CreateListInput,
    _email: str = Depends(require_hub_session),
) -> JSONResponse:
    """Rename a user-defined task list.

    PATCH /api/task-lists/{list_id} — TASK-02.

    Returns:
        JSONResponse: The updated list dict (id, name).
    Raises:
        HTTPException 401: No valid session cookie.
    """
    from memory.firestore_db import TaskListStore, _jsonsafe_doc  # lazy import

    loop = asyncio.get_running_loop()
    store = TaskListStore(
        project_id=os.environ.get("GCP_PROJECT_ID", ""),
        database=os.environ.get("FIRESTORE_DATABASE", "(default)"),
    )
    updated = await loop.run_in_executor(None, store.rename, list_id, body.name)
    return JSONResponse(content=_jsonsafe_doc(updated))


@app.delete("/api/task-lists/{list_id}")
async def api_delete_task_list(
    list_id: str,
    _email: str = Depends(require_hub_session),
) -> JSONResponse:
    """Delete a user-defined task list.

    DELETE /api/task-lists/{list_id} — TASK-02.

    Tasks previously in the deleted list retain their list_id.  They will
    appear under "Unknown list" in the UI until reassigned.  A future plan may
    add a reassign-to-inbox sweep; for now the behaviour matches TickTick's
    own delete-list semantics (tasks persist under their prior list_id).

    Returns:
        JSONResponse: {"ok": True}
    Raises:
        HTTPException 401: No valid session cookie.
    """
    from memory.firestore_db import TaskListStore  # lazy import

    loop = asyncio.get_running_loop()
    store = TaskListStore(
        project_id=os.environ.get("GCP_PROJECT_ID", ""),
        database=os.environ.get("FIRESTORE_DATABASE", "(default)"),
    )
    await loop.run_in_executor(None, store.delete, list_id)
    return JSONResponse(content={"ok": True})


# --------------------------------------------------------------------------- #
# Habit + Supplement routes — /api/habits/*                                   #
# Plan 28-02, HABIT-01 / HABIT-02 / HABIT-04 / TIME-06                       #
#                                                                             #
# All routes are behind Depends(require_hub_session) (T-28-AC).              #
# All sync Firestore calls run via loop.run_in_executor (Pitfall 2).         #
# All Firestore output passes through _jsonsafe_doc (Pitfall 4).             #
# Place BEFORE the SPA mount so these routes are reachable (Pitfall 1).      #
# /api/habits/summary declared BEFORE /api/habits/{habit_id} (FastAPI        #
# declaration order — same note as /api/tasks/summary line 1834).            #
# dose / dose_taken returned as plain strings only — never HTML (T-28-xss).  #
# --------------------------------------------------------------------------- #


class CreateHabitInput(BaseModel):
    """Pydantic model for POST /api/habits bodies (ASVS V5 / T-28-input).

    Field constraints:
      - name: 1..500 chars (non-empty, bounded)
      - type: habit | supplement (Literal)
      - dose: optional ≤200 chars; plain string, no markup (T-28-xss)
      - slot: one of the four named time-of-day slots (D-05)
      - days: "daily" or list of weekday ints 0-6 Mon=0 (D-04)
    """

    name: str = Field(..., min_length=1, max_length=500)
    type: Literal["habit", "supplement"] = "habit"
    dose: str | None = Field(None, max_length=200)
    slot: Literal["Morning", "Noon", "Evening", "Bedtime"] = "Morning"
    days: str | list[int] = "daily"  # "daily" | weekday ints (Mon=0), D-04


class EditHabitInput(BaseModel):
    """Pydantic model for PATCH /api/habits/{id} (all fields optional, T-28-input).

    ``effective_from`` is an optional date that, if provided with a schedule
    change (``days``), must be >= today (D-19 / T-28-schedule).  When absent
    the route defaults to today so the store always uses today's date for the
    new schedule revision.
    """

    name: str | None = Field(None, min_length=1, max_length=500)
    type: Literal["habit", "supplement"] | None = None
    dose: str | None = Field(None, max_length=200)
    slot: Literal["Morning", "Noon", "Evening", "Bedtime"] | None = None
    days: str | list[int] | None = None
    # Explicit effective_from for a schedule revision (D-19):
    # must be >= today_iso or the route returns 400 (T-28-schedule).
    effective_from: str | None = Field(None, pattern=r"^\d{4}-\d{2}-\d{2}$")


class CheckinInput(BaseModel):
    """Pydantic model for POST /api/habits/{id}/checkin (T-28-backfill / D-11).

    ``date`` is validated as YYYY-MM-DD.  The route enforces that it is either
    today or yesterday (Asia/Jerusalem) — older dates return 400.
    ``dose_taken`` records the actual dose for supplements (D-09).
    """

    date: str = Field(..., pattern=r"^\d{4}-\d{2}-\d{2}$")
    done: bool = True
    dose_taken: str | None = Field(None, max_length=200)


# ------------------------------------------------------------------
# /api/habits/summary — literal path BEFORE /api/habits/{habit_id}
# ------------------------------------------------------------------

@app.get("/api/habits/summary")
async def api_habits_summary(
    _email: str = Depends(require_hub_session),
) -> JSONResponse:
    """Return pending-today count + streak leaders for the GlanceRail (HABIT-04).

    GET /api/habits/summary — TIME-06 / GlanceRail.

    WHY this route is declared before /api/habits/{habit_id}: FastAPI registers
    routes in declaration order.  The literal path /api/habits/summary must
    match before the parametric /api/habits/{habit_id} would shadow it
    (same note as /api/tasks/summary line 1834).

    Returns:
        JSONResponse: {"pending_today": int, "streak_leaders": [{id, name, streak}]}
    Raises:
        HTTPException 401: No valid session cookie.
    """
    from memory.firestore_db import HabitStore, _jsonsafe_doc  # lazy import

    today_iso = datetime.now(ZoneInfo("Asia/Jerusalem")).date().isoformat()
    loop = asyncio.get_running_loop()
    store = HabitStore(
        project_id=os.environ.get("GCP_PROJECT_ID", ""),
        database=os.environ.get("FIRESTORE_DATABASE", "(default)"),
    )
    summary = await loop.run_in_executor(None, store.get_summary, today_iso)
    return JSONResponse(content=_jsonsafe_doc(summary))


# ------------------------------------------------------------------
# /api/habits routes
# ------------------------------------------------------------------

@app.get("/api/habits")
async def api_list_habits(
    _email: str = Depends(require_hub_session),
) -> JSONResponse:
    """List all active habits/supplements enriched with today's state (HABIT-01, TIME-06).

    GET /api/habits — HABIT-01 / TIME-06.

    Each item is enriched with four additional fields so the HabitsBand and
    HabitRow can render without extra per-item calls:
      - scheduled_today: bool — is this habit scheduled for today?
      - done_today: bool — has it been checked off today?
      - dose_taken: str|None — dose from today's completion record (D-09)
      - streak: int — current streak from compute_streak_and_grid

    Computation:
      - list_active() → all active definitions
      - get_completions_for_date(today_iso) → today's completion map
      - _is_scheduled(today, schedule_history) → scheduled_today (pure, no Firestore)
      - get_history(habit_id, today_iso) → streak (one Firestore call per habit;
        acceptable at personal scale of 10-20 items)

    Returns:
        JSONResponse: {"habits": [...enriched items...]}
    Raises:
        HTTPException 401: No valid session cookie.
    """
    from datetime import date as _date
    from memory.firestore_db import HabitStore, _jsonsafe_doc, _is_scheduled  # lazy import

    today_iso = datetime.now(ZoneInfo("Asia/Jerusalem")).date().isoformat()
    today = _date.fromisoformat(today_iso)

    loop = asyncio.get_running_loop()
    store = HabitStore(
        project_id=os.environ.get("GCP_PROJECT_ID", ""),
        database=os.environ.get("FIRESTORE_DATABASE", "(default)"),
    )
    habits = await loop.run_in_executor(None, store.list_active)
    completions = await loop.run_in_executor(None, store.get_completions_for_date, today_iso)

    enriched = []
    for h in habits:
        hid = h.get("id", "")
        schedule_history = h.get("schedule_history", [])
        scheduled_today = _is_scheduled(today, schedule_history)
        comp = completions.get(hid)
        done_today = comp is not None
        # dose_taken: plain string from the completion record (D-09); never HTML (T-28-xss)
        dose_taken = comp.get("dose_taken") if comp else None
        history = await loop.run_in_executor(None, store.get_history, hid, today_iso)
        streak = history.get("streak", 0) if history else 0
        enriched.append({
            **h,
            "scheduled_today": scheduled_today,
            "done_today": done_today,
            "dose_taken": dose_taken,
            "streak": streak,
        })

    return JSONResponse(content=_jsonsafe_doc({"habits": enriched}))


@app.post("/api/habits")
async def api_create_habit(
    body: CreateHabitInput,
    _email: str = Depends(require_hub_session),
) -> JSONResponse:
    """Create a new habit or supplement definition (HABIT-01).

    POST /api/habits with a CreateHabitInput body.  The store seeds
    ``schedule_history`` from the ``days`` field (D-19 / D-04).

    Returns:
        JSONResponse: The created habit dict.
    Raises:
        HTTPException 401: No valid session cookie.
        HTTPException 422: Pydantic validation failure (T-28-input).
    """
    from memory.firestore_db import HabitStore, _jsonsafe_doc  # lazy import

    habit_dict = body.model_dump(exclude_none=False)
    loop = asyncio.get_running_loop()
    store = HabitStore(
        project_id=os.environ.get("GCP_PROJECT_ID", ""),
        database=os.environ.get("FIRESTORE_DATABASE", "(default)"),
    )
    created = await loop.run_in_executor(None, store.create, habit_dict)
    return JSONResponse(content=_jsonsafe_doc(created))


@app.patch("/api/habits/{habit_id}")
async def api_update_habit(
    habit_id: str,
    body: EditHabitInput,
    _email: str = Depends(require_hub_session),
) -> JSONResponse:
    """Partially update a habit/supplement definition (HABIT-01).

    PATCH /api/habits/{habit_id} with an EditHabitInput body.

    D-19 / T-28-schedule gate: if the body carries a schedule change (``days``)
    with an explicit ``effective_from`` that is strictly before today (Asia/Jerusalem),
    returns 400 — retroactive schedule rewrites are forbidden.  When ``effective_from``
    is absent the store always uses today as the revision date, which is always valid.

    Returns:
        JSONResponse: The updated habit dict.
    Raises:
        HTTPException 400: effective_from is in the past (T-28-schedule / D-19).
        HTTPException 401: No valid session cookie.
        HTTPException 422: Pydantic validation failure (T-28-input).
    """
    from memory.firestore_db import HabitStore, _jsonsafe_doc  # lazy import

    today_iso = datetime.now(ZoneInfo("Asia/Jerusalem")).date().isoformat()

    # D-19 / T-28-schedule: reject past effective_from to prevent retroactive rewrites.
    patch = body.model_dump(exclude_unset=True)
    if "days" in patch and "effective_from" in patch and patch["effective_from"] is not None:
        if patch["effective_from"] < today_iso:
            raise HTTPException(
                status_code=400,
                detail={"error": "effective_from must be today or later"},
            )
    # Remove effective_from from the patch dict — the store always uses today as
    # the revision effective_from (HabitStore.update is the single source of truth
    # for revision dates).
    patch.pop("effective_from", None)

    loop = asyncio.get_running_loop()
    store = HabitStore(
        project_id=os.environ.get("GCP_PROJECT_ID", ""),
        database=os.environ.get("FIRESTORE_DATABASE", "(default)"),
    )
    updated = await loop.run_in_executor(None, store.update, habit_id, patch)
    return JSONResponse(content=_jsonsafe_doc(updated or {}))


@app.post("/api/habits/{habit_id}/checkin")
async def api_habit_checkin(
    habit_id: str,
    body: CheckinInput,
    _email: str = Depends(require_hub_session),
) -> JSONResponse:
    """Toggle a habit check-off for today or yesterday (D-07 / D-11 / D-12).

    POST /api/habits/{habit_id}/checkin with a CheckinInput body.

    D-11 / T-28-backfill gate: the ``date`` field must be either today or
    yesterday (Asia/Jerusalem).  Any older date returns 400 to prevent
    retroactive history rewrites beyond the one-day backfill window.

    done=True  → writes a completion record (idempotent set).
    done=False → deletes the completion record (un-check / toggle, D-07).

    dose_taken records the actual dose for supplements (D-09); plain string,
    never HTML (T-28-xss).

    Returns:
        JSONResponse: {"ok": True}
    Raises:
        HTTPException 400: date is older than yesterday (T-28-backfill / D-11).
        HTTPException 401: No valid session cookie.
        HTTPException 422: Pydantic validation failure (T-28-input).
    """
    from memory.firestore_db import HabitStore  # lazy import

    # D-11 / T-28-backfill gate: only today or yesterday (Asia/Jerusalem) allowed.
    _tz = ZoneInfo("Asia/Jerusalem")
    today_iso = datetime.now(_tz).date().isoformat()
    yesterday_iso = (datetime.now(_tz).date() - timedelta(days=1)).isoformat()
    if body.date not in (today_iso, yesterday_iso):
        raise HTTPException(
            status_code=400,
            detail={"error": "date must be today or yesterday"},
        )

    loop = asyncio.get_running_loop()
    store = HabitStore(
        project_id=os.environ.get("GCP_PROJECT_ID", ""),
        database=os.environ.get("FIRESTORE_DATABASE", "(default)"),
    )
    await loop.run_in_executor(
        None, store.log_completion, body.date, habit_id, body.done, body.dose_taken
    )
    return JSONResponse(content={"ok": True})


@app.get("/api/habits/{habit_id}/history")
async def api_habit_history(
    habit_id: str,
    _email: str = Depends(require_hub_session),
) -> JSONResponse:
    """Return the 365-day four-state contribution grid + current streak (HABIT-04).

    GET /api/habits/{habit_id}/history — HABIT-04.

    States: done | missed | pending | not-scheduled (D-13).

    Returns:
        JSONResponse: {"streak": int, "grid": [{date, state}, ...]}
    Raises:
        HTTPException 401: No valid session cookie.
    """
    from memory.firestore_db import HabitStore, _jsonsafe_doc  # lazy import

    today_iso = datetime.now(ZoneInfo("Asia/Jerusalem")).date().isoformat()
    loop = asyncio.get_running_loop()
    store = HabitStore(
        project_id=os.environ.get("GCP_PROJECT_ID", ""),
        database=os.environ.get("FIRESTORE_DATABASE", "(default)"),
    )
    history = await loop.run_in_executor(None, store.get_history, habit_id, today_iso)
    return JSONResponse(content=_jsonsafe_doc(history))


@app.post("/api/habits/{habit_id}/soft-delete")
async def api_soft_delete_habit(
    habit_id: str,
    _email: str = Depends(require_hub_session),
) -> JSONResponse:
    """Soft-delete a habit (set status='completing') to open the undo-toast window.

    POST /api/habits/{habit_id}/soft-delete — D-20.

    The frontend shows an undo toast; if not tapped, the hard-delete is
    called after the toast timeout.  /restore reverts to active if tapped.

    Returns:
        JSONResponse: {"ok": True}
    Raises:
        HTTPException 401: No valid session cookie.
    """
    from memory.firestore_db import HabitStore  # lazy import

    loop = asyncio.get_running_loop()
    store = HabitStore(
        project_id=os.environ.get("GCP_PROJECT_ID", ""),
        database=os.environ.get("FIRESTORE_DATABASE", "(default)"),
    )
    await loop.run_in_executor(None, store.soft_delete, habit_id)
    return JSONResponse(content={"ok": True})


@app.post("/api/habits/{habit_id}/restore")
async def api_restore_habit(
    habit_id: str,
    _email: str = Depends(require_hub_session),
) -> JSONResponse:
    """Restore a soft-deleted habit to active (undo-toast action, D-20).

    POST /api/habits/{habit_id}/restore — D-20.

    Returns:
        JSONResponse: {"ok": True}
    Raises:
        HTTPException 401: No valid session cookie.
    """
    from memory.firestore_db import HabitStore  # lazy import

    loop = asyncio.get_running_loop()
    store = HabitStore(
        project_id=os.environ.get("GCP_PROJECT_ID", ""),
        database=os.environ.get("FIRESTORE_DATABASE", "(default)"),
    )
    await loop.run_in_executor(None, store.restore, habit_id)
    return JSONResponse(content={"ok": True})


@app.post("/api/habits/{habit_id}/hard-delete")
async def api_hard_delete_habit(
    habit_id: str,
    _email: str = Depends(require_hub_session),
) -> JSONResponse:
    """Hard-delete a habit and all its completion records — only allowed when
    status='completing'.

    POST /api/habits/{habit_id}/hard-delete — D-20.

    The habit must first be soft-deleted (status='completing') via
    /soft-delete; otherwise 409 is returned.  This gate prevents
    accidental hard-deletes that bypass the undo-toast flow.

    Returns:
        JSONResponse: {"ok": True}
    Raises:
        HTTPException 401: No valid session cookie.
        HTTPException 409: Habit is not in 'completing' state (D-20 gate).
    """
    from memory.firestore_db import HabitStore  # lazy import

    loop = asyncio.get_running_loop()
    store = HabitStore(
        project_id=os.environ.get("GCP_PROJECT_ID", ""),
        database=os.environ.get("FIRESTORE_DATABASE", "(default)"),
    )

    habit = await loop.run_in_executor(None, store.get, habit_id)
    if habit is None or habit.get("status") != "completing":
        raise HTTPException(
            status_code=409,
            detail={"error": "habit not in completing state"},
        )

    await loop.run_in_executor(None, store.delete, habit_id)
    return JSONResponse(content={"ok": True})


# --------------------------------------------------------------------------- #
# Web Push + Hub Settings routes — /api/push/*, /api/settings                 #
# Plan 29-06, PUSH-01 / PUSH-03                                               #
#                                                                             #
# All routes are behind Depends(require_hub_session) (T-29-10). Every         #
# subscribe input is validated (https endpoint + p256dh/auth keys present,    #
# T-29-11) before it ever reaches PushSubscriptionStore.upsert. PATCH         #
# /api/settings accepts ONLY telegram_mirror_enabled — no other keys are      #
# ever forwarded to HubSettingsStore.set (T-29-12). All sync Firestore calls  #
# run via loop.run_in_executor (Pitfall 2). Place BEFORE the SPA mount so     #
# these routes are reachable (Pitfall 1).                                    #
# --------------------------------------------------------------------------- #


def _get_push_store():
    """Return a PushSubscriptionStore instance using env-driven project/database config."""
    from memory.firestore_db import PushSubscriptionStore  # lazy import

    return PushSubscriptionStore(
        project_id=os.environ.get("GCP_PROJECT_ID", ""),
        database=os.environ.get("FIRESTORE_DATABASE", "(default)"),
    )


def _get_hub_settings_store():
    """Return a HubSettingsStore instance using env-driven project/database config."""
    from memory.firestore_db import HubSettingsStore  # lazy import

    return HubSettingsStore(
        project_id=os.environ.get("GCP_PROJECT_ID", ""),
        database=os.environ.get("FIRESTORE_DATABASE", "(default)"),
    )


@app.post("/api/push/subscribe")
async def api_push_subscribe(
    request: Request,
    _email: str = Depends(require_hub_session),
) -> JSONResponse:
    """Validate and upsert a browser Web Push subscription (PUSH-01).

    POST /api/push/subscribe with body ``{subscription: {endpoint, keys:
    {p256dh, auth}}, user_agent}``.

    Input validation (ASVS V5 / T-29-11): ``endpoint`` must start with
    ``https://`` and ``keys.p256dh`` / ``keys.auth`` must both be present —
    the auth gate means only Amit can ever reach this route, but the endpoint
    is still attacker-shaped input (it's whatever the browser handed back
    from ``pushManager.subscribe``) so we validate before it touches
    Firestore.

    D-14: on the FIRST successful upsert (``HubSettingsStore.get()``'s
    ``push_enabled_at`` is unset/None) this stamps
    ``push_enabled_at=SERVER_TIMESTAMP`` — the heartbeat's anchor for
    detecting "push was enabled but zero subscriptions remain". Later
    subscribes (second device, re-subscribe after key rotation, etc.) leave
    it untouched.

    Returns:
        JSONResponse: ``{"ok": True}``
    Raises:
        HTTPException 400: endpoint is not https, or keys are missing (T-29-11).
        HTTPException 401: No valid session cookie (via require_hub_session).
    """
    body = await request.json()
    sub = body.get("subscription") or {}
    endpoint = sub.get("endpoint", "")
    keys = sub.get("keys") or {}
    user_agent = body.get("user_agent", "")

    if not endpoint.startswith("https://") or not keys.get("p256dh") or not keys.get("auth"):
        raise HTTPException(status_code=400, detail={"error": "invalid subscription"})

    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, _get_push_store().upsert, sub, user_agent)

    # D-14: stamp push_enabled_at exactly once, on the first successful subscribe.
    settings_store = _get_hub_settings_store()
    settings = await loop.run_in_executor(None, settings_store.get)
    if not settings.get("push_enabled_at"):
        from google.cloud import firestore  # lazy import — mirrors memory/firestore_db.py

        await loop.run_in_executor(
            None, settings_store.set, {"push_enabled_at": firestore.SERVER_TIMESTAMP}
        )

    return JSONResponse(content={"ok": True})


@app.get("/api/push/vapid-public-key")
async def api_vapid_public_key(
    _email: str = Depends(require_hub_session),
) -> JSONResponse:
    """Serve the VAPID application-server public key (PUSH-01).

    GET /api/push/vapid-public-key — the frontend passes this base64url key
    to ``pushManager.subscribe`` when registering a new subscription.

    Returns:
        JSONResponse: ``{"key": VAPID_PUBLIC_KEY}``
    Raises:
        HTTPException 401: No valid session cookie (via require_hub_session).
    """
    return JSONResponse(content={"key": os.environ["VAPID_PUBLIC_KEY"]})


@app.get("/api/settings")
async def api_get_settings(
    _email: str = Depends(require_hub_session),
) -> JSONResponse:
    """Return the current hub settings (PUSH-03).

    GET /api/settings — includes ``telegram_mirror_enabled`` (D-09) and
    ``push_enabled_at`` (D-14).

    Returns:
        JSONResponse: The hub settings dict, jsonsafe.
    Raises:
        HTTPException 401: No valid session cookie (via require_hub_session).
    """
    from memory.firestore_db import _jsonsafe_doc  # lazy import — Shared Pattern 5 / Pitfall 4

    loop = asyncio.get_running_loop()
    settings = await loop.run_in_executor(None, _get_hub_settings_store().get)
    return JSONResponse(content=_jsonsafe_doc(settings))


@app.patch("/api/settings")
async def api_patch_settings(
    request: Request,
    _email: str = Depends(require_hub_session),
) -> JSONResponse:
    """Toggle the Telegram-mirror flag, effective immediately (PUSH-03, D-09).

    PATCH /api/settings with body ``{"telegram_mirror_enabled": bool}``.
    Only ``telegram_mirror_enabled`` is ever forwarded to
    ``HubSettingsStore.set`` (T-29-12) — any other key in the body is
    ignored. The raw body is read (not a Pydantic-validated dependency) so a
    non-bool value can be rejected with an explicit 400 rather than FastAPI's
    generic 422.

    Returns:
        JSONResponse: The updated hub settings dict, jsonsafe.
    Raises:
        HTTPException 400: ``telegram_mirror_enabled`` present but not a bool (T-29-12).
        HTTPException 401: No valid session cookie (via require_hub_session).
    """
    from memory.firestore_db import _jsonsafe_doc  # lazy import — Shared Pattern 5 / Pitfall 4

    body = await request.json()
    loop = asyncio.get_running_loop()
    settings_store = _get_hub_settings_store()

    if "telegram_mirror_enabled" in body:
        value = body["telegram_mirror_enabled"]
        if not isinstance(value, bool):
            raise HTTPException(
                status_code=400, detail={"error": "telegram_mirror_enabled must be a bool"}
            )
        await loop.run_in_executor(
            None, settings_store.set, {"telegram_mirror_enabled": value}
        )

    settings = await loop.run_in_executor(None, settings_store.get)
    return JSONResponse(content=_jsonsafe_doc(settings))


# --------------------------------------------------------------------------- #
# SPA Static Files — MUST be the absolute last statement in this file.        #
# ANY route registered after app.mount("/", ...) is unreachable because       #
# Starlette route matching is first-match and Mount("/") matches everything.  #
# See RESEARCH.md Pattern 1 and Pitfall 1.                                    #
# --------------------------------------------------------------------------- #

from fastapi.staticfiles import StaticFiles  # noqa: E402 (end-of-file import is intentional)


class SPAStaticFiles(StaticFiles):
    """Serve the Vite SPA build; fall back to index.html for client-side routes.

    WHY lookup_path override (not get_response override): lookup_path is called
    before the response is built, so a 404 fallback via lookup_path avoids
    constructing a 404 response that we then discard.  This is slightly more
    efficient than the get_response override and avoids catching Starlette
    exceptions in the hot path.

    Any path not matched by a real file in the dist/ directory is routed to
    index.html so that the React Router can handle it client-side.
    """

    def lookup_path(self, path: str):  # type: ignore[override]
        # Starlette's StaticFiles.lookup_path is SYNCHRONOUS — get_response calls
        # it via anyio.to_thread.run_sync(self.lookup_path, path). Declaring this
        # override `async` returns an un-awaited coroutine and 500s every request
        # ("cannot unpack non-iterable coroutine object"). Keep it sync.
        full_path, stat_result = super().lookup_path(path)
        if stat_result is None:
            # Unknown path — let the React Router handle it
            return super().lookup_path("index.html")
        return full_path, stat_result


# IMPORTANT: this must be the VERY LAST statement that registers any route.
# Guard with os.path.isdir so local dev without a frontend build starts cleanly.
_DIST_PATH = os.path.join(os.path.dirname(__file__), "..", "frontend", "dist")
if os.path.isdir(_DIST_PATH):
    app.mount("/", SPAStaticFiles(directory=_DIST_PATH, html=True), name="spa")
else:
    logger.warning(
        "frontend/dist not found — SPA will not be served (expected in production; "
        "run `cd frontend && npm run build` or use the multi-stage Dockerfile)"
    )
