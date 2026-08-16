"""Habits, their completion history, and streak/grid computation.

Split out of memory/firestore_db.py, which re-exports everything here.
"""
from __future__ import annotations

import logging

from google.cloud import firestore

logger = logging.getLogger(__name__)

from memory.stores import base
from memory.stores.base import (
    _jsonsafe_doc,
)


def _is_scheduled(target_date: "date", schedule_history: list[dict]) -> bool:
    """Return True if target_date falls on a scheduled day under the active revision.

    Selects the latest ``effective_from <= target_date`` revision from
    ``schedule_history`` (sorted ascending).  If no revision covers the date,
    returns False.

    ``days`` may be:
    - ``"daily"``  → always True
    - ``list[int]`` → Python weekday ints (Mon=0, Sun=6); checks membership.

    DST safety: operates on ``datetime.date`` objects only — no wall-clock
    component, so Israel DST transitions are transparent.
    """
    from datetime import date as _date
    if isinstance(target_date, str):
        target_date = _date.fromisoformat(target_date)

    applicable = None
    for rev in sorted(schedule_history, key=lambda r: r["effective_from"]):
        if rev["effective_from"] <= target_date.isoformat():
            applicable = rev
    if applicable is None:
        return False
    days = applicable["days"]
    if days == "daily":
        return True
    return target_date.weekday() in days


def compute_streak_and_grid(
    habit_id: str,
    schedule_history: list[dict],
    completions: dict,          # keyed by "YYYY-MM-DD"
    today: "date",
    window_days: int = 365,
) -> dict:
    """Pure function — no Firestore calls.

    Computes the current streak and 365-day contribution grid for a habit.

    Args:
        habit_id:         Unused in the calculation; kept for call-site clarity.
        schedule_history: List of ``{"effective_from": "YYYY-MM-DD", "days": ...}``
                          dicts (append-only, sorted by ``effective_from``).
        completions:      Dict keyed by ``"YYYY-MM-DD"`` with any truthy value.
        today:            ``datetime.date`` representing today in Asia/Jerusalem.
        window_days:      Number of days in the rolling grid (default 365).

    Returns::

        {
            "streak": int,
            "grid": [
                {"date": "YYYY-MM-DD", "state": "done"|"missed"|"not-scheduled"|"pending"},
                ...
            ]
        }

    DST safety: all arithmetic is on ``datetime.date`` objects (no time
    component) so Israel DST transitions are invisible.

    Streak rules (D-10/D-11/D-12/D-13):
    - ``done``          — scheduled + completion present.
    - ``missed``        — scheduled, no completion, and date < yesterday (confirmed).
    - ``not-scheduled`` — habit was not scheduled for this date.
    - ``pending``       — today or yesterday: no completion yet but still in the
                          backfill window (D-12); does NOT break the streak.

    Streak counting walks backward from today:
    - ``done``          → +1 to streak.
    - ``missed``        → pure reset: break immediately (streak stays at current total).
    - ``pending`` / ``not-scheduled`` → neutral; skip without incrementing or breaking.
    """
    from datetime import timedelta, date as _date

    if isinstance(today, str):
        today = _date.fromisoformat(today)
    yesterday = today - timedelta(days=1)
    grid = []

    for offset in range(window_days - 1, -1, -1):      # oldest → newest
        d = today - timedelta(days=offset)
        d_iso = d.isoformat()
        scheduled = _is_scheduled(d, schedule_history)

        if not scheduled:
            state = "not-scheduled"
        elif d == today:
            state = "done" if d_iso in completions else "pending"
        elif d == yesterday:
            # D-12: yesterday is still in the backfill window
            state = "done" if d_iso in completions else "pending"
        else:
            # d < yesterday: miss is confirmed (D-12)
            state = "done" if d_iso in completions else "missed"

        grid.append({"date": d_iso, "state": state})

    # Walk backward from today, counting consecutive done; stop on first confirmed miss
    streak = 0
    for cell in reversed(grid):
        if cell["state"] == "done":
            streak += 1
        elif cell["state"] == "missed":
            break           # pure reset (D-10): stop counting
        # "not-scheduled" and "pending" are neutral — pass without incrementing or breaking

    return {"streak": streak, "grid": grid}


