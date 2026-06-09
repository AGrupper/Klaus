# core/run_ingest.py
"""Garmin per-run detail ingestion pipeline.

Pull-based sync (Garmin has no webhooks / no change-events API). Cloud Scheduler
fires POST /cron/run-sync daily; each tick lists recent running activities (one
cheap summary call), then fetches the expensive per-run DETAIL only for runs not
yet in RunDetailStore, bounded by a count cap and a wall-clock budget so a large
first-run backfill drains over multiple ticks.

Two modes, chosen by the ``backfill_done`` flag in Firestore (run_ingest/state):
  - **backfill** (flag unset): list a wide window (RUN_INGEST_BACKFILL_DAYS) and
    pull detail for every still-missing run; when a tick drains all unsynced runs
    in the window, the flag flips to True and the store switches to delta.
  - **delta** (flag set): list a short window (RUN_INGEST_DELTA_DAYS) and pull
    detail for any new runs. Runs are immutable post-upload, so a simple
    presence check (store.get_run(id) is None) is the whole delta — no cursor.

Why presence-check instead of a since-cursor (the Hevy pattern): Garmin exposes
no events endpoint, so we list summaries (cheap) and diff against what we've
already stored. Upserts are idempotent (doc id = activity_id), so re-runs are safe.

Local dry-run:
    GARMIN_EMAIL=... GARMIN_PASSWORD=... GCP_PROJECT_ID=... python -m core.run_ingest
"""
from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime, timezone

from mcp_tools.garmin_tool import (
    RUNNING_ACTIVITY_TYPES,
    GarminAuthError,
    GarminUnavailableError,
    fetch_garmin_activities,
    fetch_run_detail_raw,
    normalize_run_detail,
)

logger = logging.getLogger(__name__)

# ------------------------------------------------------------------ #
# Constants                                                          #
# ------------------------------------------------------------------ #

BATCH_MAX_ACTIVITIES = 8     # detail pulls per tick (env: RUN_INGEST_MAX_ACTIVITIES)
TIME_BUDGET_SEC = 50         # wall-clock budget (env: RUN_INGEST_TIME_BUDGET_SEC)
BACKFILL_DAYS = 120          # first-run look-back (env: RUN_INGEST_BACKFILL_DAYS)
DELTA_DAYS = 14              # steady-state look-back (env: RUN_INGEST_DELTA_DAYS)
REQUEST_DELAY_SEC = 0.7      # sleep between detail pulls (env: RUN_INGEST_REQUEST_DELAY_SEC)
_COLLECTION = "run_ingest"
_STATE_DOC = "state"


# ------------------------------------------------------------------ #
# Firestore state helpers (mirror core/strength_ingest)              #
# ------------------------------------------------------------------ #

def _get_state() -> dict:
    try:
        from memory.firestore_db import _make_firestore_client
        client = _make_firestore_client(
            os.environ["GCP_PROJECT_ID"], os.getenv("FIRESTORE_DATABASE", "(default)")
        )
        snap = client.collection(_COLLECTION).document(_STATE_DOC).get()
        return (snap.to_dict() or {}) if snap.exists else {}
    except Exception:
        logger.warning("run_ingest: failed to read state", exc_info=True)
        return {}


def _set_state(fields: dict) -> None:
    try:
        from memory.firestore_db import _make_firestore_client
        client = _make_firestore_client(
            os.environ["GCP_PROJECT_ID"], os.getenv("FIRESTORE_DATABASE", "(default)")
        )
        client.collection(_COLLECTION).document(_STATE_DOC).set(fields, merge=True)
    except Exception:
        logger.warning("run_ingest: failed to write state", exc_info=True)


def _store():
    from memory.firestore_db import RunDetailStore
    return RunDetailStore(
        project_id=os.environ["GCP_PROJECT_ID"],
        database=os.getenv("FIRESTORE_DATABASE", "(default)"),
    )


# ------------------------------------------------------------------ #
# Batch driver                                                       #
# ------------------------------------------------------------------ #

def run_one_batch() -> dict:
    """Process a bounded batch of Garmin run-detail pulls.

    Returns a status dict; ``done: false`` means more backlog remains for the
    next tick (re-run until ``done: true``).

    Returns:
        ``{"ok", "mode": "backfill"|"delta", "processed", "remaining", "done"}``.
        On auth/network failure: ``{"ok": False, "error": str}`` (never raises).
    """
    max_acts = int(os.getenv("RUN_INGEST_MAX_ACTIVITIES", str(BATCH_MAX_ACTIVITIES)))
    budget = int(os.getenv("RUN_INGEST_TIME_BUDGET_SEC", str(TIME_BUDGET_SEC)))
    delay = float(os.getenv("RUN_INGEST_REQUEST_DELAY_SEC", str(REQUEST_DELAY_SEC)))
    backfill_days = int(os.getenv("RUN_INGEST_BACKFILL_DAYS", str(BACKFILL_DAYS)))
    delta_days = int(os.getenv("RUN_INGEST_DELTA_DAYS", str(DELTA_DAYS)))

    state = _get_state()
    backfill_done = bool(state.get("backfill_done"))
    mode = "delta" if backfill_done else "backfill"
    window = delta_days if backfill_done else backfill_days

    store = _store()
    start = time.monotonic()
    now_iso = datetime.now(timezone.utc).isoformat()

    try:
        activities = fetch_garmin_activities(window)
    except (GarminAuthError, GarminUnavailableError) as exc:
        logger.warning("run_ingest: activities fetch failed: %s", exc)
        return {"ok": False, "error": str(exc)}

    # Candidate runs, newest-first, not yet stored.
    candidates = [
        a for a in activities
        if (a.get("type") in RUNNING_ACTIVITY_TYPES) and a.get("activity_id") is not None
    ]
    unsynced = [a for a in candidates if store.get_run(str(a["activity_id"])) is None]

    processed = 0
    for activity in unsynced:
        if processed >= max_acts or (time.monotonic() - start) >= budget:
            break
        aid = activity["activity_id"]
        try:
            raw = fetch_run_detail_raw(aid)
            store.upsert(normalize_run_detail(
                activity, raw["details"], raw["splits"], raw["hr_zones"],
            ))
            processed += 1
        except (GarminAuthError, GarminUnavailableError) as exc:
            # Client-level failure (e.g. token expired mid-batch) — stop cleanly.
            logger.warning("run_ingest: client failure on %s: %s", aid, exc)
            break
        except Exception:
            logger.warning("run_ingest: detail pull/upsert failed for %s", aid, exc_info=True)
            continue
        if delay > 0:
            time.sleep(delay)

    remaining = len(unsynced) - processed
    drained = remaining <= 0

    if not backfill_done and drained:
        # Backfill window fully ingested — switch to the short delta window.
        _set_state({"backfill_done": True, "last_run_at": now_iso})
    else:
        _set_state({"last_run_at": now_iso})

    # In delta mode "done" reflects whether this tick drained the (short) window.
    done = drained if not backfill_done else True
    return {
        "ok": True,
        "mode": mode,
        "processed": processed,
        "remaining": max(0, remaining),
        "done": done,
    }


if __name__ == "__main__":  # pragma: no cover — local dry-run helper
    logging.basicConfig(level=logging.INFO)
    print(json.dumps(run_one_batch(), indent=2))
