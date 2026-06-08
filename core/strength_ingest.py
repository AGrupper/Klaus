# core/strength_ingest.py
"""Hevy strength-session ingestion pipeline.

Pull-based sync (Hevy has no webhooks). Cloud Scheduler fires
POST /cron/strength-sync daily; each tick processes a bounded number of pages
within a time budget and persists a cursor in Firestore (strength_ingest/state)
so a large first-run backfill drains over multiple ticks.

Two modes, chosen by the presence of the ``last_synced_at`` cursor:
  - **backfill** (no cursor): paginate GET /v1/workouts newest-first, upserting
    every workout, advancing a ``backfill_page`` cursor; on completion the
    cursor flips to ``last_synced_at = now`` and the store switches to delta.
  - **delta** (cursor set): GET /v1/workouts/events?since=<cursor>, applying
    ``updated`` upserts and ``deleted`` deletes. The cursor only advances when a
    tick drains all event pages, so nothing is skipped (re-runs are idempotent —
    upserts are keyed on workout_id).

Local dry-run:
    HEVY_API_KEY=... GCP_PROJECT_ID=... python -m core.strength_ingest
"""
from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime, timezone

from mcp_tools.hevy_tool import (
    HevyAuthError,
    HevyUnavailableError,
    fetch_workout_events,
    fetch_workouts,
    normalize_workout,
)

logger = logging.getLogger(__name__)

# ------------------------------------------------------------------ #
# Constants                                                          #
# ------------------------------------------------------------------ #

BATCH_MAX_PAGES = 5          # pages per tick (env: STRENGTH_INGEST_MAX_PAGES)
TIME_BUDGET_SEC = 45         # wall-clock budget (env: STRENGTH_INGEST_TIME_BUDGET_SEC)
_COLLECTION = "strength_ingest"
_STATE_DOC = "state"


# ------------------------------------------------------------------ #
# Firestore helpers (mirror core/chat_ingest)                        #
# ------------------------------------------------------------------ #

def _make_firestore_client():
    from memory.firestore_db import _make_firestore_client as _mfc
    return _mfc(os.environ["GCP_PROJECT_ID"], os.getenv("FIRESTORE_DATABASE", "(default)"))


def _get_state() -> dict:
    try:
        client = _make_firestore_client()
        snap = client.collection(_COLLECTION).document(_STATE_DOC).get()
        return (snap.to_dict() or {}) if snap.exists else {}
    except Exception:
        logger.warning("strength_ingest: failed to read state", exc_info=True)
        return {}


def _set_state(fields: dict) -> None:
    try:
        client = _make_firestore_client()
        client.collection(_COLLECTION).document(_STATE_DOC).set(fields, merge=True)
    except Exception:
        logger.warning("strength_ingest: failed to write state", exc_info=True)


def _store():
    from memory.firestore_db import StrengthSessionStore
    return StrengthSessionStore(
        project_id=os.environ["GCP_PROJECT_ID"],
        database=os.getenv("FIRESTORE_DATABASE", "(default)"),
    )


# ------------------------------------------------------------------ #
# Batch driver                                                       #
# ------------------------------------------------------------------ #

def run_one_batch() -> dict:
    """Process a bounded batch of Hevy workouts/events.

    Returns a status dict; ``done: false`` means there is more backlog to drain
    on the next tick (re-run until ``done: true``).

    Returns:
        backfill: ``{"ok", "mode": "backfill", "processed", "done"}``
        delta:    ``{"ok", "mode": "delta", "processed", "deleted", "done"}``
        On auth/network failure: ``{"ok": False, "error": str}`` (never raises).
    """
    max_pages = int(os.getenv("STRENGTH_INGEST_MAX_PAGES", str(BATCH_MAX_PAGES)))
    budget = int(os.getenv("STRENGTH_INGEST_TIME_BUDGET_SEC", str(TIME_BUDGET_SEC)))

    state = _get_state()
    last_synced_at = state.get("last_synced_at")
    store = _store()
    start = time.monotonic()
    now_iso = datetime.now(timezone.utc).isoformat()

    try:
        if not last_synced_at:
            return _run_backfill(store, state, max_pages, budget, start, now_iso)
        return _run_delta(store, last_synced_at, max_pages, budget, start, now_iso)
    except (HevyAuthError, HevyUnavailableError) as exc:
        logger.warning("strength_ingest: Hevy fetch failed: %s", exc)
        return {"ok": False, "error": str(exc)}


def _run_backfill(store, state, max_pages, budget, start, now_iso) -> dict:
    """First-run full history pull, paginated newest-first across ticks."""
    page = int(state.get("backfill_page", 1))
    processed = 0
    pages_done = 0
    drained = False

    while pages_done < max_pages and (time.monotonic() - start) < budget:
        env = fetch_workouts(page=page)
        page_count = int(env.get("page_count") or 1)
        for raw in env.get("workouts") or []:
            try:
                store.upsert(normalize_workout(raw))
                processed += 1
            except Exception:
                logger.warning("strength_ingest: backfill upsert failed", exc_info=True)
                continue
        pages_done += 1
        if page >= page_count:
            drained = True
            break
        page += 1
        _set_state({"backfill_page": page})

    if drained:
        # Backfill complete — flip to delta mode from this sync time onward.
        _set_state({"last_synced_at": now_iso, "backfill_page": 1})
    return {"ok": True, "mode": "backfill", "processed": processed, "done": drained}


def _run_delta(store, since, max_pages, budget, start, now_iso) -> dict:
    """Incremental sync: apply updated/deleted events since the cursor."""
    page = 1
    processed = 0
    deleted = 0
    pages_done = 0
    drained = False

    while pages_done < max_pages and (time.monotonic() - start) < budget:
        env = fetch_workout_events(since=since, page=page)
        page_count = int(env.get("page_count") or 1)
        for ev in env.get("events") or []:
            try:
                if ev.get("type") == "deleted":
                    wid = ev.get("id") or (ev.get("workout") or {}).get("id")
                    if wid:
                        store.delete(wid)
                        deleted += 1
                else:  # "updated" (or any non-delete event carrying a workout)
                    raw = ev.get("workout") or {}
                    if raw.get("id"):
                        store.upsert(normalize_workout(raw))
                        processed += 1
            except Exception:
                logger.warning("strength_ingest: delta event apply failed", exc_info=True)
                continue
        pages_done += 1
        if page >= page_count:
            drained = True
            break
        page += 1

    # Only advance the cursor when fully drained — events are newest-first, so a
    # premature advance would skip unseen older events. A non-drained tick re-runs
    # with the same cursor next time (idempotent upserts make the overlap safe).
    if drained:
        _set_state({"last_synced_at": now_iso})
    return {
        "ok": True,
        "mode": "delta",
        "processed": processed,
        "deleted": deleted,
        "done": drained,
    }


if __name__ == "__main__":  # pragma: no cover — local dry-run helper
    logging.basicConfig(level=logging.INFO)
    print(json.dumps(run_one_batch(), indent=2))
