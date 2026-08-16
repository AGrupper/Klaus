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


def _flag_enabled(name: str, *, default: bool = False) -> bool:
    """Return a strict boolean feature flag from the environment."""
    fallback = "true" if default else "false"
    return os.environ.get(name, fallback).strip().lower() in {"1", "true", "yes", "on"}


def _subscription_capability_gate() -> dict:
    """Report the four manual Claude Pro proofs that must precede cutover."""
    checks = {
        "mcp_connector_verified": _flag_enabled("KLAUS_CAPABILITY_MCP_VERIFIED"),
        "private_skill_verified": _flag_enabled("KLAUS_CAPABILITY_SKILL_VERIFIED"),
        "remote_routine_verified": _flag_enabled("KLAUS_CAPABILITY_ROUTINE_VERIFIED"),
        "routine_publish_verified": _flag_enabled("KLAUS_CAPABILITY_PUBLISH_VERIFIED"),
    }
    return {**checks, "passed": all(checks.values())}


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
    for route in app.routes:
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
            for route in app.routes
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


@app.post("/telegram-webhook")
@app.post("/internal/process-update")
@app.post("/internal/process-occasion")
@app.post("/cron/proactive-alerts")
@app.post("/cron/reflect")
@app.post("/cron/autonomous-tick")
@app.post("/cron/ingest-chats")
@app.post("/cron/ingest-chat-exports")
async def retired_cloud_agent_runtime() -> JSONResponse:
    """Quarantine removed Cloud-hosted conversation and reasoning routes."""
    return JSONResponse(
        status_code=410,
        content={"detail": {"error": "Cloud agent runtime retired; use Claude"}},
    )


@app.post("/internal/process-hub-message")
@app.post("/api/chat")
@app.post("/api/chat/upload")
@app.get("/api/chat/messages")
@app.post("/api/chat/regenerate")
@app.post("/api/chat/stop")
async def retired_hub_chat_runtime() -> JSONResponse:
    """Quarantine removed Hub chat and attachment routes."""
    return JSONResponse(
        status_code=410,
        content={"detail": {"error": "Hub chat retired; use the configured Claude Project"}},
    )


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


