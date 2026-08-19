"""GET /api/today — the Hub's home screen and Claude's `today` block.

Thin by design: every field is built by core.hub.today, so the Hub and the life
snapshot Claude receives are assembled by the same code and cannot disagree.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from core.hub.today import (
    _today_calendar,
    _today_coach_note,
    _today_coach_note_at,
    _today_departure_windows,
    _today_garmin,
    _today_meals,
    _today_nutrition_totals,
    _today_training,
    _today_weather,
)
from interfaces.hub_auth import require_hub_session

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/api/today")
async def api_today(_email: str = Depends(require_hub_session)) -> JSONResponse:
    """Compose today's full timeline from all sources.

    TIME-01..05, TIME-08 — one endpoint that aggregates calendar events,
    Garmin stats, weather, meals (slot labels + macros), training plan +
    block context, traffic-aware leave-by times for located events, the
    morning coach note, and nutrition running totals.

    Invariants (CLAUDE.md §6):
      - All sync tool calls run via run_in_executor + asyncio.gather (Pitfall 2).
      - Every Firestore-derived value passes through _jsonsafe_doc (Pitfall 4).
      - Meals carry slot LABELS only — no eaten_at/eating_time fields (TIME-03).
      - coach_note is None before the morning briefing writes daily_note (D-06).

    Returns:
        JSONResponse: {"today", "calendar", "garmin", "weather", "meals",
                       "training", "coach_note", "coach_note_at",
                       "nutrition_totals"}
    Raises:
        HTTPException 401: No valid session cookie (via require_hub_session).
    """
    from memory.firestore_db import _jsonsafe_doc  # lazy import — Shared Pattern 5

    loop = asyncio.get_running_loop()
    today_iso = datetime.now(ZoneInfo("Asia/Jerusalem")).date().isoformat()

    # Phase 1: run all independent sources concurrently (Pitfall 2 — never block the event loop).
    (
        calendar_data,
        garmin_data,
        weather_data,
        meal_data,
        training_data,
        nutrition_totals,
    ) = await asyncio.gather(
        loop.run_in_executor(None, _today_calendar, today_iso),
        loop.run_in_executor(None, _today_garmin),
        loop.run_in_executor(None, _today_weather),
        loop.run_in_executor(None, _today_meals, today_iso),
        loop.run_in_executor(None, _today_training, today_iso),
        loop.run_in_executor(None, _today_nutrition_totals, today_iso),
    )

    # Phase 2: departure windows depend on calendar output (per-event).
    calendar_with_routes = await loop.run_in_executor(
        None, _today_departure_windows, calendar_data
    )

    # Phase 3: coach note is a lightweight Firestore read (single cached doc).
    # Both reads hit the same TTL-cached self_state doc, so this stays one round trip.
    coach_note = await loop.run_in_executor(None, _today_coach_note, today_iso)
    coach_note_at = await loop.run_in_executor(None, _today_coach_note_at, today_iso)

    # Assemble and JSON-safe the entire response (Pitfall 4 — _jsonsafe_doc on ALL Firestore data).
    payload = _jsonsafe_doc({
        "today": today_iso,
        "calendar": calendar_with_routes,
        "garmin": garmin_data,
        "weather": weather_data,
        "meals": meal_data,
        "training": training_data,
        "coach_note": coach_note,
        # When the note was written — the client renders it so a morning note is
        # never mistaken for live advice. None whenever coach_note is None.
        "coach_note_at": coach_note_at,
        "nutrition_totals": nutrition_totals,
    })

    return JSONResponse(content=payload)
