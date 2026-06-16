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
from fastapi import BackgroundTasks, Depends, FastAPI, Header, HTTPException, Request, Response
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
async def api_auth_google(request: Request, response: Response) -> JSONResponse:
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

    response.set_cookie(
        _hub_auth._COOKIE_NAME,
        cookie_value,
        max_age=365 * 86400,
        httponly=True,
        secure=True,
        samesite="strict",
        path="/",
    )
    return JSONResponse(content={"ok": True, "email": email})


@app.post("/api/auth/logout")
async def api_auth_logout(response: Response) -> JSONResponse:
    """Clear the session cookie (single-device sign-out, D-02).

    Does not bump session_version — only removes the cookie on this device.
    For sign-out-everywhere use /api/auth/revoke-all.
    """
    import interfaces.hub_auth as _hub_auth  # lazy import — Shared Pattern 5
    response.delete_cookie(_hub_auth._COOKIE_NAME, path="/")
    return JSONResponse(content={"ok": True})


@app.post("/api/auth/revoke-all")
async def api_auth_revoke_all(
    request: Request,
    response: Response,
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
    response.delete_cookie(_hub_auth._COOKIE_NAME, path="/")
    return JSONResponse(content={"ok": True})


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

        auth_manager = _auth.GoogleAuthManager()
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
    """Strip control/format chars + a leading Markdown header marker and clamp.

    The coach note is the morning briefing's first line — first-party text, but
    it can carry a Markdown header (``#``) or stray bidi/format control chars
    (LRM/RLM) that render oddly. React escapes HTML, so this is hardening, not
    XSS defense (CR-04).
    """
    import unicodedata
    cleaned = "".join(
        ch for ch in str(note)
        if ch in ("\n", "\t") or not unicodedata.category(ch).startswith("C")
    )
    return cleaned.lstrip("#").strip()[:_COACH_NOTE_MAX_LEN]


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
        if not agg:
            return {}
        totals = agg.get("totals", {})
        return {
            "kcal": totals.get("calories"),
            "protein_g": totals.get("protein_g"),
            "carbs_g": totals.get("carbs_g"),
            "fat_g": totals.get("fat_g"),
            "fiber_g": totals.get("fiber_g"),
        }
    except Exception:
        logger.warning("_today_nutrition_totals(%r) failed", today_iso, exc_info=True)
        return {}


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


class _ChatBody(object):
    """Pydantic-lite body parser for POST /api/chat (ASVS V5: non-empty, max length).

    WHY not a real Pydantic model: web_server.py currently doesn't import
    pydantic at the module level, and a plain class avoids adding a hard
    startup dependency. Validation is equivalent: non-empty + max-length.
    FastAPI's json() gives us the raw dict; we validate it here.
    """
    pass


_CHAT_CONTENT_MAX_LEN = 4000  # ASVS V5 — reasonable upper bound for one message


def _resolve_hub_user_id() -> int:
    """Resolve the Telegram user_id to key FirestoreConversationStore.

    Reads UserProfileStore.telegram_user_id (set by 26-02 operator step).
    Falls back to the first id in TELEGRAM_ALLOWED_USER_IDS — the same
    convention used by core/autonomous.py and core/scheduled_message.py.

    WHY this approach: the hub always operates on Amit's single account; there
    is no per-hub-session telegram_user_id mapping needed for v5.0.
    """
    try:
        project_id = os.environ.get("GCP_PROJECT_ID", "")
        database = os.environ.get("FIRESTORE_DATABASE", "(default)")
        if project_id:
            from memory.firestore_db import UserProfileStore  # lazy import
            profile = UserProfileStore(project_id=project_id, database=database).load()
            tid = profile.get("telegram_user_id")
            if tid is not None:
                return int(tid)
    except Exception:
        logger.warning("_resolve_hub_user_id: UserProfileStore lookup failed", exc_info=True)

    # Fallback: first entry of TELEGRAM_ALLOWED_USER_IDS (mirrors autonomous.py convention)
    raw = os.environ.get("TELEGRAM_ALLOWED_USER_IDS", "").split(",")[0].strip()
    if raw:
        return int(raw)
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
    _email: str = Depends(require_hub_session),
) -> JSONResponse:
    """Return the recent conversation window for polling and fast first paint.

    CHAT-03 / D-08: returns the full stored window (up to max_messages ~100).
    The client slices the most recent ~50 for first paint; scroll-up reveals
    older messages from the already-loaded window (no second server round-trip
    needed for Phase 26 — the array-in-doc schema keeps the whole window small).

    Each message dict carries a stable `seq` index (position in the window)
    so the client can compute the unread badge (CHAT-04 / D-11):
      badge = messages.length - last_seen_seq

    Returns:
        JSONResponse: {"messages": [{"seq": int, "role": str, "content": str}, ...]}

    Raises:
        HTTPException 401: No valid session cookie (via require_hub_session).
    """
    from memory.firestore_db import _jsonsafe_doc  # lazy import — Shared Pattern 5 + Pitfall 4

    loop = asyncio.get_running_loop()
    try:
        user_id = await loop.run_in_executor(None, _resolve_hub_user_id)
    except ValueError as exc:
        logger.error("api_chat_messages: cannot resolve user_id: %s", exc)
        raise HTTPException(status_code=500, detail={"error": "Server misconfigured: user identity unresolvable"})

    def _get_messages() -> list[dict]:
        from memory.firestore_conversation import FirestoreConversationStore  # lazy import
        project_id = os.environ.get("GCP_PROJECT_ID", "")
        database = os.environ.get("FIRESTORE_DATABASE", "(default)")
        store = FirestoreConversationStore(project_id=project_id, database=database)
        # get_full (not get): the hub shows the whole continuous conversation,
        # not just the active session window the agent uses (CR-02).
        msgs = store.get_full(user_id)
        # Add stable seq index for unread badge computation (CHAT-04 / D-11)
        return [{"seq": i, **msg} for i, msg in enumerate(msgs)]

    messages = await loop.run_in_executor(None, _get_messages)

    # _jsonsafe_doc on the full response (Pitfall 4 / T-26-05-06)
    payload = _jsonsafe_doc({"messages": messages})
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

    Reply is appended to the shared FirestoreConversationStore without a
    Telegram send — the hub polls /api/chat/messages to receive it.

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
    user_id = int(request_json.get("user_id", 0))

    # Run the agent turn inside this tracked request (full CPU — D-09).
    # handle_message is the single writer: it appends BOTH the user turn and the
    # assistant reply to the shared FirestoreConversationStore (core/main.py
    # lines 481/501), with no Telegram send on this hub path — the client polls
    # /api/chat/messages to receive the reply. We do NOT append here (doing so
    # double-wrote the assistant reply, CR-03).
    # asyncio.to_thread is safe: handle_message uses thread-local tool_registry.
    await asyncio.to_thread(_orchestrator.handle_message, content, user_id)

    return JSONResponse(content={"ok": True})


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

    async def lookup_path(self, path: str):  # type: ignore[override]
        full_path, stat_result = await super().lookup_path(path)
        if stat_result is None:
            # Unknown path — let the React Router handle it
            return await super().lookup_path("index.html")
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
