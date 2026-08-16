"""Hub habit APIs — creation, editing, check-ins, history and adherence.

Streaks and the completion grid are computed in memory/firestore_db by
`compute_streak_and_grid`; these routes shape and gate, they do not calculate.
Deletion is two-stage on purpose: soft-delete is reversible from the UI, and
hard-delete refuses unless the habit is already soft-deleted.
"""
from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timedelta
from typing import Literal
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from interfaces.hub_auth import require_hub_session

logger = logging.getLogger(__name__)

router = APIRouter()


class CreateHabitInput(BaseModel):
    """Pydantic model for POST /api/habits bodies (ASVS V5 / T-28-input).

    Field constraints:
      - name: 1..500 chars (non-empty, bounded)
      - type: habit | supplement (Literal)
      - dose: optional ≤200 chars; plain string, no markup (T-28-xss)
      - slot: one of the four named time-of-day slots (D-05)
      - days: "daily" or list of weekday ints 0-6 Mon=0 (D-04)
    """

    name: str = Field(..., min_length=1, max_length=500)
    type: Literal["habit", "supplement"] = "habit"
    dose: str | None = Field(None, max_length=200)
    slot: Literal["Morning", "Noon", "Evening", "Bedtime"] = "Morning"
    days: str | list[int] = "daily"  # "daily" | weekday ints (Mon=0), D-04


class EditHabitInput(BaseModel):
    """Pydantic model for PATCH /api/habits/{id} (all fields optional, T-28-input).

    ``effective_from`` is an optional date that, if provided with a schedule
    change (``days``), must be >= today (D-19 / T-28-schedule).  When absent
    the route defaults to today so the store always uses today's date for the
    new schedule revision.
    """

    name: str | None = Field(None, min_length=1, max_length=500)
    type: Literal["habit", "supplement"] | None = None
    dose: str | None = Field(None, max_length=200)
    slot: Literal["Morning", "Noon", "Evening", "Bedtime"] | None = None
    days: str | list[int] | None = None
    # Explicit effective_from for a schedule revision (D-19):
    # must be >= today_iso or the route returns 400 (T-28-schedule).
    effective_from: str | None = Field(None, pattern=r"^\d{4}-\d{2}-\d{2}$")


class CheckinInput(BaseModel):
    """Pydantic model for POST /api/habits/{id}/checkin (T-28-backfill / D-11).

    ``date`` is validated as YYYY-MM-DD.  The route enforces that it is either
    today or yesterday (Asia/Jerusalem) — older dates return 400.
    ``dose_taken`` records the actual dose for supplements (D-09).
    """

    date: str = Field(..., pattern=r"^\d{4}-\d{2}-\d{2}$")
    done: bool = True
    dose_taken: str | None = Field(None, max_length=200)


@router.get("/api/habits/summary")
async def api_habits_summary(
    _email: str = Depends(require_hub_session),
) -> JSONResponse:
    """Return pending-today count + streak leaders for the GlanceRail (HABIT-04).

    GET /api/habits/summary — TIME-06 / GlanceRail.

    WHY this route is declared before /api/habits/{habit_id}: FastAPI registers
    routes in declaration order.  The literal path /api/habits/summary must
    match before the parametric /api/habits/{habit_id} would shadow it
    (same note as /api/tasks/summary line 1834).

    Returns:
        JSONResponse: {"pending_today": int, "streak_leaders": [{id, name, streak}]}
    Raises:
        HTTPException 401: No valid session cookie.
    """
    from memory.firestore_db import HabitStore, _jsonsafe_doc  # lazy import

    today_iso = datetime.now(ZoneInfo("Asia/Jerusalem")).date().isoformat()
    loop = asyncio.get_running_loop()
    store = HabitStore(
        project_id=os.environ.get("GCP_PROJECT_ID", ""),
        database=os.environ.get("FIRESTORE_DATABASE", "(default)"),
    )
    summary = await loop.run_in_executor(None, store.get_summary, today_iso)
    return JSONResponse(content=_jsonsafe_doc(summary))


