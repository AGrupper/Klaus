"""Cloud Run service boundary for Klaus.

This module is the cloud entry point for the Klaus agent when deployed on
Google Cloud Run. It exposes retained Hub, MCP, routine, and sync routes:

    GET  /health             — liveness/startup probe (no auth, no init).
    POST /cron/deterministic-alerts — runs explicit notification rules.
    POST /mcp/*                    — serves scoped Claude capabilities.

Cold start opens only the retained Claude MCP session managers, so health and
Hub surfaces remain independent of any in-process generative runtime.

Container entry point:
    uvicorn interfaces.web_server:app --host 0.0.0.0 --port ${PORT:-8080} --workers 1

"""
from __future__ import annotations

import asyncio
import hmac
import logging
import os
from contextlib import AsyncExitStack, asynccontextmanager
from datetime import date as _date_cls, datetime, timedelta
from typing import AsyncGenerator
from zoneinfo import ZoneInfo

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.responses import JSONResponse

from interfaces.hub_auth import require_hub_session  # HUB-01: used by /api/* Depends

# Hub payload builders. These used to be defined here — roughly a third of this
# module — and are now in core/hub/ because they shape data rather than handle
# HTTP. They are imported into this namespace rather than called through their
# modules so the route handlers below read unchanged, and so the many tests that
# monkeypatch `web_server._today_calendar` and friends keep binding to the name
# the handlers actually resolve at call time.
from core.hub.today import (  # noqa: F401
    _COACH_NOTE_MAX_LEN,
    _DEFAULT_TRAVEL_MINUTES,
    _GET_READY_MINUTES,
    _SLOT_LABELS,
    _configured_travel_minutes,
    _sanitize_coach_note,
    _today_calendar,
    _today_coach_note,
    _today_departure_windows,
    _today_garmin,
    _today_meals,
    _today_nutrition_totals,
    _today_training,
    _today_weather,
)
from core.hub.health_series import (  # noqa: F401
    _HEALTH_CACHE_TTL_SECONDS,
    _MILEAGE_WEEKLY_THRESHOLD_DAYS,
    _NUTRITION_MACRO_KEYS,
    _SLOT_LABELS_HEALTH,
    _VALID_RANGES,
    _WEEKLY_BUCKET_THRESHOLD_DAYS,
    _health_nutrition_daily,
    _health_nutrition_profile,
    _health_nutrition_slots,
    _health_sleep_data,
    _health_sleep_pipeline_active,
    _health_training_benchmarks,
    _health_training_blocks,
    _health_training_runs,
    _health_training_strength,
    _hrv_baseline_with_fallback,
    _nutrition_daily_cache,
    _range_bounds,
    _resolve_calories_target,
    _resolve_range,
    _slot_label_for_meal,
    _week_axis_for_dates,
    _weekly_bucket_points,
)
from core.hub.reviews import _REVIEW_CLIENT_FIELDS, _review_for_client  # noqa: F401

# Route modules. Each owns one surface and exposes an APIRouter; include_flat
# registers them so their routes stay visible in app.routes (see
# interfaces/routes/__init__.py for why that matters).
from interfaces.flags import (
    _flag_enabled,
    _routine_cutover_enabled,
    _subscription_capability_gate,
)
from interfaces.routes import iter_routes
from interfaces.routes.retired import (  # noqa: F401
    retired_cloud_agent_runtime,
    retired_hub_chat_runtime,
)
from interfaces.routes._stores import _get_hub_settings_store
from interfaces.routes import auth as auth_routes
from interfaces.routes import hub_health as hub_health_routes
from interfaces.routes import hub_today as hub_today_routes
from interfaces.routes import misc as misc_routes
from interfaces.routes import habits as habits_routes
from interfaces.routes import push as push_routes
from interfaces.routes import retired as retired_routes
from interfaces.routes import tasks as tasks_routes

# WHY: override=True ensures .env values win even when the shell has already
# exported the variable. Tests may explicitly bypass local developer secrets so
# credential-free cold-start coverage is hermetic.
if os.environ.get("KLAUS_SKIP_DOTENV", "false").strip().lower() not in {
    "1", "true", "yes", "on",
}:
    load_dotenv(override=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s"
)

logger = logging.getLogger(__name__)

# ------------------------------------------------------------------ #
# Module-level singletons (populated during lifespan startup)        #
# ------------------------------------------------------------------ #

_mcp_bundle = None


# ------------------------------------------------------------------ #
# FastAPI lifespan                                                    #
# ------------------------------------------------------------------ #

