"""Reconcile planned training against what actually happened.

Carried v6 requirement WB-04. Every reasoning surface used to receive the raw
sources — the training log, Hevy workouts, Garmin activities — and was left to
work out for itself whether a planned session had happened. That guesswork is
what made Klaus ask about a workout the user had already done.

This module answers the question once, deterministically, so no reasoning
surface has to. A planned slot with evidence against it is closed; a slot the
user moved is not a gap on the date it left.

The reconciler proper (``reconcile_training_reality``) is a pure function over
already-fetched data, so its behaviour is fully testable without Firestore,
Garmin, or Hevy. ``build_training_reality`` is the thin gather wrapper that
reads the live stores and hands the results to it.
"""
from __future__ import annotations

import logging
import os
from datetime import date as date_cls, datetime, timedelta
from typing import Any

logger = logging.getLogger(__name__)

# The window the reconciler answers about: three days back through tomorrow.
# Far enough back to catch a session logged late, far enough forward to show
# what is still coming, short enough that it stays cheap to assemble.
DEFAULT_DAYS_BACK = 3
DEFAULT_DAYS_FORWARD = 1


def _as_date_key(value: Any) -> str:
    """Return the YYYY-MM-DD prefix of a date or timestamp field.

    Garmin reports activity dates as local timestamps ("2026-08-14 07:12:33"),
    while the training log and Hevy store plain calendar dates. Truncating to
    the first ten characters normalises all three onto the same key.
    """
    text = str(value or "").strip()
    return text[:10]


def _window_dates(today: str, days_back: int, days_forward: int) -> list[str]:
    """Return every calendar date in the window, oldest first."""
    anchor = date_cls.fromisoformat(today)
    span = range(-days_back, days_forward + 1)
    return [(anchor + timedelta(days=offset)).isoformat() for offset in span]


def _evidence_for_date(
    strength_sessions: list[dict],
    garmin_activities: list[dict],
    target_date: str,
) -> list[dict]:
    """Return every piece of completion evidence recorded on one date.

    Evidence is anything that proves training happened: a Hevy workout or a
    Garmin activity. Each item carries a stable ``ref`` so a caller can point
    at the exact record a conclusion came from.
    """
    evidence: list[dict] = []
    for session in strength_sessions:
        if _as_date_key(session.get("date")) == target_date:
            evidence.append({
                "ref": f"hevy:{session.get('workout_id')}",
                "label": session.get("title") or "Strength session",
            })
    for activity in garmin_activities:
        if _as_date_key(activity.get("date")) == target_date:
            evidence.append({
                "ref": f"garmin:{activity.get('activity_id')}",
                "label": activity.get("type") or "Activity",
            })
    return evidence


def _reconcile_one_day(
    target_date: str,
    logged_rows: list[dict],
    evidence: list[dict],
    today: str,
) -> list[dict]:
    """Reconcile one date's planned rows against that date's evidence.

    Rows are resolved in order, and each open planned row consumes one piece of
    evidence. Evidence left over after every row is satisfied is training that
    was never planned — which is worth seeing, not worth hiding.
    """
    unconsumed = list(evidence)
    sessions: list[dict] = []

    for row in logged_rows:
        plan_status = str(row.get("plan_status") or "")
        skipped_reason = row.get("skipped_reason")
        session = {
            "date": target_date,
            "slot": row.get("slot"),
            "type": row.get("type"),
            "skipped_reason": skipped_reason,
            "evidence": [f"training_log:{target_date}_{row.get('slot')}"],
        }

        # Terminal states first: the user already told us what became of these,
        # so no amount of missing evidence makes them a gap.
        if skipped_reason:
            session["status"] = "skipped"
        elif plan_status == "moved":
            session["status"] = "moved"
        elif plan_status == "deleted":
            session["status"] = "cancelled"
        elif row.get("completed"):
            # Already logged complete. Still consume a matching evidence item so
            # the Garmin activity that produced this row is not also reported as
            # an unplanned extra session.
            session["status"] = "completed"
            if unconsumed:
                session["evidence"].append(unconsumed.pop(0)["ref"])
        elif unconsumed:
            session["status"] = "completed"
            session["evidence"].append(unconsumed.pop(0)["ref"])
        elif target_date < today:
            session["status"] = "missed"
        else:
            session["status"] = "planned"

        sessions.append(session)

    for leftover in unconsumed:
        sessions.append({
            "date": target_date,
            "slot": None,
            "type": leftover["label"],
            "skipped_reason": None,
            "status": "unplanned",
            "evidence": [leftover["ref"]],
        })

    return sessions


