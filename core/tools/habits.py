"""Habit adherence.

Split out of core/tools.py; registered automatically on import.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

from core.tools.registry import tool
from core.tools.state import _get_current_user_id

logger = logging.getLogger(__name__)


def _get_habit_store():
    """Return a HabitStore instance using env-driven project/database config."""
    from memory.firestore_db import HabitStore
    return HabitStore(
        project_id=os.environ.get("GCP_PROJECT_ID", ""),
        database=os.environ.get("FIRESTORE_DATABASE", "(default)"),
    )


def _habit_today_iso() -> str:
    """Return today's date in Asia/Jerusalem as YYYY-MM-DD."""
    from zoneinfo import ZoneInfo
    return datetime.now(ZoneInfo("Asia/Jerusalem")).date().isoformat()


@tool({
        "name": "get_habit_adherence",
        "description": (
            "Read today's pending habits and supplements with streak info. "
            "Returns list of items not yet checked off today with their current streak. "
            "Use to assess adherence or to prepare a coaching note."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "slot": {
                    "type": "string",
                    "enum": ["Morning", "Noon", "Evening", "Bedtime"],
                    "description": "Filter by time slot. Omit for all slots.",
                },
                "type": {
                    "type": "string",
                    "enum": ["habit", "supplement"],
                    "description": "Filter by item type. Omit for both.",
                },
            },
            "required": [],
        },
    })
def _handle_get_habit_adherence(
    slot: str | None = None,
    type: str | None = None,
) -> str:
    """Return pending habits/supplements for today with streaks (HABIT-05).

    Queries HabitStore.get_pending_today for today's Asia/Jerusalem date.
    Optional filters: slot (Morning/Noon/Evening/Bedtime) and type (habit/supplement).
    Returns a JSON list of pending items with streak info (D-16).
    """
    store = _get_habit_store()
    today_iso = _habit_today_iso()
    pending = store.get_pending_today(today_iso)
    if slot:
        pending = [h for h in pending if h.get("slot") == slot]
    if type:
        pending = [h for h in pending if h.get("type") == type]
    return json.dumps(pending)