@asynccontextmanager
async def lifespan(fastapi_app: FastAPI) -> AsyncGenerator[None, None]:
    """Initialise and shut down the Klaus singletons around the server lifetime.

    Runs once when the Cloud Run container becomes ready to serve traffic.
    Keeping all heavyweight initialisation here (rather than at import time)
    means ``/health`` responds immediately even if Firestore, MCP, or
    Google OAuth are still waking up.

    Args:
        fastapi_app: The ``FastAPI`` instance (provided by the framework; unused
                     directly but required by the lifespan protocol).

    Yields:
        None — control returns to FastAPI, which starts serving requests.
    """
    mcp_stack = AsyncExitStack()
    await mcp_stack.__aenter__()
    if _mcp_bundle is not None:
        if _flag_enabled("KLAUS_CLAUDE_LIVE_ENABLED"):
            await mcp_stack.enter_async_context(
                _mcp_bundle.interactive.session_manager.run()
            )
        if _flag_enabled("KLAUS_CLAUDE_ROUTINES_ENABLED"):
            await mcp_stack.enter_async_context(_mcp_bundle.routine.session_manager.run())
        logger.info("Klaus MCP session managers initialised.")

    try:
        yield  # Server is live and handling requests from here.
    finally:
        await mcp_stack.aclose()


# ------------------------------------------------------------------ #
# FastAPI application                                                 #
# ------------------------------------------------------------------ #

app = FastAPI(
    title="Klaus – Cloud Run service",
    description="Authorization, data, action, routine, and Hub boundary for Klaus.",
    lifespan=lifespan,
)








_MCP_MOUNT_PATHS = frozenset({"/mcp/interactive", "/mcp/routine"})

_CONNECTOR_EVIDENCE = {
    "calendar": {"tools": {"list_calendar_events", "create_calendar_event"}},
    "google_routes": {"routes": {"GET /api/today"}},
    "things": {"tools": {"task_list", "task_create"}},
    "garmin": {"tools": {"fetch_garmin_today"}},
    "hevy": {"tools": {"get_strength_progress"}},
    "healthkit_lifesum": {"routes": {"POST /cron/healthkit-sync"}},
    "weather": {"tools": {"fetch_weather"}},
    "pinecone": {"tools": {"recall", "remember"}},
    "postgresql": {"tools": {"query_health_database"}},
    "firestore": {"tools": {"get_routine_status"}},
    "web_push": {"tools": {"get_push_health"}, "routes": {"POST /api/push/subscribe"}},
    "cloud_tasks": {"routes": {"POST /internal/routine-fallback"}},
}


def _runtime_inventory() -> dict:
    """Describe capabilities actually registered in this running revision."""
    routes: set[str] = set()
    for route in iter_routes(app):
        path = getattr(route, "path", "")
        for method in getattr(route, "methods", None) or ():
            if method not in {"HEAD", "OPTIONS"}:
                routes.add(f"{method} {path}")
    if _mcp_bundle is not None:
        routes.update(f"POST {path}" for path in _MCP_MOUNT_PATHS)
    registered_tools: set[str] = set()
    if _mcp_bundle is not None:
        registered_tools.update(
            getattr(_mcp_bundle.interactive, "_tool_manager")._tools
        )
        registered_tools.update(getattr(_mcp_bundle.routine, "_tool_manager")._tools)
    connectors = {
        name
        for name, evidence in _CONNECTOR_EVIDENCE.items()
        if set(evidence.get("tools", ())).issubset(registered_tools)
        and set(evidence.get("routes", ())).issubset(routes)
    }
    if _mcp_bundle is not None and _MCP_MOUNT_PATHS.issubset(
        {route.removeprefix("POST ") for route in routes if route.startswith("POST ")}
    ):
        connectors.add("claude_mcp")
    return {
        "observed_routes": sorted(routes),
        "connectors": sorted(connectors),
        "embedding": {
            "model": __import__("memory.pinecone_db", fromlist=["EMBEDDING_MODEL"]).EMBEDDING_MODEL,
            "daily_request_limit": __import__(
                "memory.pinecone_db", fromlist=["EMBEDDING_DAILY_REQUEST_LIMIT"]
            ).EMBEDDING_DAILY_REQUEST_LIMIT,
        },
        "tombstones": sorted(
            f"{method} {route.path}"
            for route in iter_routes(app)
            if getattr(route, "endpoint", None)
            in {retired_cloud_agent_runtime, retired_hub_chat_runtime}
            for method in getattr(route, "methods", None) or ()
            if method not in {"HEAD", "OPTIONS"}
        ),
    }