def _routine_cutover_enabled(routine: str) -> bool:
    """Return whether one routine has independently cut over to Claude."""
    return (
        _flag_enabled("KLAUS_MCP_ENABLED")
        and _flag_enabled("KLAUS_CLAUDE_ROUTINES_ENABLED")
        and _subscription_capability_gate()["passed"]
        and _flag_enabled(f"KLAUS_ROUTINE_{routine.upper()}_CUTOVER")
    )


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
        # OAuth begins as a cross-site top-level GET from Claude. Lax permits
        # that safe navigation but still withholds the cookie on cross-site
        # POST mutations; OAuth state + PKCE bind the authorization response.
        samesite="lax",
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
    _email: str = Depends(require_hub_session),
) -> JSONResponse:
    """Bump session_version to invalidate every previously-issued cookie (D-02).

    Also clears the cookie on the current device. After this call every existing
    session cookie (on every device) will fail the version check and return 401.

    Requires an active session cookie via Depends(require_hub_session).
    Declared as a dependency rather than called in the body so the gate is
    visible to route introspection — an in-body call is equally secure but
    invisible to the test that proves no /api route is left unguarded.
    Intended for "lost phone" scenarios.

    Raises:
        HTTPException 401: No valid session cookie.
        HTTPException 500: HUB_SESSION_SECRET or Firestore unavailable.
    """
    import interfaces.hub_auth as _hub_auth  # lazy import — Shared Pattern 5
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

    # Phase 2: departure windows depend on calendar output (per-event).
    calendar_with_routes = await loop.run_in_executor(
        None, _today_departure_windows, calendar_data
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











# --------------------------------------------------------------------------- #
# GET /api/health/training (HLTH-01) — mixed strength+run+benchmark log,      #
# block dividers, two trend series.                                          #
# --------------------------------------------------------------------------- #










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
    estimated_minutes: int | None = Field(None, ge=1, le=1_440)
    hard_deadline_at: datetime | None = None
    auto_schedule: bool | None = None
    manual_lock: bool | None = None
    calendar_event_id: str | None = Field(None, max_length=1_024)


class UpdateTaskInput(BaseModel):
    """Pydantic model for PATCH /api/tasks/{id} bodies (all fields optional)."""

    title: str | None = Field(None, min_length=1, max_length=500)
    notes: str | None = Field(None, max_length=10_000)
    due_date: str | None = Field(None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    due_time: str | None = Field(None, pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    priority: Literal["none", "low", "medium", "high"] | None = None
    list_id: str | None = None
    recurrence: RecurrenceInput | None = None
    estimated_minutes: int | None = Field(None, ge=1, le=1_440)
    hard_deadline_at: datetime | None = None
    auto_schedule: bool | None = None
    manual_lock: bool | None = None
    calendar_event_id: str | None = Field(None, max_length=1_024)


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
    """Create a new task in the authoritative Things store.

    POST /api/tasks with a CreateTaskInput body.  list_id defaults to "inbox"
    when None is supplied (Inbox is implicit — no Firestore doc exists for it).

    Returns:
        JSONResponse: The created task dict (id, title, status, …).
    Raises:
        HTTPException 401: No valid session cookie.
        HTTPException 422: Pydantic validation failure (T-27-IV).
    """
    from memory.firestore_db import _jsonsafe_doc, get_task_store  # lazy import — Shared Pattern 5

    task_dict = body.model_dump(exclude_none=False, mode="json")
    # Coerce None list_id → "inbox" (D-07 from RESEARCH: Inbox is implicit)
    if not task_dict.get("list_id"):
        task_dict["list_id"] = "inbox"

    loop = asyncio.get_running_loop()
    store = get_task_store(
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
    from memory.firestore_db import _jsonsafe_doc, get_task_store  # lazy import

    today_iso = datetime.now(ZoneInfo("Asia/Jerusalem")).date().isoformat()
    loop = asyncio.get_running_loop()
    store = get_task_store(
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
    from memory.firestore_db import _jsonsafe_doc, get_task_store  # lazy import

    loop = asyncio.get_running_loop()
    store = get_task_store(
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
    from memory.firestore_db import _jsonsafe_doc, get_task_store  # lazy import

    # Only pass fields that were explicitly provided (exclude unset so None
    # values don't overwrite set fields that weren't sent in this PATCH).
    patch = body.model_dump(exclude_unset=True, mode="json")
    loop = asyncio.get_running_loop()
    store = get_task_store(
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
    from memory.firestore_db import _jsonsafe_doc, get_task_store  # lazy import

    completed_on_iso = datetime.now(ZoneInfo("Asia/Jerusalem")).date().isoformat()
    loop = asyncio.get_running_loop()
    store = get_task_store(
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
    from memory.firestore_db import get_task_store  # lazy import

    loop = asyncio.get_running_loop()
    store = get_task_store(
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
    from memory.firestore_db import get_task_store  # lazy import

    loop = asyncio.get_running_loop()
    store = get_task_store(
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
    """Trash a completing Things task after the Hub undo window.

    POST /api/tasks/{task_id}/hard-delete — T-27-REP.

    A replayed or forged delete of an active task is rejected with 409: the task
    must first go through the soft-complete flow so the UI always has an undo
    window. Things receives a recoverable trash edit, never a hard delete.

    Returns:
        JSONResponse: {"ok": True}
    Raises:
        HTTPException 401: No valid session cookie.
        HTTPException 409: Task is not in 'completing' state (T-27-REP).
    """
    from memory.firestore_db import get_task_store  # lazy import

    loop = asyncio.get_running_loop()
    store = get_task_store(
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
    from memory.firestore_db import _jsonsafe_doc, get_task_store  # lazy import

    loop = asyncio.get_running_loop()
    store = get_task_store(
        project_id=os.environ.get("GCP_PROJECT_ID", ""),
        database=os.environ.get("FIRESTORE_DATABASE", "(default)"),
    )
    created = await loop.run_in_executor(None, store.create_list, body.name)
    return JSONResponse(content=_jsonsafe_doc(created))


@app.get("/api/task-lists")
async def api_list_task_lists(
    _email: str = Depends(require_hub_session),
) -> JSONResponse:
    """List all user-defined task lists, with the implicit Inbox prepended.

    GET /api/task-lists — TASK-02.

    WHY Inbox is prepended: the "inbox" list_id is implicit (no Things project).
    The route always inserts it at
    position 0 so the frontend can render a stable "Inbox" entry without
    special-casing an empty-document fallback.

    Returns:
        JSONResponse: {"lists": [{"id": "inbox", "name": "Inbox"}, ...user lists]}
    Raises:
        HTTPException 401: No valid session cookie.
    """
    from memory.firestore_db import _jsonsafe_doc, get_task_store  # lazy import

    loop = asyncio.get_running_loop()
    store = get_task_store(
        project_id=os.environ.get("GCP_PROJECT_ID", ""),
        database=os.environ.get("FIRESTORE_DATABASE", "(default)"),
    )
    user_lists = await loop.run_in_executor(None, store.list_lists)
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
    from memory.firestore_db import _jsonsafe_doc, get_task_store  # lazy import

    loop = asyncio.get_running_loop()
    store = get_task_store(
        project_id=os.environ.get("GCP_PROJECT_ID", ""),
        database=os.environ.get("FIRESTORE_DATABASE", "(default)"),
    )
    updated = await loop.run_in_executor(None, store.rename_list, list_id, body.name)
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
    from memory.firestore_db import get_task_store  # lazy import

    loop = asyncio.get_running_loop()
    store = get_task_store(
        project_id=os.environ.get("GCP_PROJECT_ID", ""),
        database=os.environ.get("FIRESTORE_DATABASE", "(default)"),
    )
    await loop.run_in_executor(None, store.delete_list, list_id)
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
# Settings are read-only and expose only retained Web Push state. All sync    #
# Firestore calls run via loop.run_in_executor (Pitfall 2). Place BEFORE the  #
# SPA mount so                                                               #
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

    GET /api/settings includes retained Web Push state.

    Returns:
        JSONResponse: The hub settings dict, jsonsafe.
    Raises:
        HTTPException 401: No valid session cookie (via require_hub_session).
    """
    from memory.firestore_db import _jsonsafe_doc  # lazy import — Shared Pattern 5 / Pitfall 4

    loop = asyncio.get_running_loop()
    settings = _jsonsafe_doc(
        await loop.run_in_executor(None, _get_hub_settings_store().get)
    )
    return JSONResponse(content={"push_enabled_at": settings.get("push_enabled_at")})


# --------------------------------------------------------------------------- #
# Klaus v7 subscription-first read models                                    #
# --------------------------------------------------------------------------- #

@app.post("/api/routines/{routine}/shadow")
async def api_shadow_routine(
    routine: str,
    request: Request,
    _email: str = Depends(require_hub_session),
) -> JSONResponse:
    """Run one subscription routine without publishing, pushing, or writing memory."""
    if routine not in {"morning", "nightly", "weekly"}:
        raise HTTPException(status_code=404, detail={"error": "unknown routine"})
    if not (
        _flag_enabled("KLAUS_MCP_ENABLED")
        and _flag_enabled("KLAUS_CLAUDE_ROUTINES_ENABLED")
    ):
        raise HTTPException(
            status_code=409, detail={"error": "Claude routine interface disabled"}
        )
    body = await request.json()
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail={"error": "body must be an object"})
    target_date = str(
        body.get("target_date")
        or datetime.now(ZoneInfo("Asia/Jerusalem")).date().isoformat()
    )
    try:
        _date_cls.fromisoformat(target_date)
    except ValueError as exc:
        raise HTTPException(
            status_code=400, detail={"error": "target_date must be YYYY-MM-DD"}
        ) from exc
    from core.subscription_routines import build_subscription_routine_coordinator

    coordinator = build_subscription_routine_coordinator()
    result = await asyncio.get_running_loop().run_in_executor(
        None,
        lambda: coordinator.start(
            routine,
            target_date,
            "operator_shadow",
            delivery_mode="shadow",
        ),
    )
    return JSONResponse(
        status_code=202 if result.get("accepted") else 503,
        content=result,
    )





@app.get("/api/reviews")
async def api_reviews(
    limit: int = Query(default=20, ge=1, le=60),
    _email: str = Depends(require_hub_session),
) -> JSONResponse:
    """Return published morning, nightly, and weekly reviews for the inbox."""
    from memory.firestore_db import RoutineReviewStore, RoutineRunStore, _jsonsafe_doc

    project = os.environ.get("GCP_PROJECT_ID", "klaus-agent")
    database = os.environ.get("FIRESTORE_DATABASE", "klaus-firestore")
    reviews_store = RoutineReviewStore(project, database)
    runs_store = RoutineRunStore(project, database)

    def load_reviews() -> list[dict]:
        reviews = reviews_store.list_recent(min(limit, 31))
        return [
            _review_for_client(review, runs_store)
            for review in reviews[:limit]
        ]

    reviews = await asyncio.get_running_loop().run_in_executor(None, load_reviews)
    return JSONResponse(
        content={"reviews": [_jsonsafe_doc(review) for review in reviews]}
    )


@app.get("/api/reviews/{routine}/{target_date}")
async def api_review_detail(
    routine: Literal["morning", "nightly", "weekly"],
    target_date: str,
    _email: str = Depends(require_hub_session),
) -> JSONResponse:
    """Return one canonical review, recovering only a safe legacy session URL."""
    try:
        parsed_date = _date_cls.fromisoformat(target_date)
    except (TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=422, detail={"error": "target_date must be YYYY-MM-DD"}
        ) from exc
    if parsed_date.isoformat() != target_date:
        raise HTTPException(
            status_code=422, detail={"error": "target_date must be YYYY-MM-DD"}
        )

    from memory.firestore_db import RoutineReviewStore, RoutineRunStore, _jsonsafe_doc

    project = os.environ.get("GCP_PROJECT_ID", "klaus-agent")
    database = os.environ.get("FIRESTORE_DATABASE", "klaus-firestore")
    reviews_store = RoutineReviewStore(project, database)
    runs_store = RoutineRunStore(project, database)

    def load_review() -> dict | None:
        review = reviews_store.get(routine, target_date)
        return _review_for_client(review, runs_store) if review is not None else None

    review = await asyncio.get_running_loop().run_in_executor(None, load_review)
    if review is None:
        raise HTTPException(status_code=404, detail={"error": "review not found"})
    return JSONResponse(content={"review": _jsonsafe_doc(review)})


@app.get("/api/activity")
async def api_activity(
    days: int = Query(default=7, ge=1, le=30),
    _email: str = Depends(require_hub_session),
) -> JSONResponse:
    """Assemble, but do not merge, review/outreach/action source records."""
    from memory.firestore_db import (
        ActionLogStore,
        OutreachLogStore,
        RoutineReviewStore,
        _jsonsafe_doc,
    )

    project = os.environ.get("GCP_PROJECT_ID", "klaus-agent")
    database = os.environ.get("FIRESTORE_DATABASE", "klaus-firestore")
    loop = asyncio.get_running_loop()
    reviews_store = RoutineReviewStore(project, database)
    actions_store = ActionLogStore(project, database)
    outreach_store = OutreachLogStore(project, database)
    today = datetime.now(ZoneInfo("Asia/Jerusalem")).date()

    def load_outreach() -> list[dict]:
        records = []
        for offset in range(days):
            day = (today - timedelta(days=offset)).isoformat()
            records.extend(outreach_store.get_today(day))
        return records

    reviews, actions, outreach = await asyncio.gather(
        loop.run_in_executor(None, reviews_store.list_recent, min(days, 31)),
        loop.run_in_executor(None, actions_store.get_recent, days),
        loop.run_in_executor(None, load_outreach),
    )
    activity = []
    activity.extend(
        {
            "type": "review",
            "id": item.get("review_id"),
            "at": item.get("published_at") or item.get("target_date"),
            "record": item,
        }
        for item in reviews
    )
    activity.extend(
        {
            "type": "action",
            "id": item.get("id"),
            "at": item.get("at"),
            "record": item,
        }
        for item in actions
    )
    activity.extend(
        {
            "type": "outreach",
            "id": item.get("id") or item.get("topic_key"),
            "at": item.get("at"),
            "record": item,
        }
        for item in outreach
    )
    activity.sort(key=lambda item: str(item.get("at") or ""), reverse=True)
    return JSONResponse(content={"activity": _jsonsafe_doc(activity)})


@app.get("/api/approvals")
async def api_approvals(
    _email: str = Depends(require_hub_session),
) -> JSONResponse:
    """Return immutable high-risk actions awaiting confirmation."""
    from memory.firestore_db import PendingApprovalStore, _jsonsafe_doc

    store = PendingApprovalStore(
        os.environ.get("GCP_PROJECT_ID", "klaus-agent"),
        os.environ.get("FIRESTORE_DATABASE", "klaus-firestore"),
    )
    approvals = await asyncio.get_running_loop().run_in_executor(None, store.list_pending)
    return JSONResponse(content={"approvals": _jsonsafe_doc(approvals)})


@app.get("/api/portfolio")
async def api_portfolio(
    snapshot_limit: int = Query(default=12, ge=1, le=52),
    _email: str = Depends(require_hub_session),
) -> JSONResponse:
    """Return active holdings and recent weekly ILS snapshots."""
    from memory.firestore_db import (
        PortfolioHoldingStore,
        PortfolioSnapshotStore,
        _jsonsafe_doc,
    )

    project = os.environ.get("GCP_PROJECT_ID", "klaus-agent")
    database = os.environ.get("FIRESTORE_DATABASE", "klaus-firestore")
    holdings = PortfolioHoldingStore(project, database)
    snapshots = PortfolioSnapshotStore(project, database)
    loop = asyncio.get_running_loop()
    holdings_data, snapshot_data = await asyncio.gather(
        loop.run_in_executor(None, holdings.list_active),
        loop.run_in_executor(None, snapshots.list_recent, snapshot_limit),
    )
    last_valid = snapshot_data[0] if snapshot_data else None
    return JSONResponse(
        content=_jsonsafe_doc(
            {
                "holdings": holdings_data,
                "snapshots": snapshot_data,
                "last_valid_valuation": last_valid,
            }
        )
    )


@app.get("/api/agent/status")
async def api_agent_status(
    _email: str = Depends(require_hub_session),
) -> JSONResponse:
    """Expose capability gates, routine state, and Ask Claude launch config."""
    from core.review_delivery import public_routine_run
    from interfaces.mcp_server import EXPECTED_SKILL_VERSION
    from memory.firestore_db import RoutineRunStore, _jsonsafe_doc

    project = os.environ.get("GCP_PROJECT_ID", "klaus-agent")
    database = os.environ.get("FIRESTORE_DATABASE", "klaus-firestore")
    runs = await asyncio.get_running_loop().run_in_executor(
        None, RoutineRunStore(project, database).list_recent, 20
    )
    project_url = os.environ.get("CLAUDE_PROJECT_URL", "")
    gate = _subscription_capability_gate()
    embedding_usage = {}
    canonical_user_id = os.environ.get("KLAUS_USER_ID", "")
    try:
        from memory.firestore_db import EmbeddingUsageStore

        embedding_usage = await asyncio.get_running_loop().run_in_executor(
            None,
            EmbeddingUsageStore(project, database).summary,
            canonical_user_id,
            "today",
        )
    except Exception:
        logger.warning("Could not read embedding quota health", exc_info=True)
    embedding_request_count = max(0, int(embedding_usage.get("embedding_calls", 0)))
    embedding_daily_limit = max(1, int(embedding_usage.get("daily_limit", 200)))
    return JSONResponse(
        content=_jsonsafe_doc(
            {
                "interface": "claude_project",
                "claude_project_url": project_url or None,
                "ask_claude_configured": bool(project_url),
                "expected_skill_version": EXPECTED_SKILL_VERSION,
                "capability_gate": gate,
                "features": {
                    "mcp": _flag_enabled("KLAUS_MCP_ENABLED"),
                    "live": _flag_enabled("KLAUS_CLAUDE_LIVE_ENABLED"),
                    "routines": _flag_enabled("KLAUS_CLAUDE_ROUTINES_ENABLED"),
                    "morning_cutover": _routine_cutover_enabled("morning"),
                    "nightly_cutover": _routine_cutover_enabled("nightly"),
                    "weekly_cutover": _routine_cutover_enabled("weekly"),
                },
                "recent_runs": [public_routine_run(run) for run in runs],
                "usage": {
                    "claude_subscription": {
                        "run_count": len(runs),
                        "funding": "subscription",
                        "cost_usd": None,
                    },
                    "gemini_embeddings": {
                        "cost_usd": embedding_usage.get("embedding_cost_usd"),
                        "request_count": embedding_request_count,
                        "daily_limit": embedding_daily_limit,
                        "daily_remaining": max(
                            0, embedding_daily_limit - embedding_request_count
                        ),
                        "input_tokens": embedding_usage.get("embedding_input_tokens", 0),
                        "item_count": embedding_usage.get("embedding_items", 0),
                        "measurement": (
                            "provider_tokens_at_configured_rate"
                            if os.environ.get("GEMINI_EMBEDDING_COST_PER_MILLION_TOKENS")
                            else "provider_tokens_only_rate_not_configured"
                        ),
                    },
                },
            }
        )
    )


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
