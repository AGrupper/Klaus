"""Per-set strength sessions synced from Hevy.

Split out of memory/firestore_db.py, which re-exports everything here.
"""
from __future__ import annotations

import logging
import os
from decimal import Decimal

from google.cloud import firestore
from google.api_core.exceptions import GoogleAPICallError

logger = logging.getLogger(__name__)

from memory.stores import base
from memory.stores.base import (
    _DESCENDING,
    _cache_get,
    _cache_invalidate_prefix,
    _cache_put,
    _jsonsafe_doc,
    _jsonsafe_value,
    _where,
)


class StrengthSessionStore:
    """Per-workout strength-training log synced from Hevy.

    Collection: ``strength_sessions``
    Document ID: the Hevy ``workout_id`` (idempotent — re-syncing the same
    workout lands on the same doc via merge=True).

    Unlike TrainingLogStore (session-level metadata keyed by calendar slot),
    this store holds the FULL per-exercise / per-set detail (weight, reps, RPE)
    plus the derived strength metrics pre-computed at ingest by
    ``mcp_tools.hevy_tool.normalize_workout`` (top_set, est_1rm, volume_kg).
    The two stores are independent and read side-by-side by the weekly review;
    no fragile join on date is attempted.

    Read discipline:
        get_range / get_recent / get_exercise_history never raise on Firestore
        errors — they return ``[]`` so coaching read-paths degrade gracefully.
        Reads strip ``updated_at`` (a DatetimeWithNanoseconds SERVER_TIMESTAMP)
        via _jsonsafe_doc so the result round-trips through ``json.dumps``
        (same hazard that bit MealStore / TrainingLogStore).

    Write discipline:
        upsert / delete re-raise on Firestore failure so the ingest cron knows
        the sync did not land (matches MealStore.upsert / TrainingLogStore).
    """

    _COLLECTION = "strength_sessions"

    def __init__(self, project_id: str, database: str = "(default)") -> None:
        self._client = base._make_firestore_client(project_id, database)
        self._col = self._client.collection(self._COLLECTION)

    def upsert(self, workout: dict) -> None:
        """Idempotent write keyed on workout['workout_id']. Re-raises on failure.

        Args:
            workout: Normalized workout dict from
                ``mcp_tools.hevy_tool.normalize_workout`` — must include a
                truthy ``workout_id``.

        Raises:
            ValueError: If ``workout_id`` is missing/empty (would collide).
            Exception:  Re-raises any Firestore write failure after logging.
        """
        workout_id = workout.get("workout_id")
        if not workout_id:
            raise ValueError("StrengthSessionStore.upsert requires a workout_id")
        try:
            self._col.document(str(workout_id)).set(
                {**workout, "source": "hevy", "updated_at": firestore.SERVER_TIMESTAMP},
                merge=True,
            )
        except Exception:
            logger.error("StrengthSessionStore.upsert(%r) failed", workout_id, exc_info=True)
            raise

    def delete(self, workout_id: str) -> None:
        """Delete a workout doc (Hevy 'deleted' event). Re-raises on failure."""
        try:
            self._col.document(str(workout_id)).delete()
        except Exception:
            logger.error("StrengthSessionStore.delete(%r) failed", workout_id, exc_info=True)
            raise

    def get_range(self, start_date: str, end_date: str) -> list[dict]:
        """Return sessions with date in [start_date, end_date], newest-first.

        Never raises — returns ``[]`` on any Firestore error.
        """
        try:
            query = _where(
                _where(self._col, "date", ">=", start_date), "date", "<=", end_date
            ).order_by("date", direction=_DESCENDING)
            return [_jsonsafe_doc(snap.to_dict() or {}) for snap in query.stream()]
        except Exception:
            logger.warning(
                "StrengthSessionStore.get_range(%r, %r) failed",
                start_date, end_date, exc_info=True,
            )
            return []

    def get_recent(self, days: int) -> list[dict]:
        """Return sessions with date >= today-{days}, newest-first.

        Never raises — returns ``[]`` on any Firestore error.
        """
        try:
            from datetime import date as _date, timedelta
            cutoff = (_date.today() - timedelta(days=days)).isoformat()
            query = _where(self._col, "date", ">=", cutoff).order_by(
                "date", direction=_DESCENDING
            )
            return [_jsonsafe_doc(snap.to_dict() or {}) for snap in query.stream()]
        except Exception:
            logger.warning("StrengthSessionStore.get_recent(%r) failed", days, exc_info=True)
            return []

    def get_exercise_history(self, name: str, limit: int | None = None) -> list[dict]:
        """Return the per-session progression for one exercise, newest-first.

        Scans all sessions and, for each that contains an exercise whose name
        matches ``name`` (case-insensitive), emits a compact progression record:
        ``{"date", "workout_id", "top_set", "est_1rm", "volume_kg"}``. This is
        the data Klaus uses to spot trends and stalls on a specific lift.

        Never raises — returns ``[]`` on any Firestore error.

        Args:
            name:  Exercise name to match (case-insensitive, exact).
            limit: Cap on the number of records returned (most-recent first).
        """
        try:
            target = (name or "").strip().lower()
            records: list[dict] = []
            # The nested exercises[].name array isn't Firestore-queryable, so
            # this stays a scan — but ordered newest-first server-side, so a
            # `limit` lets us stop streaming early instead of reading all docs.
            query = self._col.order_by("date", direction=_DESCENDING)
            for snap in query.stream():
                d = _jsonsafe_doc(snap.to_dict() or {})
                for ex in d.get("exercises") or []:
                    if (ex.get("name") or "").strip().lower() == target:
                        records.append({
                            "date": d.get("date"),
                            "workout_id": d.get("workout_id"),
                            "top_set": ex.get("top_set"),
                            "est_1rm": ex.get("est_1rm"),
                            "volume_kg": ex.get("volume_kg"),
                        })
                if limit and len(records) >= limit:
                    break
            return records[:limit] if limit else records
        except Exception:
            logger.warning(
                "StrengthSessionStore.get_exercise_history(%r) failed", name, exc_info=True,
            )
            return []
