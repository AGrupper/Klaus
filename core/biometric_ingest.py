# core/biometric_ingest.py
"""Daily Garmin biometrics ingestion pipeline (HRV / resting HR history).

The Postgres ``daily_biometrics`` table powers rolling recovery baselines
(get_training_context, weekly review, core/recovery_metrics.py) — but until
this cron its only writer was the morning briefing, one today-row at a time,
and only when the briefing fired. Cloud Scheduler now fires POST
/cron/biometric-sync daily; each tick diffs the look-back window against the
rows already in Postgres and pulls the missing days, bounded by a count cap
and a wall-clock budget so the first-run backfill drains over multiple ticks.

Two modes, chosen by the ``backfill_done`` flag in Firestore
(biometric_ingest/state):
  - **backfill** (flag unset): diff a wide window (BIOMETRIC_INGEST_BACKFILL_DAYS).
  - **delta** (flag set): diff a short window (BIOMETRIC_INGEST_DELTA_DAYS).

Today and yesterday are ALWAYS re-fetched regardless of presence — a row
written at 05:30 predates wake-up, and sleep/HRV land late; the next tick's
yesterday-refetch heals it.

Days Garmin returns entirely empty (pre-watch / watch not worn) are recorded
in a ``skipped_dates`` state ledger so the backfill can drain — without it,
empty days would be retried forever and ``backfill_done`` would never flip.
Failed Postgres writes need no ledger: the row stays absent, so the
presence-diff retries the day on the next tick (self-healing).

Local dry-run:
    GARMIN_EMAIL=... GARMIN_PASSWORD=... DATABASE_URL=... GCP_PROJECT_ID=... \
        python -m core.biometric_ingest
"""
from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from mcp_tools.garmin_tool import (
    GarminAuthError,
    GarminUnavailableError,
    fetch_garmin_daily,
    write_biometrics_to_postgres,
)

logger = logging.getLogger(__name__)

# ------------------------------------------------------------------ #
# Constants                                                          #
# ------------------------------------------------------------------ #

BATCH_MAX_DAYS = 10          # daily fetches per tick (env: BIOMETRIC_INGEST_MAX_DAYS)
TIME_BUDGET_SEC = 50         # wall-clock budget (env: BIOMETRIC_INGEST_TIME_BUDGET_SEC)
BACKFILL_DAYS = 90           # first-run look-back (env: BIOMETRIC_INGEST_BACKFILL_DAYS)
DELTA_DAYS = 7               # steady-state look-back (env: BIOMETRIC_INGEST_DELTA_DAYS)
REQUEST_DELAY_SEC = 0.7      # sleep between day fetches (env: BIOMETRIC_INGEST_REQUEST_DELAY_SEC)
_COLLECTION = "biometric_ingest"
_STATE_DOC = "state"

# A day is "empty" (→ skipped_dates ledger) when every metric is None.
_METRIC_FIELDS = (
    "sleep_score", "sleep_hours", "hrv_status", "hrv_overnight",
    "hrv_baseline", "body_battery_morning", "resting_hr", "training_readiness",
)


# ------------------------------------------------------------------ #
# Firestore state helpers (mirror core/run_ingest)                   #
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
        logger.warning("biometric_ingest: failed to read state", exc_info=True)
        return {}


def _set_state(fields: dict) -> None:
    try:
        from memory.firestore_db import _make_firestore_client
        client = _make_firestore_client(
            os.environ["GCP_PROJECT_ID"], os.getenv("FIRESTORE_DATABASE", "(default)")
        )
        client.collection(_COLLECTION).document(_STATE_DOC).set(fields, merge=True)
    except Exception:
        logger.warning("biometric_ingest: failed to write state", exc_info=True)


# ------------------------------------------------------------------ #
# Postgres presence diff                                             #
# ------------------------------------------------------------------ #