def reconcile_training_reality(
    *,
    today: str,
    training_log: list[dict],
    strength_sessions: list[dict],
    garmin_activities: list[dict],
    days_back: int = DEFAULT_DAYS_BACK,
    days_forward: int = DEFAULT_DAYS_FORWARD,
) -> dict:
    """Return the reconciled planned-vs-actual picture for the window.

    Args:
        today: Today's date as YYYY-MM-DD, in the user's timezone.
        training_log: TrainingLogStore rows (planned and completed alike).
        strength_sessions: StrengthSessionStore rows synced from Hevy.
        garmin_activities: Normalised Garmin activity dicts.
        days_back: Days before today to include.
        days_forward: Days after today to include.

    Returns:
        A dict with ``window`` (start/end dates) and ``days`` — one entry per
        calendar date, oldest first, each holding its reconciled ``sessions``.
        Every session carries a ``status`` of completed, planned, missed,
        moved, cancelled, skipped, or unplanned, plus the ``evidence`` refs
        behind it.
    """
    dates = _window_dates(today, days_back, days_forward)
    in_window = set(dates)

    rows_by_date: dict[str, list[dict]] = {}
    for row in training_log:
        key = _as_date_key(row.get("date"))
        if key in in_window:
            rows_by_date.setdefault(key, []).append(row)

    days = [
        {
            "date": target_date,
            "sessions": _reconcile_one_day(
                target_date,
                rows_by_date.get(target_date, []),
                _evidence_for_date(strength_sessions, garmin_activities, target_date),
                today,
            ),
        }
        for target_date in dates
    ]

    return {"window": {"start": dates[0], "end": dates[-1]}, "days": days}


def build_training_reality(
    days_back: int = DEFAULT_DAYS_BACK,
    days_forward: int = DEFAULT_DAYS_FORWARD,
) -> dict:
    """Gather the live sources and return the reconciled window.

    Every read is best-effort and fail-open, matching ``get_training_context``:
    one outage degrades the picture rather than denying the whole answer. A
    source that could not be read is named in ``degraded`` so a caller can tell
    "nothing happened" apart from "we could not see what happened".
    """
    from zoneinfo import ZoneInfo

    project_id = os.environ.get("GCP_PROJECT_ID", "")
    database = os.environ.get("FIRESTORE_DATABASE", "(default)")
    today = datetime.now(ZoneInfo("Asia/Jerusalem")).date()
    lookback = days_back + 1

    degraded: list[str] = []

    try:
        from memory.firestore_db import TrainingLogStore
        training_log = TrainingLogStore(project_id, database).get_recent(lookback)
    except Exception:
        logger.warning("training reality: training_log read failed", exc_info=True)
        training_log = []
        degraded.append("training_log")

    try:
        from memory.firestore_db import StrengthSessionStore
        strength_sessions = StrengthSessionStore(project_id, database).get_recent(lookback)
    except Exception:
        logger.warning("training reality: strength read failed", exc_info=True)
        strength_sessions = []
        degraded.append("strength_sessions")

    try:
        from mcp_tools.garmin_tool import fetch_garmin_activities
        garmin_activities = fetch_garmin_activities(lookback)
    except Exception:
        logger.warning("training reality: garmin read failed", exc_info=True)
        garmin_activities = []
        degraded.append("garmin_activities")

    reality = reconcile_training_reality(
        today=today.isoformat(),
        training_log=training_log or [],
        strength_sessions=strength_sessions or [],
        garmin_activities=garmin_activities or [],
        days_back=days_back,
        days_forward=days_forward,
    )
    reality["degraded"] = degraded
    return reality