@app.middleware("http")
async def _normalize_mcp_mount_path(request: Request, call_next):
    """Route canonical no-slash MCP URLs into their root-mounted ASGI apps.

    Starlette mounts a child app's ``/`` route at ``<mount>/``. Ordinarily its
    router redirects ``<mount>`` there, but Klaus's final ``/`` SPA mount
    captures the request first and returns 405 for MCP POSTs. Rewriting only
    the two exact public MCP paths preserves the advertised OAuth resource URL
    and avoids a redirect that could drop the request body or bearer header.
    """
    path = request.scope.get("path")
    if path in _MCP_MOUNT_PATHS:
        request.scope["path"] = f"{path}/"
        request.scope["raw_path"] = f"{path}/".encode("ascii")
    return await call_next(request)


def _configure_subscription_interfaces() -> None:
    """Mount OAuth and independently gated stateless MCP resources."""
    global _mcp_bundle  # noqa: PLW0603

    if not _flag_enabled("KLAUS_MCP_ENABLED"):
        return
    from urllib.parse import urlsplit

    from mcp.server.transport_security import TransportSecuritySettings

    from interfaces.mcp_oauth import build_oauth_router
    from interfaces.mcp_runtime import (
        create_production_mcp_bundle,
        create_production_oauth_service,
    )

    oauth_service = create_production_oauth_service()
    _mcp_bundle = create_production_mcp_bundle(
        oauth_service,
        read_only=_flag_enabled("KLAUS_MCP_READ_ONLY_MODE", default=True),
    )
    app.include_router(build_oauth_router(oauth_service, require_hub_session))

    parsed = urlsplit(oauth_service.issuer_url)
    allowed_hosts = [parsed.netloc, "localhost:*", "127.0.0.1:*"]
    allowed_origins = [
        oauth_service.issuer_url,
        "https://claude.ai",
        "https://claude.com",
    ]
    transport_security = TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=allowed_hosts,
        allowed_origins=allowed_origins,
    )
    if _flag_enabled("KLAUS_CLAUDE_LIVE_ENABLED"):
        app.mount(
            "/mcp/interactive",
            _mcp_bundle.interactive.streamable_http_app(
                streamable_http_path="/",
                stateless_http=True,
                json_response=True,
                transport_security=transport_security,
            ),
            name="mcp-interactive",
        )
    if _flag_enabled("KLAUS_CLAUDE_ROUTINES_ENABLED"):
        app.mount(
            "/mcp/routine",
            _mcp_bundle.routine.streamable_http_app(
                streamable_http_path="/",
                stateless_http=True,
                json_response=True,
                transport_security=transport_security,
            ),
            name="mcp-routine",
        )


_configure_subscription_interfaces()

app.include_router(tasks_routes.router)
app.include_router(habits_routes.router)
app.include_router(push_routes.router)
app.include_router(auth_routes.router)
app.include_router(retired_routes.router)
app.include_router(hub_today_routes.router)
app.include_router(hub_health_routes.router)
app.include_router(misc_routes.router)


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


@app.get("/health/inventory")
async def health_inventory() -> JSONResponse:
    """Expose non-sensitive live capability metadata for drift audits."""
    return JSONResponse(content={"status": "ok", **_runtime_inventory()})






@app.post("/internal/routine-fallback")
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


async def _verify_morning_trigger_request(request: Request) -> None:
    """Verify a shared-secret bearer token from the iOS Sleep-Focus-off Shortcut.

    Byte-for-byte mirror of _verify_trigger_request, with MORNING_TRIGGER_TOKEN
    in place of NIGHTLY_TRIGGER_TOKEN. D-13: this is a DISTINCT secret — no
    fallback to NIGHTLY_TRIGGER_TOKEN — so a leaked credential does not unlock
    every proactive surface.

    Mirrors _verify_healthkit_request exactly (constant-time compare, refuse-all on
    unset env, redacted-prefix logging).

    Raises:
        HTTPException 401: Missing / malformed Authorization header.
        HTTPException 403: Bearer present but does not match the secret.
        HTTPException 500: MORNING_TRIGGER_TOKEN env unset (refuse-all).
    """
    if os.getenv("CRON_DEV_BYPASS", "false").lower() == "true":
        logger.info("CRON_DEV_BYPASS=true — skipping morning-trigger auth")
        return

    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(
            status_code=401,
            detail={"error": "Missing or malformed Authorization header"},
        )

    received = auth_header.removeprefix("Bearer ").strip()
    expected = os.environ.get("MORNING_TRIGGER_TOKEN", "")
    if not expected:
        # WHY: refuse-all on unset env prevents a fail-open if the Secret Manager
        # mount silently fails — surfaces as a 500 the operator can detect rather
        # than letting any random POST trigger a send.
        logger.error("MORNING_TRIGGER_TOKEN env unset — refusing all morning-trigger auth")
        raise HTTPException(status_code=500, detail={"error": "Server misconfigured"})

    if not hmac.compare_digest(received.encode(), expected.encode()):
        client = request.client.host if request.client else "?"
        redacted = received[:4] + "..." + received[-4:] if len(received) >= 8 else "***"
        logger.warning("morning-trigger auth failed from %s (token_prefix=%s)", client, redacted)
        raise HTTPException(status_code=403, detail={"error": "Invalid token"})


