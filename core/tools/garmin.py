"""Live Garmin training status and load.

Split out of core/tools.py; registered automatically on import.
"""
from __future__ import annotations

import json
import logging

from core.tools.registry import tool

logger = logging.getLogger(__name__)


@tool({
        "name": "fetch_training_status",
        "description": (
            "Fetch today's Garmin training status (PRODUCTIVE / MAINTAINING / RECOVERY / "
            "DETRAINING / OVERREACHING), VO2 max, and load focus. "
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    })
def _handle_fetch_training_status() -> str:
    """GARMIN-04 live Garmin training status / VO2 / load focus."""
    from mcp_tools.garmin_tool import (
        fetch_garmin_training_status,
        GarminUnavailableError,
        GarminAuthError,
    )
    try:
        return json.dumps(fetch_garmin_training_status())
    except (GarminUnavailableError, GarminAuthError) as exc:
        return json.dumps({"error": str(exc)})


@tool({
        "name": "fetch_recent_activities",
        "description": (
            "Fetch Amit's last N days of Garmin activities as a normalized list "
            "(activity_id, date, type, duration_sec, distance_m, perceived_exertion, "
            "feel, training_load). Default days=7. "
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "days": {
                    "type": "integer",
                    "description": "Days of history to fetch, inclusive of today. Default 7.",
                },
            },
            "required": [],
        },
    })
def _handle_fetch_recent_activities(days: int = 7) -> str:
    """GARMIN-04 live Garmin activities for the last N days."""
    from mcp_tools.garmin_tool import (
        fetch_garmin_activities,
        GarminUnavailableError,
        GarminAuthError,
    )
    try:
        return json.dumps(fetch_garmin_activities(days=days))
    except (GarminUnavailableError, GarminAuthError) as exc:
        return json.dumps({"error": str(exc)})


@tool({
        "name": "get_acwr",
        "description": (
            "Compute Amit's acute:chronic workload ratio (ACWR) from the Postgres "
            "`activities` table. Returns JSON {acute, chronic, ratio}: acute = mean "
            "7-day training_load, chronic = mean 28-day training_load, ratio = "
            "acute/chronic. ratio is null when fewer than 14 of the last 28 days "
            "have training_load data (\"chronic baseline insufficient\"). "
            "Single-call wrapper — do NOT fetch raw activities and compute manually. "
            ""
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    })
def _handle_get_acwr() -> str:
    """Phase 19 SC-1 closeout: single-call ACWR wrapper around compute_acwr_from_db.

    Reads last 28 days from Postgres `activities`, returns
    {"acute", "chronic", "ratio"}. ratio is null when chronic baseline is
    insufficient (<14 of 28 days with training_load). compute_acwr_from_db
    swallows all exceptions and returns the sentinel — this handler never raises.
    """
    from mcp_tools.garmin_tool import compute_acwr_from_db
    return json.dumps(compute_acwr_from_db())
