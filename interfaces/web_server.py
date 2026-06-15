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
from fastapi import BackgroundTasks, FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from telegram import Update
from telegram.ext import Application

from core.main import AgentOrchestrator
from core.task_dispatch import enqueue_update
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