def _log_cron_run(job_id: str, ok: bool, *, backlog_done: bool | None = None) -> None:
    """Best-effort liveness ledger write for a cron endpoint. Never raises."""
    try:
        from memory.firestore_db import record_cron_run
        record_cron_run(job_id, ok, backlog_done=backlog_done)
    except Exception:
        logger.warning("Failed to record cron run for %s", job_id, exc_info=True)





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





@app.post("/trigger/nightly")
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
@app.post("/trigger/morning")
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


@app.post("/cron/nightly-backstop")
async def cron_nightly_backstop(request: Request) -> JSONResponse:
    """Safety-net for the nightly review if the Sleep-Focus trigger never fired.

    Schedule: 0 1 * * *  (Asia/Jerusalem) — ~01:00. Authenticated via OIDC bearer.
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
    target = nightly_target_date_now()
    if _routine_cutover_enabled("nightly"):
        response = await _start_subscription_routine("nightly", target, "backstop")
        _log_cron_run("nightly-backstop", ok=response.status_code == 202)
        return response
    _log_cron_run("nightly-backstop", ok=False)
    raise HTTPException(
        status_code=503,
        detail={"error": "Claude nightly Routine cutover is unavailable"},
    )


@app.post("/cron/morning-backstop")
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


@app.post("/cron/deterministic-alerts")
async def cron_deterministic_alerts(request: Request) -> JSONResponse:
    """Run deterministic daytime rules with no legacy runtime dependency."""
    await _verify_cron_request(request)
    from core.deterministic_alerts import run_rule_evaluator

    try:
        result = await run_rule_evaluator()
        _log_cron_run("deterministic-alerts", ok=True)
    except Exception:
        _log_cron_run("deterministic-alerts", ok=False)
        raise
    return JSONResponse(content={"ok": True, **result})


@app.post("/cron/weekly-training-review")
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


@app.post("/cron/healthkit-sync")
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


@app.post("/cron/strength-sync")
async def cron_strength_sync(request: Request) -> JSONResponse:
    """Receive Cloud Scheduler daily tick and run a bounded Hevy strength-sync batch.

    Schedule: 0 5 * * *  (Asia/Jerusalem)
    Authenticated via OIDC bearer token from Cloud Scheduler.

    Pull-only with no conversation-runtime dependency. The only sink is
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


@app.post("/cron/things-sync")
async def cron_things_sync(request: Request) -> JSONResponse:
    """Receive a Cloud Scheduler tick and refresh the Things 3 mirror.

    Schedule: */30 6-23 * * *  (Asia/Jerusalem)
    Authenticated via OIDC bearer token from Cloud Scheduler.

    Pull-only with no conversation-runtime dependency. The only sink is the
    Firestore mirror (via core.things_ingest.run_one_batch).

    A backstop, not the primary path: ThingsTaskStore checks the journal head on
    every read and pulls its own delta, so conversational reads are already fresh.
    This keeps the mirror warm for cold starts, and keeps the fallback that reads
    degrade to hours old rather than days when Things Cloud is unreachable.

    Returns:
        JSONResponse: status dict (ok, mode, cursor, entities, open_todos, done).
    """
    await _verify_cron_request(request)
    import asyncio as _asyncio
    import core.things_ingest as _things
    try:
        loop = _asyncio.get_running_loop()
        result = await loop.run_in_executor(None, _things.run_one_batch)
        _log_cron_run("things-sync", ok=bool(result.get("ok")), backlog_done=result.get("done"))
        return JSONResponse(content=result)
    except Exception:
        _log_cron_run("things-sync", ok=False)
        raise