def _present_dates(cutoff_iso: str) -> set[str] | None:
    """ISO dates already in daily_biometrics since cutoff; None on any failure.

    None (vs empty set) tells the caller the diff is unknowable this tick —
    it then fetches only today+yesterday and must NOT flip backfill_done.
    """
    try:
        import psycopg2  # lazy import — keeps cold-start cheap when unused
        dsn = os.environ.get("DATABASE_URL") or os.environ.get("PG_CONNECTION_STRING")
        if not dsn:
            logger.info("biometric_ingest: DATABASE_URL unset — presence diff skipped")
            return None
        with psycopg2.connect(dsn) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT date::date FROM daily_biometrics WHERE date >= %s",
                    (cutoff_iso,),
                )
                return {r[0].isoformat() for r in cur.fetchall()}
    except Exception:
        logger.warning("biometric_ingest: presence query failed", exc_info=True)
        return None


# ------------------------------------------------------------------ #
# Batch driver                                                       #
# ------------------------------------------------------------------ #

def run_one_batch() -> dict:
    """Process a bounded batch of Garmin daily-biometrics pulls.

    Returns a status dict; ``done: false`` means more backlog remains for the
    next tick (re-run until ``done: true``).

    Returns:
        ``{"ok", "mode": "backfill"|"delta", "processed", "remaining", "done"}``.
        On auth/network failure: ``{"ok": False, "error": str}`` (never raises).
    """
    max_days = int(os.getenv("BIOMETRIC_INGEST_MAX_DAYS", str(BATCH_MAX_DAYS)))
    budget = int(os.getenv("BIOMETRIC_INGEST_TIME_BUDGET_SEC", str(TIME_BUDGET_SEC)))
    delay = float(os.getenv("BIOMETRIC_INGEST_REQUEST_DELAY_SEC", str(REQUEST_DELAY_SEC)))
    backfill_days = int(os.getenv("BIOMETRIC_INGEST_BACKFILL_DAYS", str(BACKFILL_DAYS)))
    delta_days = int(os.getenv("BIOMETRIC_INGEST_DELTA_DAYS", str(DELTA_DAYS)))

    state = _get_state()
    backfill_done = bool(state.get("backfill_done"))
    mode = "delta" if backfill_done else "backfill"
    window = delta_days if backfill_done else backfill_days

    today = datetime.now(ZoneInfo("Asia/Jerusalem")).date()
    yesterday = today - timedelta(days=1)
    window_dates = [(today - timedelta(days=i)).isoformat() for i in range(window + 1)]

    present = _present_dates(window_dates[-1])
    skipped_ledger = set(state.get("skipped_dates") or [])

    always = [today.isoformat(), yesterday.isoformat()]
    if present is None:
        # Diff unknowable — keep the daily heal, don't touch the backlog.
        targets = always
    else:
        missing = [
            d for d in window_dates
            if d not in present and d not in skipped_ledger and d not in always
        ]
        targets = always + missing  # newest-first (window_dates is newest-first)

    start = time.monotonic()
    now_iso = datetime.now(timezone.utc).isoformat()
    processed = 0
    newly_skipped: list[str] = []

    for d in targets:
        if processed >= max_days or (time.monotonic() - start) >= budget:
            break
        try:
            daily = fetch_garmin_daily(d)
        except (GarminAuthError, GarminUnavailableError) as exc:
            # Client-level failure (e.g. token expired mid-batch) — stop cleanly.
            logger.warning("biometric_ingest: client failure on %s: %s", d, exc)
            if processed == 0:
                return {"ok": False, "error": str(exc)}
            break
        except Exception:
            logger.warning("biometric_ingest: fetch failed for %s", d, exc_info=True)
            processed += 1
            continue

        if all(daily.get(k) is None for k in _METRIC_FIELDS):
            # Pre-watch / watch-off day — remember it so the backfill drains.
            # Never ledger today/yesterday: their data may simply not exist YET.
            if d not in always:
                newly_skipped.append(d)
        else:
            write_biometrics_to_postgres(daily)
        processed += 1
        if delay > 0:
            time.sleep(delay)

    remaining = len(targets) - processed
    drained = remaining <= 0

    fields: dict = {"last_run_at": now_iso}
    if newly_skipped:
        fields["skipped_dates"] = sorted(skipped_ledger | set(newly_skipped))
    if not backfill_done and drained and present is not None:
        # Backfill window fully ingested — switch to the short delta window.
        fields["backfill_done"] = True
    _set_state(fields)

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
