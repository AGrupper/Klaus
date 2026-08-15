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

# The window the reconciler answers about: a week back through tomorrow.
# Three days was the original span, but on real data it surfaced a single
# session — too thin to answer "what training have I done lately". Training
# runs on a weekly cycle and the weekly review needs the full week, so a week
# is the useful default. Callers narrow or widen it per question.
DEFAULT_DAYS_BACK = 7
DEFAULT_DAYS_FORWARD = 1

# Garmin saves a warmup, the main effort and a cooldown as separate activities,
# so one track morning arrives as three or four records. Reported separately
# Klaus would say Amit trained four times that day. Activities less than this
# far apart are one session (Amit's choice, 2026-08-15).
SESSION_GAP_MINUTES = 75
LOCAL_TZ = "Asia/Jerusalem"


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


def _local_start(value: Any) -> datetime | None:
    """Parse a start timestamp into naive local (Asia/Jerusalem) time.

    The two sources disagree about timezones: Hevy stores UTC-aware ISO
    timestamps, Garmin stores naive local ones. Comparing them raw is a
    three-hour error in summer, which would merge unrelated sessions or split
    contiguous ones. Everything is normalised to naive local before any gap is
    measured.
    """
    from zoneinfo import ZoneInfo

    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(ZoneInfo(LOCAL_TZ)).replace(tzinfo=None)
    return parsed


def _evidence_for_date(
    strength_sessions: list[dict],
    garmin_activities: list[dict],
    target_date: str,
) -> list[dict]:
    """Return every piece of completion evidence recorded on one date.

    Evidence is anything that proves training happened: a Hevy workout or a
    Garmin activity. Each item carries stable ``refs`` so a caller can point at
    the exact records a conclusion came from, plus the timing needed to decide
    whether neighbouring records are really one session.
    """
    evidence: list[dict] = []
    for session in strength_sessions:
        if _as_date_key(session.get("date")) == target_date:
            duration_min = session.get("duration_min") or 0
            evidence.append({
                "refs": [f"hevy:{session.get('workout_id')}"],
                "label": session.get("title") or "Strength session",
                "start": _local_start(session.get("start_time")),
                "duration_sec": int(float(duration_min) * 60),
            })
    for activity in garmin_activities:
        if _as_date_key(activity.get("date")) == target_date:
            evidence.append({
                "refs": [f"garmin:{activity.get('activity_id')}"],
                "label": activity.get("type") or "Activity",
                "start": _local_start(activity.get("date")),
                "duration_sec": int(activity.get("duration_sec") or 0),
            })
    return _group_contiguous(evidence)


def _group_contiguous(evidence: list[dict]) -> list[dict]:
    """Merge evidence records less than ``SESSION_GAP_MINUTES`` apart.

    The gap measured is from the end of one record to the start of the next, so
    a long run followed straight by a cooldown groups correctly rather than
    being split because its start times are far apart.

    Records with no usable start time cannot be placed on the timeline, so they
    are left as their own sessions rather than guessed into a neighbour.
    """
    timed = sorted(
        (item for item in evidence if item["start"] is not None),
        key=lambda item: item["start"],
    )
    untimed = [item for item in evidence if item["start"] is None]

    grouped: list[dict] = []
    for item in timed:
        if grouped:
            previous = grouped[-1]
            previous_end = previous["start"] + timedelta(
                seconds=previous["duration_sec"]
            )
            gap = (item["start"] - previous_end).total_seconds() / 60
            if gap < SESSION_GAP_MINUTES:
                # Merge: keep the earliest start, extend the span to this
                # record's end, and keep the longest part's label as the name
                # of the session — a 20-minute track effort describes the
                # morning better than the 5-minute cooldown that ended it.
                previous_end_new = item["start"] + timedelta(
                    seconds=item["duration_sec"]
                )
                previous["refs"].extend(item["refs"])
                previous["duration_sec"] = int(
                    (previous_end_new - previous["start"]).total_seconds()
                )
                if item["duration_sec"] > previous.get("longest_part", 0):
                    previous["label"] = item["label"]
                    previous["longest_part"] = item["duration_sec"]
                continue
        item.setdefault("longest_part", item["duration_sec"])
        grouped.append(item)

    return grouped + untimed