@router.get("/api/habits")
async def api_list_habits(
    _email: str = Depends(require_hub_session),
) -> JSONResponse:
    """List all active habits/supplements enriched with today's state (HABIT-01, TIME-06).

    GET /api/habits — HABIT-01 / TIME-06.

    Each item is enriched with four additional fields so the HabitsBand and
    HabitRow can render without extra per-item calls:
      - scheduled_today: bool — is this habit scheduled for today?
      - done_today: bool — has it been checked off today?
      - dose_taken: str|None — dose from today's completion record (D-09)
      - streak: int — current streak from compute_streak_and_grid

    Computation:
      - list_active() → all active definitions
      - get_completions_for_date(today_iso) → today's completion map
      - _is_scheduled(today, schedule_history) → scheduled_today (pure, no Firestore)
      - get_history(habit_id, today_iso) → streak (one Firestore call per habit;
        acceptable at personal scale of 10-20 items)

    Returns:
        JSONResponse: {"habits": [...enriched items...]}
    Raises:
        HTTPException 401: No valid session cookie.
    """
    from datetime import date as _date
    from memory.firestore_db import HabitStore, _jsonsafe_doc, _is_scheduled  # lazy import

    today_iso = datetime.now(ZoneInfo("Asia/Jerusalem")).date().isoformat()
    today = _date.fromisoformat(today_iso)

    loop = asyncio.get_running_loop()
    store = HabitStore(
        project_id=os.environ.get("GCP_PROJECT_ID", ""),
        database=os.environ.get("FIRESTORE_DATABASE", "(default)"),
    )
    habits = await loop.run_in_executor(None, store.list_active)
    completions = await loop.run_in_executor(None, store.get_completions_for_date, today_iso)

    enriched = []
    for h in habits:
        hid = h.get("id", "")
        schedule_history = h.get("schedule_history", [])
        scheduled_today = _is_scheduled(today, schedule_history)
        comp = completions.get(hid)
        done_today = comp is not None
        # dose_taken: plain string from the completion record (D-09); never HTML (T-28-xss)
        dose_taken = comp.get("dose_taken") if comp else None
        history = await loop.run_in_executor(None, store.get_history, hid, today_iso)
        streak = history.get("streak", 0) if history else 0
        enriched.append({
            **h,
            "scheduled_today": scheduled_today,
            "done_today": done_today,
            "dose_taken": dose_taken,
            "streak": streak,
        })

    return JSONResponse(content=_jsonsafe_doc({"habits": enriched}))


@router.post("/api/habits")
async def api_create_habit(
    body: CreateHabitInput,
    _email: str = Depends(require_hub_session),
) -> JSONResponse:
    """Create a new habit or supplement definition (HABIT-01).

    POST /api/habits with a CreateHabitInput body.  The store seeds
    ``schedule_history`` from the ``days`` field (D-19 / D-04).

    Returns:
        JSONResponse: The created habit dict.
    Raises:
        HTTPException 401: No valid session cookie.
        HTTPException 422: Pydantic validation failure (T-28-input).
    """
    from memory.firestore_db import HabitStore, _jsonsafe_doc  # lazy import

    habit_dict = body.model_dump(exclude_none=False)
    loop = asyncio.get_running_loop()
    store = HabitStore(
        project_id=os.environ.get("GCP_PROJECT_ID", ""),
        database=os.environ.get("FIRESTORE_DATABASE", "(default)"),
    )
    created = await loop.run_in_executor(None, store.create, habit_dict)
    return JSONResponse(content=_jsonsafe_doc(created))


