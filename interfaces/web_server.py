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

import logging
import os
from contextlib import AsyncExitStack, asynccontextmanager
from typing import AsyncGenerator

from dotenv import load_dotenv
from fastapi import FastAPI, Request

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
)
from interfaces.routes import iter_routes
from interfaces.routes.retired import (  # noqa: F401
    retired_cloud_agent_runtime,
    retired_hub_chat_runtime,
)
from interfaces.routes import auth as auth_routes
from interfaces.routes import cron as cron_routes
from interfaces.routes import health as health_routes
from interfaces.routes import hub_health as hub_health_routes
from interfaces.routes import hub_today as hub_today_routes
from interfaces.routes import misc as misc_routes
from interfaces.routes import sync as sync_routes
from interfaces.routes import triggers as trigger_routes
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

    from interfaces.mcp.oauth import build_oauth_router
    from interfaces.mcp.runtime import (
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
app.include_router(health_routes.router)
app.include_router(trigger_routes.router)
app.include_router(cron_routes.router)
app.include_router(sync_routes.router)


# ------------------------------------------------------------------ #
# Routes                                                              #
# ------------------------------------------------------------------ #











# ------------------------------------------------------------------ #
# Cloud Scheduler OIDC verification                                  #
# ------------------------------------------------------------------ #













































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
