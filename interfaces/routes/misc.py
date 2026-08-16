"""Remaining Hub read surfaces: settings, reviews, activity, approvals, portfolio.

Small, mostly read-only endpoints that each back one Hub panel. Grouped rather
than given a module apiece because none of them is big enough to navigate to on
its own, and splitting further would trade one long file for ten short ones.
"""
from __future__ import annotations

import asyncio
import logging
import os
from datetime import date as _date_cls, datetime, timedelta
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse

from core.hub.reviews import _review_for_client
from interfaces.flags import (
    _flag_enabled,
    _routine_cutover_enabled,
    _subscription_capability_gate,
)
from interfaces.hub_auth import require_hub_session
from interfaces.routes._stores import _get_hub_settings_store

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/api/settings")
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


@router.post("/api/routines/{routine}/shadow")
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
    from core.routines.subscription import build_subscription_routine_coordinator

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


@router.get("/api/reviews")
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


@router.get("/api/reviews/{routine}/{target_date}")
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


@router.get("/api/activity")
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


@router.get("/api/approvals")
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


@router.get("/api/portfolio")
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


@router.get("/api/agent/status")
async def api_agent_status(
    _email: str = Depends(require_hub_session),
) -> JSONResponse:
    """Expose capability gates, routine state, and Ask Claude launch config."""
    from core.routines.delivery import public_routine_run
    from interfaces.mcp.server import EXPECTED_SKILL_VERSION
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