@router.patch("/api/habits/{habit_id}")
async def api_update_habit(
    habit_id: str,
    body: EditHabitInput,
    _email: str = Depends(require_hub_session),
) -> JSONResponse:
    """Partially update a habit/supplement definition (HABIT-01).

    PATCH /api/habits/{habit_id} with an EditHabitInput body.

    D-19 / T-28-schedule gate: if the body carries a schedule change (``days``)
    with an explicit ``effective_from`` that is strictly before today (Asia/Jerusalem),
    returns 400 — retroactive schedule rewrites are forbidden.  When ``effective_from``
    is absent the store always uses today as the revision date, which is always valid.

    Returns:
        JSONResponse: The updated habit dict.
    Raises:
        HTTPException 400: effective_from is in the past (T-28-schedule / D-19).
        HTTPException 401: No valid session cookie.
        HTTPException 422: Pydantic validation failure (T-28-input).
    """
    from memory.firestore_db import HabitStore, _jsonsafe_doc  # lazy import

    today_iso = datetime.now(ZoneInfo("Asia/Jerusalem")).date().isoformat()

    # D-19 / T-28-schedule: reject past effective_from to prevent retroactive rewrites.
    patch = body.model_dump(exclude_unset=True)
    if "days" in patch and "effective_from" in patch and patch["effective_from"] is not None:
        if patch["effective_from"] < today_iso:
            raise HTTPException(
                status_code=400,
                detail={"error": "effective_from must be today or later"},
            )
    # Remove effective_from from the patch dict — the store always uses today as
    # the revision effective_from (HabitStore.update is the single source of truth
    # for revision dates).
    patch.pop("effective_from", None)

    loop = asyncio.get_running_loop()
    store = HabitStore(
        project_id=os.environ.get("GCP_PROJECT_ID", ""),
        database=os.environ.get("FIRESTORE_DATABASE", "(default)"),
    )
    updated = await loop.run_in_executor(None, store.update, habit_id, patch)
    return JSONResponse(content=_jsonsafe_doc(updated or {}))


@router.post("/api/habits/{habit_id}/checkin")
async def api_habit_checkin(
    habit_id: str,
    body: CheckinInput,
    _email: str = Depends(require_hub_session),
) -> JSONResponse:
    """Toggle a habit check-off for today or yesterday (D-07 / D-11 / D-12).

    POST /api/habits/{habit_id}/checkin with a CheckinInput body.

    D-11 / T-28-backfill gate: the ``date`` field must be either today or
    yesterday (Asia/Jerusalem).  Any older date returns 400 to prevent
    retroactive history rewrites beyond the one-day backfill window.

    done=True  → writes a completion record (idempotent set).
    done=False → deletes the completion record (un-check / toggle, D-07).

    dose_taken records the actual dose for supplements (D-09); plain string,
    never HTML (T-28-xss).

    Returns:
        JSONResponse: {"ok": True}
    Raises:
        HTTPException 400: date is older than yesterday (T-28-backfill / D-11).
        HTTPException 401: No valid session cookie.
        HTTPException 422: Pydantic validation failure (T-28-input).
    """
    from memory.firestore_db import HabitStore  # lazy import

    # D-11 / T-28-backfill gate: only today or yesterday (Asia/Jerusalem) allowed.
    _tz = ZoneInfo("Asia/Jerusalem")
    today_iso = datetime.now(_tz).date().isoformat()
    yesterday_iso = (datetime.now(_tz).date() - timedelta(days=1)).isoformat()
    if body.date not in (today_iso, yesterday_iso):
        raise HTTPException(
            status_code=400,
            detail={"error": "date must be today or yesterday"},
        )

    loop = asyncio.get_running_loop()
    store = HabitStore(
        project_id=os.environ.get("GCP_PROJECT_ID", ""),
        database=os.environ.get("FIRESTORE_DATABASE", "(default)"),
    )
    await loop.run_in_executor(
        None, store.log_completion, body.date, habit_id, body.done, body.dose_taken
    )
    return JSONResponse(content={"ok": True})


