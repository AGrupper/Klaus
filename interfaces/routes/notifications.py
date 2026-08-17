"""Hub bell feed and follow-up visibility — the notification center reads.

GET /api/notifications shapes the same three sources /api/activity exposes
raw (reviews, action log, outreach log) into one typed, deep-linkable feed
for the bell sheet. It is a read-only projection: nothing here marks items
read (the client keeps a last-seen cursor) and nothing writes.

GET /api/followups exposes FollowupStore's pending check-backs so "Klaus's
corner" can show what he is planning to come back about.
"""
from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse

from interfaces.hub_auth import require_hub_session

logger = logging.getLogger(__name__)

router = APIRouter()

_TZ = ZoneInfo("Asia/Jerusalem")

_REVIEW_TITLES = {
    "morning": "Morning review",
    "nightly": "Nightly review",
    "weekly": "Weekly review",
}

# Outreach `kind` values that are infrastructure noise rather than things
# Amit must act on — the bell renders these dimmed, at the bottom of a day.
_SYSTEM_KINDS = {"automation_failure"}

_SNIPPET_CHARS = 240


def _snippet(text: str) -> str:
    """First ~240 chars of a review, cut at a word boundary, single line."""
    flat = " ".join(str(text or "").split())
    if len(flat) <= _SNIPPET_CHARS:
        return flat
    cut = flat[:_SNIPPET_CHARS]
    return cut[: cut.rfind(" ")].rstrip(",.;:") + "…" if " " in cut else cut + "…"


@router.get("/api/notifications")
async def api_notifications(
    days: int = Query(default=7, ge=1, le=30),
    _email: str = Depends(require_hub_session),
) -> JSONResponse:
    """Return the typed bell feed, newest first.

    Item shape::

        {"id": str, "type": "review"|"alert"|"action"|"system",
         "title": str, "body": str|None, "at": ISO str,
         "claude_session_url": str|None,      # reviews only — deep link
         "routine": str|None, "target_date": str|None,
         "push_tag": str|None}                # matches the delivered push's
                                              # tag, for lock-screen dismissal

    Every item is tappable somewhere: reviews continue in Claude via
    ``claude_session_url`` (client falls back to the Project URL when a
    fallback review has none), alerts/actions open the relevant Hub spot.
    """
    from core.hub.actions import humanize_action
    from core.hub.reviews import _review_for_client
    from memory.firestore_db import (  # lazy import
        ActionLogStore,
        OutreachLogStore,
        RoutineReviewStore,
        RoutineRunStore,
        _jsonsafe_doc,
    )

    project = os.environ.get("GCP_PROJECT_ID", "klaus-agent")
    database = os.environ.get("FIRESTORE_DATABASE", "klaus-firestore")
    loop = asyncio.get_running_loop()
    reviews_store = RoutineReviewStore(project, database)
    runs_store = RoutineRunStore(project, database)
    actions_store = ActionLogStore(project, database)
    outreach_store = OutreachLogStore(project, database)
    today = datetime.now(_TZ).date()

    def load_reviews() -> list[dict]:
        return [
            _review_for_client(review, runs_store)
            for review in reviews_store.list_recent(min(days, 31))
        ]

    def load_outreach() -> list[tuple[str, dict]]:
        records = []
        for offset in range(days):
            day = (today - timedelta(days=offset)).isoformat()
            records.extend((day, entry) for entry in outreach_store.get_today(day))
        return records

    reviews, actions, outreach = await asyncio.gather(
        loop.run_in_executor(None, load_reviews),
        loop.run_in_executor(None, actions_store.get_recent, days),
        loop.run_in_executor(None, load_outreach),
    )

    items: list[dict] = []

    for review in reviews:
        routine = str(review.get("routine") or "")
        target_date = str(review.get("target_date") or "")
        items.append({
            "id": review.get("review_id") or f"review:{routine}:{target_date}",
            "type": "review",
            "title": _REVIEW_TITLES.get(routine, "Review"),
            "body": _snippet(review.get("review_text", "")),
            "at": str(review.get("published_at") or target_date),
            "claude_session_url": review.get("claude_session_url"),
            "routine": routine,
            "target_date": target_date,
            # Must match the tag core/routines + MCP publish put on the push,
            # so reading here dismisses the lock-screen notification.
            "push_tag": f"review:{routine}:{target_date}",
        })

    for entry in actions:
        # humanize_action returns None for entries the bell suppresses
        # (publish_review duplicates the review item itself).
        title = humanize_action(entry)
        if title is None:
            continue
        items.append({
            "id": str(entry.get("id") or ""),
            "type": "action",
            "title": title,
            "body": None,
            "at": str(entry.get("at") or ""),
            "claude_session_url": None,
            "routine": None,
            "target_date": None,
            "push_tag": None,   # actions never push
        })

    for day, entry in outreach:
        kind = str(entry.get("kind") or "")
        # Entries store only "HH:MM"; anchor them to their day for sorting.
        at = f"{day}T{entry.get('time') or '00:00'}:00"
        items.append({
            "id": str(entry.get("topic_key") or f"{day}:{entry.get('time')}"),
            "type": "system" if kind in _SYSTEM_KINDS else "alert",
            "title": _snippet(entry.get("final", "")) or "Alert",
            "body": None,
            "at": at,
            "claude_session_url": None,
            "routine": None,
            "target_date": None,
            # Alerts push with their topic_key as the tag (deterministic
            # alerts dedup on it), so reading clears the lock screen too.
            "push_tag": str(entry.get("topic_key") or "") or None,
        })

    items.sort(key=lambda item: str(item.get("at") or ""), reverse=True)
    return JSONResponse(content=_jsonsafe_doc({"notifications": items}))


@router.get("/api/followups")
async def api_followups(
    _email: str = Depends(require_hub_session),
) -> JSONResponse:
    """Return pending follow-ups sorted soonest-first for Klaus's corner."""
    from memory.firestore_db import FollowupStore, _jsonsafe_doc  # lazy import

    store = FollowupStore(
        os.environ.get("GCP_PROJECT_ID", "klaus-agent"),
        os.environ.get("FIRESTORE_DATABASE", "klaus-firestore"),
    )
    followups = await asyncio.get_running_loop().run_in_executor(
        None, store.list_pending
    )
    followups.sort(key=lambda f: str(f.get("due_at") or ""))
    return JSONResponse(content=_jsonsafe_doc({"followups": followups}))
