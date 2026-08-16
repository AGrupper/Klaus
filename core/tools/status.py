"""Ambient context and Klaus's own health: weather, today's Garmin
readings, self-state and Web Push delivery.

Split out of core/tools.py; registered automatically on import.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone

from core.tools.registry import tool

logger = logging.getLogger(__name__)


def _get_hub_settings_store():
    """Return a HubSettingsStore instance using env-driven project/database config."""
    from memory.firestore_db import HubSettingsStore
    return HubSettingsStore(
        project_id=os.environ.get("GCP_PROJECT_ID", ""),
        database=os.environ.get("FIRESTORE_DATABASE", "(default)"),
    )


def _get_push_subscription_store():
    """Return a PushSubscriptionStore instance using env-driven project/database config."""
    from memory.firestore_db import PushSubscriptionStore
    return PushSubscriptionStore(
        project_id=os.environ.get("GCP_PROJECT_ID", ""),
        database=os.environ.get("FIRESTORE_DATABASE", "(default)"),
    )


@tool({
        "name": "fetch_weather",
        "description": (
            "Fetch current weather conditions and today/tomorrow forecast for a location. "
            "Defaults to Tel Aviv. Use when the user asks about weather, temperature, "
            "rain, or when composing a daily briefing."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "location": {
                    "type": "string",
                    "description": "City name or coordinates (default: 'Tel Aviv').",
                },
            },
            "required": [],
        },
    })
def _handle_fetch_weather(location: str = "Tel Aviv") -> str:
    result = fetch_weather(location=location)
    return json.dumps(result)


@tool({
        "name": "fetch_garmin_today",
        "description": (
            "Fetch today's health summary from Garmin Connect: sleep score, sleep hours, "
            "HRV status, body battery, and resting heart rate. "
            "Use when the user asks about sleep, recovery, readiness, or health data."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    })
def _handle_fetch_garmin_today() -> str:
    result = fetch_garmin_today()
    return json.dumps(result)


@tool({
        "name": "get_self_status",
        "description": (
            "Return Klaus's retained operational state: container uptime, current "
            "status timestamp, and the latest reflection journal summary. "
            "Available through Claude MCP. "
            "Use when asked about current status, uptime, or health. "
            "It deliberately excludes model usage, costs, and fallback telemetry."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    })
def _handle_get_self_status() -> str:
    """Return retained operational state without model, cost, or fallback telemetry."""
    import os as _os

    result: dict = {}

    # --- Uptime via /proc/uptime (Linux / Cloud Run) ---
    try:
        with open("/proc/uptime", "r") as f:
            uptime_seconds = float(f.read().split()[0])
        hours, remainder = divmod(int(uptime_seconds), 3600)
        minutes = remainder // 60
        result["uptime"] = f"{hours}h {minutes}m"
        result["uptime_seconds"] = uptime_seconds
    except (OSError, ValueError):
        # macOS / local dev — /proc/uptime not available
        result["uptime"] = "unavailable (local dev or non-Linux)"

    # --- Timestamp ---
    result["status_at"] = datetime.now(timezone.utc).isoformat()

    # --- Journal (Phase 17) ---
    try:
        project_id = _os.environ.get("GCP_PROJECT_ID")
        if project_id:
            database = _os.environ.get("FIRESTORE_DATABASE", "(default)")
            from memory.firestore_db import JournalStore
            recent = JournalStore(project_id=project_id, database=database).get_recent(1)
            if recent:
                j = recent[0]
                result["journal"] = {
                    "date": j.get("date"),
                    "summary": j.get("summary"),
                    "mood": j.get("mood"),
                }
            else:
                result["journal"] = None
        else:
            result["journal"] = None
    except Exception as exc:
        result["journal"] = None
        result["journal_error"] = str(exc)

    return json.dumps(result)


@tool({
        "name": "get_push_health",
        "description": (
            "Return Web Push self-awareness data: how many devices are subscribed, "
            "each device's user agent / last successful delivery timestamp / failure "
            "count, and when push was first enabled. "
            "Available through Claude MCP."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    })
def _handle_get_push_health() -> str:
    """Report Web Push subscription health (D-13 self-awareness).

    T-29-09 mitigation: only user_agent/last_success_at/failure_count are
    surfaced per subscription — the p256dh/auth encryption keys and the VAPID
    private key are never included in the response.
    """
    from memory.firestore_db import _jsonsafe_doc

    sub_store = _get_push_subscription_store()
    settings_store = _get_hub_settings_store()

    subscriptions = sub_store.list_all()
    devices = [
        {
            "user_agent": sub.get("user_agent"),
            "last_success_at": sub.get("last_success_at"),
            "failure_count": sub.get("failure_count", 0),
        }
        for sub in subscriptions
    ]
    settings = _jsonsafe_doc(settings_store.get())

    return json.dumps({
        "subscription_count": len(devices),
        "devices": devices,
        "push_enabled_at": settings.get("push_enabled_at"),
    })
