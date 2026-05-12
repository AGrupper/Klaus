# mcp_tools/things_snapshot.py
"""Read the Things 3 snapshot pushed by local_mac/things_poller.py.

The Mac-side poller writes things_snapshot/latest to Firestore on every poll
cycle. This module reads it and returns structured task data with staleness info.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


@dataclass
class ThingsSnapshot:
    stale_minutes: int | None          # None = doc missing entirely
    today: list[dict] = field(default_factory=list)
    overdue: list[dict] = field(default_factory=list)
    due_today: list[dict] = field(default_factory=list)

    @property
    def is_missing(self) -> bool:
        return self.stale_minutes is None

    @property
    def staleness_warning(self) -> str | None:
        """Return a warning string if the snapshot is stale, else None."""
        if self.stale_minutes is None:
            return "Task data unavailable, sir."
        if self.stale_minutes > 1440:  # > 24 h
            return "Task data unavailable, sir."
        if self.stale_minutes > 60:
            return "Things 3 last synced over an hour ago — the list below may be out of date."
        if self.stale_minutes > 10:
            return f"(Things 3 last synced {self.stale_minutes} min ago, sir)"
        return None


def get_today_tasks() -> ThingsSnapshot:
    """Read things_snapshot/latest from Firestore.

    Returns a ThingsSnapshot with stale_minutes=None if the doc is missing.
    Never raises — returns an empty snapshot on any Firestore error.
    """
    try:
        from memory.firestore_db import _make_firestore_client
        project_id = os.environ["GCP_PROJECT_ID"]
        database = os.getenv("FIRESTORE_DATABASE", "(default)")
        client = _make_firestore_client(project_id, database)
        snap = client.collection("things_snapshot").document("latest").get()
        if not snap.exists:
            return ThingsSnapshot(stale_minutes=None)
        doc = snap.to_dict() or {}
    except Exception:
        logger.warning("things_snapshot: Firestore read failed", exc_info=True)
        return ThingsSnapshot(stale_minutes=None)

    updated_at_raw = doc.get("updated_at")
    stale_minutes: int | None = None
    if updated_at_raw:
        try:
            if hasattr(updated_at_raw, "timestamp"):
                # Firestore DatetimeWithNanoseconds
                updated_at = updated_at_raw.replace(tzinfo=timezone.utc) if updated_at_raw.tzinfo is None else updated_at_raw
            else:
                updated_at = datetime.fromisoformat(str(updated_at_raw)).replace(tzinfo=timezone.utc)
            delta = datetime.now(timezone.utc) - updated_at
            stale_minutes = max(0, int(delta.total_seconds() / 60))
        except Exception:
            stale_minutes = None

    return ThingsSnapshot(
        stale_minutes=stale_minutes,
        today=doc.get("today") or [],
        overdue=doc.get("overdue") or [],
        due_today=doc.get("due_today") or [],
    )