@app.post("/cron/run-sync")
async def cron_run_sync(request: Request) -> JSONResponse:
    """Receive Cloud Scheduler daily tick and run a bounded Garmin run-detail batch.

    Schedule: 15 5 * * *  (Asia/Jerusalem) — staggered after strength-sync (05:00)
    to spread Garmin login load.
    Authenticated via OIDC bearer token from Cloud Scheduler.

    Pull-only with no conversation-runtime dependency. The only sink is
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

    Pull-only with no conversation-runtime dependency. The only sink is
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
    from core.heartbeat import collect_deterministic_signals

    try:
        signals = await asyncio.to_thread(collect_deterministic_signals)
        _log_cron_run("heartbeat", ok=True)
    except Exception:
        _log_cron_run("heartbeat", ok=False)
        raise
    return JSONResponse(content={"ok": True, "signals": [signal.__dict__ for signal in signals]})


# --------------------------------------------------------------------------- #
# Hub auth routes — /api/auth/*                                               #
#                                                                             #
# These routes provide Google Sign-In session auth for the Klaus Hub (HUB-01).#
# They must be registered BEFORE the SPAStaticFiles mount (Pitfall 1).       #
# Existing /cron/* and /internal/* routes are untouched (HUB-04).            #
# --------------------------------------------------------------------------- #









# --------------------------------------------------------------------------- #
# /api/today — read-only Today timeline aggregator (Plan 26-04, TIME-01..05, #
# TIME-08). Behind require_hub_session (HUB-01). All sync tool calls run via  #
# run_in_executor + asyncio.gather (Pitfall 2). Every Firestore-derived value #
# passes through _jsonsafe_doc before JSONResponse (Pitfall 4).               #
#                                                                              #
# MUST be registered BEFORE the SPA mount (Pitfall 1).                        #
# --------------------------------------------------------------------------- #
































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











# --------------------------------------------------------------------------- #
# GET /api/health/training (HLTH-01) — mixed strength+run+benchmark log,      #
# block dividers, two trend series.                                          #
# --------------------------------------------------------------------------- #












# --------------------------------------------------------------------------- #
# GET /api/health/nutrition (HLTH-02) — macro trend series, slot-adherence    #
# grid, targets. The day-series math is EXTRACTED from                       #
# core.tools._handle_fetch_nutrition_trend (_compute_nutrition_averages /     #
# _nutrition_targets_and_protein_ratio) — shared, not reimplemented, so the   #
# chat tool and this route can never drift (RESEARCH.md Anti-Patterns).      #
# --------------------------------------------------------------------------- #

















# --------------------------------------------------------------------------- #
# GET /api/health/sleep (HLTH-03) — HRV/sleep/body-battery trend series +     #
# header stat row + pipeline_active guard. Postgres read is ALWAYS wrapped    #
# in run_in_executor (Pitfall 3 — the 2026-06-24 weekly-review-500 incident   #
# class: a synchronous psycopg2 call inside async def starves the event loop).#
# --------------------------------------------------------------------------- #










# --------------------------------------------------------------------------- #
from pydantic import BaseModel, Field  # noqa: E402 (lazy placement — keeps cold-start fast)
from typing import Literal  # noqa: E402










# ------------------------------------------------------------------
# /api/tasks routes
# ------------------------------------------------------------------

















# ------------------------------------------------------------------
# /api/task-lists routes
# ------------------------------------------------------------------









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








# ------------------------------------------------------------------
# /api/habits/summary — literal path BEFORE /api/habits/{habit_id}
# ------------------------------------------------------------------



# ------------------------------------------------------------------
# /api/habits routes
# ------------------------------------------------------------------

















# --------------------------------------------------------------------------- #
# Web Push + Hub Settings routes — /api/push/*, /api/settings                 #
# Plan 29-06, PUSH-01 / PUSH-03                                               #
#                                                                             #
# All routes are behind Depends(require_hub_session) (T-29-10). Every         #
# subscribe input is validated (https endpoint + p256dh/auth keys present,    #
# T-29-11) before it ever reaches PushSubscriptionStore.upsert. PATCH         #
# Settings are read-only and expose only retained Web Push state. All sync    #
# Firestore calls run via loop.run_in_executor (Pitfall 2). Place BEFORE the  #
# SPA mount so                                                               #
# these routes are reachable (Pitfall 1).                                    #
# --------------------------------------------------------------------------- #













# --------------------------------------------------------------------------- #
# Klaus v7 subscription-first read models                                    #
# --------------------------------------------------------------------------- #


















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
