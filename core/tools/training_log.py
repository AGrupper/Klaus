"""Manual training log entries.

Split out of core/tools.py; registered automatically on import.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone

from core.tools.registry import tool

logger = logging.getLogger(__name__)


@tool({
        "name": "log_training",
        "description": (
            "Log a completed or skipped training session. "
            "Call when Amit reports a workout done, skipped, or RPE. "
            "Parameters: date (YYYY-MM-DD, required), session_type (gym/run/etc), "
            "completed (bool), rpe (1–10 optional), notes (optional), "
            "skipped_reason (rest_recovery | sick_injured | too_busy | other, optional)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "date": {
                    "type": "string",
                    "description": "Training date in YYYY-MM-DD format.",
                },
                "session_type": {
                    "type": "string",
                    "description": "Type of session (gym, run, bike, swim, etc.).",
                },
                "completed": {
                    "type": "boolean",
                    "description": "True if the session was completed; False if skipped.",
                },
                "skipped_reason": {
                    "type": "string",
                    "description": (
                        "Reason for skipping. One of: rest_recovery, sick_injured, "
                        "too_busy, other."
                    ),
                },
                "rpe": {
                    "type": "integer",
                    "description": "Perceived exertion on 1–10 scale (Rate of Perceived Exertion).",
                },
                "feel": {
                    "type": "integer",
                    "description": "Garmin feel value (verbatim, 0–4 scale).",
                },
                "notes": {
                    "type": "string",
                    "description": "Free-form session notes from Amit.",
                },
                "source": {
                    "type": "string",
                    "description": "Origin of the log entry: telegram | garmin | manual_chat.",
                },
                "garmin_activity_id": {
                    "type": "string",
                    "description": "Garmin activity ID if this log entry was auto-created from Garmin.",
                },
            },
            "required": ["date"],
        },
    })
def _handle_log_training(**kwargs) -> str:
    """LOG-03 write one training session to TrainingLogStore."""
    from memory.firestore_db import TrainingLogStore
    store = TrainingLogStore(
        project_id=os.environ["GCP_PROJECT_ID"],
        database=os.environ.get("FIRESTORE_DATABASE", "(default)"),
    )
    # Derive slot from explicit slot kwarg, else a unique timestamped manual slot.
    # A literal "manual" slot collides on {date}_manual, so a second same-day
    # free-form chat log would overwrite the first via merge=True (data loss).
    if "slot" not in kwargs or not kwargs.get("slot"):
        kwargs["slot"] = datetime.now(timezone.utc).strftime("manual_%H%M%S")
    try:
        store.log_session(**kwargs)
        return json.dumps({"ok": True})
    except Exception as exc:
        return json.dumps({"error": str(exc)})


@tool({
        "name": "get_training_history",
        "description": (
            "Return recent training log entries from Firestore. "
            "Use days param (default 7) for recent history."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "days": {
                    "type": "integer",
                    "description": "Number of days of history to return. Default 7.",
                },
            },
            "required": [],
        },
    })
def _handle_get_training_history(days: int = 7) -> str:
    """LOG-04 return recent training log entries as JSON."""
    from memory.firestore_db import TrainingLogStore
    store = TrainingLogStore(
        project_id=os.environ["GCP_PROJECT_ID"],
        database=os.environ.get("FIRESTORE_DATABASE", "(default)"),
    )
    # default=str guards against any non-JSON-serialisable Firestore value
    # (e.g. a server timestamp) slipping through the store's normalisation.
    return json.dumps(store.get_recent(days), default=str)
