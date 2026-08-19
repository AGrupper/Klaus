"""The one live scheduled notification per routine.

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


class ReminderScheduleStore:
    """What Cloud Tasks is currently holding for each armed routine.

    Collection: ``routine_reminders``
    Document ID: **the routine's own id** — which is the whole point. One
    routine cannot have two live scheduled notifications because there is
    nowhere to record a second one, so changing a routine's time can never
    leave the old notification queued alongside the new one.

    Document::

        {routine_id, anchor_time, scheduled_for, target_date,
         task_name, updated_at}

    ``task_name`` is the name Cloud Tasks *assigned* on create, never one we
    composed. Composed names cannot be reused for an hour after the task is
    deleted or executed, which would break the ordinary "21:30 → 21:40 → back
    to 21:30" edit; a server-assigned name is unique by construction and is
    all we need in order to cancel.

    Read discipline: ``get`` / ``list_all`` never raise — None / [] on error.
    Write discipline: ``upsert`` / ``clear`` re-raise after logger.error, so a
    caller that just created a Cloud Task learns that we failed to record it.
    """

    _COLLECTION = "routine_reminders"

    def __init__(self, project_id: str, database: str = "(default)") -> None:
        self._client = base._make_firestore_client(project_id, database)
        self._col = self._client.collection(self._COLLECTION)

    def get(self, routine_id: str) -> dict | None:
        """Return what is scheduled for this routine, or None. Never raises."""
        try:
            snap = self._col.document(routine_id).get()
            if not snap.exists:
                return None
            return _jsonsafe_doc(snap.to_dict() or {})
        except Exception:
            logger.warning(
                "ReminderScheduleStore.get(%r) failed", routine_id, exc_info=True
            )
            return None

    def list_all(self) -> list[dict]:
        """Return every scheduled reminder. Never raises."""
        try:
            return [_jsonsafe_doc(snap.to_dict() or {}) for snap in self._col.stream()]
        except Exception:
            logger.warning("ReminderScheduleStore.list_all failed", exc_info=True)
            return []

    def upsert(self, routine_id: str, fields: dict) -> dict:
        """Record the task now holding this routine's notification. Re-raises."""
        payload = {
            **fields,
            "routine_id": routine_id,
            "updated_at": firestore.SERVER_TIMESTAMP,
        }
        try:
            self._col.document(routine_id).set(payload)
        except Exception:
            logger.error(
                "ReminderScheduleStore.upsert(%r) failed", routine_id, exc_info=True
            )
            raise
        return {k: v for k, v in payload.items() if k != "updated_at"}

    def clear(self, routine_id: str) -> None:
        """Forget this routine's schedule — it is disarmed or gone. Re-raises."""
        try:
            self._col.document(routine_id).delete()
        except Exception:
            logger.error(
                "ReminderScheduleStore.clear(%r) failed", routine_id, exc_info=True
            )
            raise