def _reconcile_one_day(
    target_date: str,
    logged_rows: list[dict],
    evidence: list[dict],
    today: str,
    evidence_sources_degraded: bool,
) -> list[dict]:
    """Reconcile one date's planned rows against that date's evidence.

    Rows are resolved in order, and each open planned row consumes one piece of
    evidence. Evidence left over after every row is satisfied is training that
    was never planned — which is worth seeing, not worth hiding.

    When an evidence source could not be read, a past planned session with no
    evidence resolves to ``unverified`` rather than ``missed``. Garmin returning
    502 is routine, and reporting a session as missed on the strength of a
    failed read would tell Amit he skipped training he actually did.
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
                session["evidence"].extend(unconsumed.pop(0)["refs"])
        elif unconsumed:
            session["status"] = "completed"
            session["evidence"].extend(unconsumed.pop(0)["refs"])
        elif target_date >= today:
            session["status"] = "planned"
        elif evidence_sources_degraded:
            session["status"] = "unverified"
        else:
            session["status"] = "missed"

        sessions.append(session)

    for leftover in unconsumed:
        sessions.append({
            "date": target_date,
            "slot": None,
            "type": leftover["label"],
            "skipped_reason": None,
            "status": "unplanned",
            "evidence": list(leftover["refs"]),
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
    evidence_sources_degraded: bool = False,
) -> dict:
    """Return the reconciled planned-vs-actual picture for the window.

    Args:
        today: Today's date as YYYY-MM-DD, in the user's timezone.
        training_log: TrainingLogStore rows (planned and completed alike).
        strength_sessions: StrengthSessionStore rows synced from Hevy.
        garmin_activities: Normalised Garmin activity dicts.
        days_back: Days before today to include.
        days_forward: Days after today to include.
        evidence_sources_degraded: True when any source could not be read, which
            downgrades what would have been a ``missed`` verdict to
            ``unverified``.

    Returns:
        A dict with ``window`` (start/end dates) and ``days`` — one entry per
        calendar date, oldest first, each holding its reconciled ``sessions``.
        Every session carries a ``status`` of completed, planned, missed,
        unverified, moved, cancelled, skipped, or unplanned, plus the
        ``evidence`` refs behind it.
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
                evidence_sources_degraded,
            ),
        }
        for target_date in dates
    ]

    return {"window": {"start": dates[0], "end": dates[-1]}, "days": days}


def _read_training_log(project_id: str, database: str, lookback: int):
    """Return (rows, degraded_name). ``rows`` is None when the read failed."""
    try:
        from memory.firestore_db import TrainingLogStore
        return TrainingLogStore(project_id, database).get_recent(lookback), None
    except Exception:
        logger.warning("training reality: training_log read failed", exc_info=True)
        return None, "training_log"


def _read_strength_sessions(project_id: str, database: str, lookback: int):
    """Return (rows, degraded_name). ``rows`` is None when the read failed."""
    try:
        from memory.firestore_db import StrengthSessionStore
        return StrengthSessionStore(project_id, database).get_recent(lookback), None
    except Exception:
        logger.warning("training reality: strength read failed", exc_info=True)
        return None, "strength_sessions"


def _read_garmin_activities(lookback: int):
    """Return (activities, degraded_name). ``activities`` is None on failure."""
    try:
        from mcp_tools.garmin_tool import fetch_garmin_activities
        return fetch_garmin_activities(lookback), None
    except Exception:
        logger.warning("training reality: garmin read failed", exc_info=True)
        return None, "garmin_activities"


def build_training_reality(
    days_back: int = DEFAULT_DAYS_BACK,
    days_forward: int = DEFAULT_DAYS_FORWARD,
) -> dict:
    """Gather the live sources and return the reconciled window.

    Every read is best-effort and fail-open, matching ``get_training_context``:
    one outage degrades the picture rather than denying the whole answer.

    Degradation changes the verdicts, not just the metadata. A source that
    could not be read is named in ``degraded``, ``evidence_complete`` says
    whether every source answered, and any past planned session without
    evidence resolves to ``unverified`` instead of ``missed`` — because a
    failed Garmin read is not proof that Amit skipped a session.
    """
    from zoneinfo import ZoneInfo

    project_id = os.environ.get("GCP_PROJECT_ID", "")
    database = os.environ.get("FIRESTORE_DATABASE", "(default)")
    today = datetime.now(ZoneInfo("Asia/Jerusalem")).date()
    lookback = days_back + 1

    training_log, log_degraded = _read_training_log(project_id, database, lookback)
    strength_sessions, strength_degraded = _read_strength_sessions(
        project_id, database, lookback,
    )
    garmin_activities, garmin_degraded = _read_garmin_activities(lookback)

    degraded = [
        name for name in (log_degraded, strength_degraded, garmin_degraded) if name
    ]

    reality = reconcile_training_reality(
        today=today.isoformat(),
        training_log=training_log or [],
        strength_sessions=strength_sessions or [],
        garmin_activities=garmin_activities or [],
        days_back=days_back,
        days_forward=days_forward,
        evidence_sources_degraded=bool(degraded),
    )
    reality["degraded"] = degraded
    reality["evidence_complete"] = not degraded
    return reality