class HabitStore:
    """Native habit/supplement store (Phase 28 — HABIT-01).

    Collection 1 — Definitions: ``habits/{habit_id}``
    Collection 2 — Completions: ``habit_completions/{YYYY-MM-DD}/records/{habit_id}``

    H-28-IV: dates are ALWAYS plain strings ("YYYY-MM-DD") — never Timestamps.
    Only ``updated_at`` uses SERVER_TIMESTAMP, stripped by _jsonsafe_doc on reads.

    Read discipline:
        list_active / get / get_completions_for_date / get_pending_today /
        get_history / get_summary never raise — return [] / None / {} on any
        Firestore error (logger.warning with exc_info=True).

    Write discipline:
        create / update / soft_delete / restore / delete / log_completion
        re-raise after logger.error so callers know the operation failed.

    Phase 28 — HABIT-01/03/04.
    """

    _COLLECTION = "habits"
    _COMPLETIONS = "habit_completions"

    def __init__(self, project_id: str, database: str = "(default)") -> None:
        self._client = base._make_firestore_client(project_id, database)
        self._col = self._client.collection(self._COLLECTION)

    # ------------------------------------------------------------------ #
    # Definition CRUD                                                     #
    # ------------------------------------------------------------------ #

    def create(self, habit: dict) -> dict:
        """Create a new habit/supplement definition.

        Accepts a ``habit`` dict with at minimum ``name`` and ``type``.
        Optional top-level ``days`` field seeds ``schedule_history`` if
        ``schedule_history`` is not already provided.

        Returns the stored document WITHOUT ``updated_at`` (H-28-IV).
        Re-raises on Firestore failure.
        """
        import uuid
        from datetime import datetime, timezone

        habit_id = habit.get("id") or uuid.uuid4().hex
        today_iso = datetime.now(timezone.utc).date().isoformat()

        # D-19: seed schedule_history from days if not already supplied
        if "schedule_history" in habit:
            schedule_history = habit["schedule_history"]
        else:
            days = habit.get("days", "daily")
            schedule_history = [{"effective_from": today_iso, "days": days}]

        # Build payload; strip caller-provided top-level "days" (it lives in schedule_history)
        base = {k: v for k, v in habit.items() if k not in ("id", "days", "schedule_history")}
        payload = {
            "slot": "Morning",
            "status": "active",
            **base,
            "id": habit_id,
            "schedule_history": schedule_history,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "updated_at": firestore.SERVER_TIMESTAMP,
        }
        try:
            self._col.document(habit_id).set(payload)
        except Exception:
            logger.error("HabitStore.create failed (name=%r)", habit.get("name"), exc_info=True)
            raise
        # Return without updated_at (H-28-IV / T-27-IV precedent)
        return {k: v for k, v in payload.items() if k != "updated_at"}

    def get(self, habit_id: str) -> dict | None:
        """Return the habit definition doc, or None if not found. Never raises."""
        try:
            snap = self._col.document(habit_id).get()
            if not snap.exists:
                return None
            return _jsonsafe_doc(snap.to_dict() or {})
        except Exception:
            logger.warning("HabitStore.get(%r) failed", habit_id, exc_info=True)
            return None

    def reclaim_stale_deletions(self, *, older_than_seconds: int = 120) -> int:
        """Self-heal habits stranded in ``status == 'completing'`` (WR-02).

        The undo-toast hard-delete is a *client-side* 4s timer; if the user
        navigates away or closes the PWA during the undo window the timer never
        fires, leaving the doc invisible (filtered from :meth:`list_active`) yet
        never deleted and with no UI path to restore or remove it.

        This finishes the delete the user intended for any ``completing`` doc
        whose ``updated_at`` is older than ``older_than_seconds`` — chosen well
        above the 4s undo window so a legitimately-pending undo is never
        reclaimed early. Returns the number of docs reclaimed. Never raises.
        """
        from datetime import datetime, timezone, timedelta
        reclaimed = 0
        try:
            from google.cloud.firestore_v1.base_query import FieldFilter
            cutoff = datetime.now(timezone.utc) - timedelta(seconds=older_than_seconds)
            query = self._col.where(filter=FieldFilter("status", "==", "completing"))
            for snap in query.stream():
                data = snap.to_dict() or {}
                updated = data.get("updated_at")
                # updated_at is a Firestore timestamp (tz-aware datetime). A
                # missing/unparseable value means we can't prove the doc is
                # still inside its undo window, so reclaim it rather than risk a
                # permanent strand.
                stale = True
                if isinstance(updated, datetime):
                    aware = updated if updated.tzinfo else updated.replace(tzinfo=timezone.utc)
                    stale = aware < cutoff
                if stale:
                    self.delete(snap.id)
                    reclaimed += 1
        except Exception:
            logger.warning("HabitStore.reclaim_stale_deletions failed", exc_info=True)
        return reclaimed

    def list_active(self) -> list[dict]:
        """Return all habits/supplements with ``status == 'active'``.

        Best-effort self-heals stranded soft-deletes first (WR-02), then lists.
        Never raises — returns [] on any Firestore error.
        """
        # Reclaim never raises; run it before listing so a zombie 'completing'
        # doc is cleaned the next time the Habits page loads.
        self.reclaim_stale_deletions()
        try:
            from google.cloud.firestore_v1.base_query import FieldFilter
            query = self._col.where(filter=FieldFilter("status", "==", "active"))
            return [_jsonsafe_doc(snap.to_dict() or {}) for snap in query.stream()]
        except Exception:
            logger.warning("HabitStore.list_active failed", exc_info=True)
            return []

    def update(self, habit_id: str, fields: dict) -> dict | None:
        """PATCH fields onto the habit definition.

        Schedule changes (``days`` key in ``fields``) are applied forward-only
        via a new ``schedule_history`` revision (D-19 / Pitfall 7): the current
        ``schedule_history`` is read, a new ``{"effective_from": today_iso, "days": ...}``
        entry is appended, and the combined list is written back.  The top-level
        ``days`` key is never stored as a direct field.

        Re-raises on Firestore failure.
        """
        from datetime import datetime, timezone
        try:
            update_payload: dict = {
                k: v for k, v in fields.items() if k != "days"
            }
            update_payload["updated_at"] = firestore.SERVER_TIMESTAMP

            if "days" in fields:
                today_iso = datetime.now(timezone.utc).date().isoformat()
                # Read-modify-write: append new revision
                snap = self._col.document(habit_id).get()
                existing = (snap.to_dict() or {}) if snap.exists else {}
                current_history = existing.get("schedule_history", [])
                new_revision = {"effective_from": today_iso, "days": fields["days"]}
                update_payload["schedule_history"] = current_history + [new_revision]

            self._col.document(habit_id).update(update_payload)
        except Exception:
            logger.error("HabitStore.update(%r) failed", habit_id, exc_info=True)
            raise
        return self.get(habit_id)

    def soft_delete(self, habit_id: str) -> None:
        """Set ``status='completing'`` (soft-delete for undo-toast window).

        Re-raises on failure.
        """
        try:
            self._col.document(habit_id).update({
                "status": "completing",
                "updated_at": firestore.SERVER_TIMESTAMP,
            })
        except Exception:
            logger.error("HabitStore.soft_delete(%r) failed", habit_id, exc_info=True)
            raise

    def restore(self, habit_id: str) -> None:
        """Revert a soft-delete by setting ``status='active'``.

        Re-raises on failure.
        """
        try:
            self._col.document(habit_id).update({
                "status": "active",
                "updated_at": firestore.SERVER_TIMESTAMP,
            })
        except Exception:
            logger.error("HabitStore.restore(%r) failed", habit_id, exc_info=True)
            raise

    def delete(self, habit_id: str) -> None:
        """Hard-delete the definition AND all completion records for this habit.

        Uses a Firestore collection group query to find all ``records``
        subcollection docs with ``habit_id == habit_id``, deletes them in a
        batch, then deletes the definition doc.

        Acceptable at personal scale (Open Question 1 — at most ~365 completion
        records per habit).  Re-raises on failure.
        """
        try:
            from google.cloud.firestore_v1.base_query import FieldFilter
            records_query = (
                self._client.collection_group("records")
                .where(filter=FieldFilter("habit_id", "==", habit_id))
            )
            batch = self._client.batch()
            for snap in records_query.stream():
                batch.delete(snap.reference)
            batch.commit()
            self._col.document(habit_id).delete()
        except Exception:
            logger.error("HabitStore.delete(%r) failed", habit_id, exc_info=True)
            raise

    # ------------------------------------------------------------------ #
    # Completion log                                                       #
    # ------------------------------------------------------------------ #

    def log_completion(
        self,
        date_str: str,
        habit_id: str,
        done: bool,
        dose_taken: str | None = None,
    ) -> None:
        """Idempotent check-off toggle (D-07).

        If ``done=True``: write/merge a completion record at
        ``habit_completions/{date_str}/records/{habit_id}`` recording
        ``dose_taken`` (D-09) and ``logged_at`` as a plain ISO string (H-28-IV).

        If ``done=False``: delete the record for un-check.

        Re-raises on Firestore write/delete failure.
        """
        from datetime import datetime, timezone
        doc_ref = (
            self._client.collection(self._COMPLETIONS)
            .document(date_str)
            .collection("records")
            .document(habit_id)
        )
        if not done:
            try:
                doc_ref.delete()
            except Exception:
                logger.error(
                    "HabitStore.log_completion: delete failed (%r, %r)",
                    date_str, habit_id, exc_info=True,
                )
                raise
            return

        payload = {
            "habit_id": habit_id,
            "date": date_str,                               # plain string (H-28-IV)
            "done": True,
            "dose_taken": dose_taken,
            "logged_at": datetime.now(timezone.utc).isoformat(),   # plain ISO string
            "updated_at": firestore.SERVER_TIMESTAMP,
        }
        try:
            doc_ref.set(payload, merge=True)
        except Exception:
            logger.error(
                "HabitStore.log_completion failed (%r, %r)",
                date_str, habit_id, exc_info=True,
            )
            raise

    def get_completions_for_date(self, date_str: str) -> dict:
        """Return ``{habit_id: completion_doc}`` for a date.

        All docs pass through ``_jsonsafe_doc`` so the result round-trips
        through ``json.dumps`` (Pitfall 1 — DatetimeWithNanoseconds guard).

        Never raises — returns {} on any Firestore error.
        """
        try:
            snaps = (
                self._client.collection(self._COMPLETIONS)
                .document(date_str)
                .collection("records")
                .stream()
            )
            return {
                snap.id: _jsonsafe_doc(snap.to_dict() or {})
                for snap in snaps
            }
        except Exception:
            logger.warning(
                "HabitStore.get_completions_for_date(%r) failed", date_str, exc_info=True
            )
            return {}

    # ------------------------------------------------------------------ #
    # Read helpers                                                         #
    # ------------------------------------------------------------------ #

    def get_pending_today(self, today_iso: str) -> list[dict]:
        """Return active habits scheduled for today that have not been completed.

        Each item in the result has ``streak`` (from ``compute_streak_and_grid``)
        and the habit's ``dose`` attached.

        Never raises — returns [] on error.
        """
        from datetime import date as _date
        try:
            today = _date.fromisoformat(today_iso)
            active = self.list_active()
            completions_today = self.get_completions_for_date(today_iso)

            pending = []
            for habit in active:
                schedule_history = habit.get("schedule_history", [])
                if not _is_scheduled(today, schedule_history):
                    continue
                if habit["id"] in completions_today:
                    continue
                # Fetch history for streak (acceptable at personal scale)
                history = self.get_history(habit["id"], today_iso)
                pending.append({
                    **habit,
                    "streak": history["streak"],
                })
            return pending
        except Exception:
            logger.warning("HabitStore.get_pending_today(%r) failed", today_iso, exc_info=True)
            return []

    def get_history(self, habit_id: str, today_iso: str, window_days: int = 365) -> dict:
        """Return ``compute_streak_and_grid`` output for ``habit_id``.

        Fetches all completion records via a collection group query on
        ``records`` subcollection, keyed by ``habit_id``.

        Never raises — returns ``{"streak": 0, "grid": []}`` on error.
        """
        from datetime import date as _date
        try:
            today = _date.fromisoformat(today_iso)
            habit = self.get(habit_id)
            if not habit:
                return {"streak": 0, "grid": []}
            schedule_history = habit.get("schedule_history", [])

            # Fetch all completion records for this habit across all dates
            try:
                from google.cloud.firestore_v1.base_query import FieldFilter
                records_query = (
                    self._client.collection_group("records")
                    .where(filter=FieldFilter("habit_id", "==", habit_id))
                )
                completions: dict = {}
                for snap in records_query.stream():
                    d = _jsonsafe_doc(snap.to_dict() or {})
                    date_key = d.get("date")
                    if date_key:
                        completions[date_key] = d
            except Exception:
                # WR-05: this must stay non-fatal (get_summary / get_pending_today
                # run inside the autonomous tick and must never crash it), but a
                # failure here silently yields streak 0 + an empty grid for EVERY
                # habit — so log LOUDLY and actionably. The usual cause is a
                # missing COLLECTION_GROUP index on records.habit_id (see
                # DEPLOYMENT.md §21). Falling back to an empty completion set.
                logger.error(
                    "HabitStore.get_history(%r) completions collection-group query "
                    "failed — streaks/grid will read as empty until fixed. If this is "
                    "FAILED_PRECONDITION, create the records.habit_id COLLECTION_GROUP "
                    "index (DEPLOYMENT.md §21).",
                    habit_id, exc_info=True,
                )
                completions = {}

            return compute_streak_and_grid(
                habit_id, schedule_history, completions, today, window_days
            )
        except Exception:
            logger.warning("HabitStore.get_history(%r) failed", habit_id, exc_info=True)
            return {"streak": 0, "grid": []}

    def get_summary(self, today_iso: str) -> dict:
        """Return ``{pending_today: int, streak_leaders: list}`` for the GlanceRail.

        ``streak_leaders`` contains up to 4 active habits sorted by descending
        streak (``[{id, name, streak}]``).

        Never raises — returns ``{"pending_today": 0, "streak_leaders": []}`` on error.
        """
        try:
            pending = self.get_pending_today(today_iso)
            active = self.list_active()

            streak_leaders = []
            for habit in active:
                history = self.get_history(habit["id"], today_iso)
                streak_leaders.append({
                    "id": habit["id"],
                    "name": habit.get("name", ""),
                    "streak": history["streak"],
                })

            streak_leaders.sort(key=lambda x: x["streak"], reverse=True)

            return {
                "pending_today": len(pending),
                "streak_leaders": streak_leaders[:4],
            }
        except Exception:
            logger.warning("HabitStore.get_summary(%r) failed", today_iso, exc_info=True)
            return {"pending_today": 0, "streak_leaders": []}
