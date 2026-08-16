"""Per-run Garmin detail, including lap splits.

Split out of memory/firestore_db.py, which re-exports everything here.
"""
from __future__ import annotations

import logging

from google.cloud import firestore

logger = logging.getLogger(__name__)

from memory.stores import base
from memory.stores.base import (
    _DESCENDING,
    _jsonsafe_doc,
    _where,
)


class RunDetailStore:
    """Per-run Garmin detail — full splits + dynamics for each run.

    Collection: ``run_details``
    Document ID: the Garmin ``activity_id`` (idempotent — re-syncing the same
    run lands on the same doc via merge=True).

    Holds the FULL per-run detail (recorded laps/intervals exactly as the watch
    captured them, plus whole-run {min,avg,max} dynamics summary and derived
    signals) pre-computed at ingest by ``mcp_tools.garmin_tool.normalize_run_detail``.
    This is the running analogue of StrengthSessionStore (which holds per-set
    strength detail) — both are read side-by-side by the coaching read-paths.

    Read discipline:
        get_range / get_recent / get_run never raise on Firestore errors — they
        return ``[]`` / ``None`` so coaching read-paths degrade gracefully.
        Reads strip ``updated_at`` (a DatetimeWithNanoseconds SERVER_TIMESTAMP)
        via _jsonsafe_doc so the result round-trips through ``json.dumps``.

    Write discipline:
        upsert / delete re-raise on Firestore failure so the ingest cron knows
        the sync did not land (matches StrengthSessionStore convention).
    """

    _COLLECTION = "run_details"

    def __init__(self, project_id: str, database: str = "(default)") -> None:
        self._client = base._make_firestore_client(project_id, database)
        self._col = self._client.collection(self._COLLECTION)

    def upsert(self, run: dict) -> None:
        """Idempotent write keyed on run['activity_id']. Re-raises on failure.

        Args:
            run: Normalized run dict from
                ``mcp_tools.garmin_tool.normalize_run_detail`` — must include a
                truthy ``activity_id``.

        Raises:
            ValueError: If ``activity_id`` is missing/empty (would collide).
            Exception:  Re-raises any Firestore write failure after logging.
        """
        activity_id = run.get("activity_id")
        if not activity_id or activity_id == "None":
            raise ValueError("RunDetailStore.upsert requires an activity_id")
        try:
            self._col.document(str(activity_id)).set(
                {**run, "source": "garmin", "updated_at": firestore.SERVER_TIMESTAMP},
                merge=True,
            )
        except Exception:
            logger.error("RunDetailStore.upsert(%r) failed", activity_id, exc_info=True)
            raise

    def delete(self, activity_id: str) -> None:
        """Delete a run doc. Re-raises on failure."""
        try:
            self._col.document(str(activity_id)).delete()
        except Exception:
            logger.error("RunDetailStore.delete(%r) failed", activity_id, exc_info=True)
            raise

    def get_run(self, activity_id: str) -> dict | None:
        """Return one run doc by activity_id, or None if absent / on error.

        Used by the ingest cron as a presence check (skip already-synced runs)
        and by the get_run_detail tool for single-run lookups.
        """
        try:
            snap = self._col.document(str(activity_id)).get()
            if not snap.exists:
                return None
            return _jsonsafe_doc(snap.to_dict() or {})
        except Exception:
            logger.warning("RunDetailStore.get_run(%r) failed", activity_id, exc_info=True)
            return None

    def get_range(self, start_date: str, end_date: str) -> list[dict]:
        """Return runs with date in [start_date, end_date], newest-first.

        Never raises — returns ``[]`` on any Firestore error.
        """
        try:
            query = _where(
                _where(self._col, "date", ">=", start_date), "date", "<=", end_date
            ).order_by("date", direction=_DESCENDING)
            return [_jsonsafe_doc(snap.to_dict() or {}) for snap in query.stream()]
        except Exception:
            logger.warning(
                "RunDetailStore.get_range(%r, %r) failed",
                start_date, end_date, exc_info=True,
            )
            return []

    def get_recent(self, days: int) -> list[dict]:
        """Return runs with date >= today-{days}, newest-first.

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
            logger.warning("RunDetailStore.get_recent(%r) failed", days, exc_info=True)
            return []
