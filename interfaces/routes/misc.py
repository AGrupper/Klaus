"""Remaining Hub read surfaces: settings, reviews, activity, approvals, portfolio.

Small, mostly read-only endpoints that each back one Hub panel. Grouped rather
than given a module apiece because none of them is big enough to navigate to on
its own, and splitting further would trade one long file for ten short ones.
"""
from __future__ import annotations

import asyncio
import logging
import os
import unicodedata
from datetime import date as _date_cls, datetime, timedelta
from typing import Annotated, Literal
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator

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
    return JSONResponse(content={
        "push_enabled_at": settings.get("push_enabled_at"),
        "appearance": settings.get("appearance"),
        "home_sections": settings.get("home_sections"),
        "bell_last_seen": settings.get("bell_last_seen"),
        "bell_read_ids": settings.get("bell_read_ids") or [],
    })


#: Cap on stored bell read ids. Mirrors MAX_READ_IDS in the Hub's
#: api/notifications.ts; the client prunes first, this is the backstop.
_MAX_BELL_READ_IDS = 500


#: Cap on a stored Klaus mark. One emoji, but a family or flag sequence is
#: several code points joined by zero-width joiners, so the limit is generous
#: enough to hold one of those and nothing like a sentence. Mirrors
#: KLAUS_MARK_MAX in the Hub's tokens.ts.
_MAX_MARK_LEN = 16


class AppearanceInput(BaseModel):
    """Customize-sheet appearance: hex colors, a native font, Klaus's mark."""

    accent: str = Field(..., pattern=r"^#[0-9A-Fa-f]{6}$")
    flame: str = Field(..., pattern=r"^#[0-9A-Fa-f]{6}$")
    font: Literal["default", "serif", "rounded", "mono"] = "default"
    # The glyph on Talk to Klaus and beside the coach note. "" means the pen
    # nib — the shipped default, and what every account had before the field
    # existed. Deliberately not constrained to an emoji block: a letter is a
    # legitimate mark, and no choice here can render anything unreadable.
    #
    # Omitted (None) and cleared ("") are different requests, and the store is
    # why. HubSettingsStore.set() writes with Firestore merge=True, which
    # merges nested maps key by key — so an appearance patch that simply left
    # `emoji` out would leave the old mark sitting in the document forever.
    # Clearing therefore has to travel as an explicit "", while None keeps its
    # ordinary meaning of "this patch says nothing about the mark" and is
    # dropped by exclude_none. That also means a stale client that predates the
    # field cannot wipe a mark just by changing a colour.
    emoji: str | None = Field(None, max_length=_MAX_MARK_LEN)

    @field_validator("emoji")
    @classmethod
    def _clean_emoji(cls, value: str | None) -> str | None:
        """Strip invisible characters from a mark, preserving clear-vs-omit.

        A pasted mark can carry bidi controls or a zero-width space: invisible,
        but they still occupy the field, so the button would look blank with no
        way to tell why. Anything that cleans away to nothing becomes "" — a
        clear — rather than None, which would silently mean "leave it alone".
        """
        if value is None:
            return None
        return "".join(
            ch for ch in value
            if ch == "\u200d"  # ZWJ: joins emoji sequences, must survive
            or not unicodedata.category(ch).startswith("C")
        ).strip()


class SettingsPatchInput(BaseModel):
    """PATCH /api/settings body — each section optional, replaced whole.

    ``home_sections`` keys are constrained to the known module names so a
    typo can never grow the settings doc unbounded.
    """

    appearance: AppearanceInput | None = None
    home_sections: dict[Literal["leaveby", "stats", "corner", "portfolio"], bool] | None = None
    # ISO timestamp of the newest bell item the user has seen. Account-level
    # so "mark all read" on the phone also clears the dot on the Mac.
    bell_last_seen: str | None = Field(None, max_length=64)
    # Keys of bell items already read (see the Hub's api/notifications.ts
    # `itemKey`). Per-item rather than a cursor because the bell marks rows
    # read as they scroll into view and the feed is newest-first: "everything
    # older than X" cannot express "the rows on screen, but not the ones
    # below". Over-long lists are truncated, not rejected — see the handler.
    bell_read_ids: list[Annotated[str, Field(max_length=128)]] | None = None


@router.patch("/api/settings")
async def api_patch_settings(
    body: SettingsPatchInput,
    _email: str = Depends(require_hub_session),
) -> JSONResponse:
    """Persist Customize-sheet choices account-wide (Paper Hub).

    Sections arrive whole (the sheet always sends its full state), so the
    store's shallow merge cannot half-update a nested object. Returns the
    merged settings in the same shape as GET.
    """
    from memory.firestore_db import _jsonsafe_doc  # lazy import

    patch = body.model_dump(exclude_none=True)
    if "bell_read_ids" in patch:
        # Keep the newest ids. The client already prunes to its 7-day feed;
        # this is the backstop that keeps a buggy or hostile client from
        # growing the settings doc without bound.
        patch["bell_read_ids"] = patch["bell_read_ids"][-_MAX_BELL_READ_IDS:]
    if not patch:
        raise HTTPException(status_code=400, detail={"error": "empty patch"})

    store = _get_hub_settings_store()
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, store.set, patch)
    settings = _jsonsafe_doc(await loop.run_in_executor(None, store.get))
    return JSONResponse(content={
        "push_enabled_at": settings.get("push_enabled_at"),
        "appearance": settings.get("appearance"),
        "home_sections": settings.get("home_sections"),
        "bell_last_seen": settings.get("bell_last_seen"),
        "bell_read_ids": settings.get("bell_read_ids") or [],
    })


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