@router.get("/api/habits/{habit_id}/history")
async def api_habit_history(
    habit_id: str,
    _email: str = Depends(require_hub_session),
) -> JSONResponse:
    """Return the 365-day four-state contribution grid + current streak (HABIT-04).

    GET /api/habits/{habit_id}/history — HABIT-04.

    States: done | missed | pending | not-scheduled (D-13).

    Returns:
        JSONResponse: {"streak": int, "grid": [{date, state}, ...]}
    Raises:
        HTTPException 401: No valid session cookie.
    """
    from memory.firestore_db import HabitStore, _jsonsafe_doc  # lazy import

    today_iso = datetime.now(ZoneInfo("Asia/Jerusalem")).date().isoformat()
    loop = asyncio.get_running_loop()
    store = HabitStore(
        project_id=os.environ.get("GCP_PROJECT_ID", ""),
        database=os.environ.get("FIRESTORE_DATABASE", "(default)"),
    )
    history = await loop.run_in_executor(None, store.get_history, habit_id, today_iso)
    return JSONResponse(content=_jsonsafe_doc(history))


@router.post("/api/habits/{habit_id}/soft-delete")
async def api_soft_delete_habit(
    habit_id: str,
    _email: str = Depends(require_hub_session),
) -> JSONResponse:
    """Soft-delete a habit (set status='completing') to open the undo-toast window.

    POST /api/habits/{habit_id}/soft-delete — D-20.

    The frontend shows an undo toast; if not tapped, the hard-delete is
    called after the toast timeout.  /restore reverts to active if tapped.

    Returns:
        JSONResponse: {"ok": True}
    Raises:
        HTTPException 401: No valid session cookie.
    """
    from memory.firestore_db import HabitStore  # lazy import

    loop = asyncio.get_running_loop()
    store = HabitStore(
        project_id=os.environ.get("GCP_PROJECT_ID", ""),
        database=os.environ.get("FIRESTORE_DATABASE", "(default)"),
    )
    await loop.run_in_executor(None, store.soft_delete, habit_id)
    return JSONResponse(content={"ok": True})


@router.post("/api/habits/{habit_id}/restore")
async def api_restore_habit(
    habit_id: str,
    _email: str = Depends(require_hub_session),
) -> JSONResponse:
    """Restore a soft-deleted habit to active (undo-toast action, D-20).

    POST /api/habits/{habit_id}/restore — D-20.

    Returns:
        JSONResponse: {"ok": True}
    Raises:
        HTTPException 401: No valid session cookie.
    """
    from memory.firestore_db import HabitStore  # lazy import

    loop = asyncio.get_running_loop()
    store = HabitStore(
        project_id=os.environ.get("GCP_PROJECT_ID", ""),
        database=os.environ.get("FIRESTORE_DATABASE", "(default)"),
    )
    await loop.run_in_executor(None, store.restore, habit_id)
    return JSONResponse(content={"ok": True})


@router.post("/api/habits/{habit_id}/hard-delete")
async def api_hard_delete_habit(
    habit_id: str,
    _email: str = Depends(require_hub_session),
) -> JSONResponse:
    """Hard-delete a habit and all its completion records — only allowed when
    status='completing'.

    POST /api/habits/{habit_id}/hard-delete — D-20.

    The habit must first be soft-deleted (status='completing') via
    /soft-delete; otherwise 409 is returned.  This gate prevents
    accidental hard-deletes that bypass the undo-toast flow.

    Returns:
        JSONResponse: {"ok": True}
    Raises:
        HTTPException 401: No valid session cookie.
        HTTPException 409: Habit is not in 'completing' state (D-20 gate).
    """
    from memory.firestore_db import HabitStore  # lazy import

    loop = asyncio.get_running_loop()
    store = HabitStore(
        project_id=os.environ.get("GCP_PROJECT_ID", ""),
        database=os.environ.get("FIRESTORE_DATABASE", "(default)"),
    )

    habit = await loop.run_in_executor(None, store.get, habit_id)
    if habit is None or habit.get("status") != "completing":
        raise HTTPException(
            status_code=409,
            detail={"error": "habit not in completing state"},
        )

    await loop.run_in_executor(None, store.delete, habit_id)
    return JSONResponse(content={"ok": True})
