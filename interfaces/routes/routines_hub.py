"""Hub routine-group APIs — named routines with per-routine streak flames.

A routine ("Morning routine", "Nightly routine", anything Amit adds) groups
habits; the routine itself carries the streak: consecutive days on which every
scheduled member habit was completed (``compute_routine_streak``). Habits keep
their own history and check-in flow in interfaces/routes/habits.py — these
routes only manage the grouping and the aggregate read.

Named ``routines_hub`` (not ``routines``) to stay unambiguous next to
core/routines/, which coordinates the Claude morning/nightly/weekly reviews.
"""
from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from interfaces.hub_auth import require_hub_session

logger = logging.getLogger(__name__)

router = APIRouter()


class CreateRoutineInput(BaseModel):
    """POST /api/routines body — name required, emoji/order optional."""

    name: str = Field(..., min_length=1, max_length=200)
    emoji: str | None = Field(None, max_length=8)
    order: int = Field(0, ge=0, le=999)


class EditRoutineInput(BaseModel):
    """PATCH /api/routines/{id} body — all fields optional."""

    name: str | None = Field(None, min_length=1, max_length=200)
    emoji: str | None = Field(None, max_length=8)
    order: int | None = Field(None, ge=0, le=999)


def _stores():
    """Build the two stores this surface reads from (lazy — Shared Pattern 5)."""
    from memory.firestore_db import HabitStore, RoutineStore  # lazy import

    project = os.environ.get("GCP_PROJECT_ID", "")
    database = os.environ.get("FIRESTORE_DATABASE", "(default)")
    return RoutineStore(project, database), HabitStore(project, database)


@router.get("/api/routines")
async def api_list_routines(
    _email: str = Depends(require_hub_session),
) -> JSONResponse:
    """Return every routine with members, today's progress, and its streak.

    Habits without a ``routine_id`` (or pointing at a deleted routine) are
    grouped under a synthetic ``{"id": null, "name": "Unassigned"}`` entry so
    nothing ever silently disappears from the Hub.

    Response shape::

        {"routines": [{id, name, emoji, order, streak, done_today,
                       scheduled_today, completed_today, habits: [...]}]}

    Each member habit carries the same enrichment as GET /api/habits
    (scheduled_today / done_today / dose_taken) minus the per-habit streak —
    the routine's flame replaces it on this surface.
    """
    from datetime import date as _date
    from memory.firestore_db import (  # lazy import
        _is_scheduled,
        _jsonsafe_doc,
        compute_routine_streak,
    )

    routine_store, habit_store = _stores()
    today_iso = datetime.now(ZoneInfo("Asia/Jerusalem")).date().isoformat()
    today = _date.fromisoformat(today_iso)

    loop = asyncio.get_running_loop()
    routines, habits, completions_by_habit = await asyncio.gather(
        loop.run_in_executor(None, routine_store.list_all),
        loop.run_in_executor(None, habit_store.list_active),
        loop.run_in_executor(None, habit_store.get_all_completions),
    )
    completions_today = {
        hid: docs[today_iso]
        for hid, docs in completions_by_habit.items()
        if today_iso in docs
    }

    known_ids = {r["id"] for r in routines}
    grouped: dict = {r["id"]: [] for r in routines}
    unassigned: list[dict] = []
    for habit in habits:
        comp = completions_today.get(habit.get("id", ""))
        member = {
            **habit,
            "scheduled_today": _is_scheduled(today, habit.get("schedule_history", [])),
            "done_today": comp is not None,
            "dose_taken": comp.get("dose_taken") if comp else None,
        }
        rid = habit.get("routine_id")
        if rid in known_ids:
            grouped[rid].append(member)
        else:
            unassigned.append(member)

    payload = []
    for routine in routines:
        members = grouped[routine["id"]]
        stats = compute_routine_streak(members, completions_by_habit, today)
        payload.append({**routine, **stats, "habits": members})
    if unassigned:
        stats = compute_routine_streak(unassigned, completions_by_habit, today)
        payload.append({
            "id": None,
            "name": "Unassigned",
            "emoji": None,
            "order": 1000,
            **stats,
            "habits": unassigned,
        })

    return JSONResponse(content=_jsonsafe_doc({"routines": payload}))


@router.post("/api/routines")
async def api_create_routine(
    body: CreateRoutineInput,
    _email: str = Depends(require_hub_session),
) -> JSONResponse:
    """Create a routine group. Membership is assigned via PATCH /api/habits."""
    from memory.firestore_db import _jsonsafe_doc  # lazy import

    routine_store, _ = _stores()
    loop = asyncio.get_running_loop()
    created = await loop.run_in_executor(
        None, routine_store.create, body.model_dump(exclude_none=False)
    )
    return JSONResponse(content=_jsonsafe_doc(created))


@router.patch("/api/routines/{routine_id}")
async def api_update_routine(
    routine_id: str,
    body: EditRoutineInput,
    _email: str = Depends(require_hub_session),
) -> JSONResponse:
    """Rename / re-emoji / re-order a routine."""
    from memory.firestore_db import _jsonsafe_doc  # lazy import

    patch = body.model_dump(exclude_unset=True)
    if not patch:
        raise HTTPException(status_code=400, detail={"error": "empty patch"})

    routine_store, _ = _stores()
    loop = asyncio.get_running_loop()
    if await loop.run_in_executor(None, routine_store.get, routine_id) is None:
        raise HTTPException(status_code=404, detail={"error": "routine not found"})
    updated = await loop.run_in_executor(None, routine_store.update, routine_id, patch)
    return JSONResponse(content=_jsonsafe_doc(updated or {}))


@router.post("/api/routines/{routine_id}/delete")
async def api_delete_routine(
    routine_id: str,
    _email: str = Depends(require_hub_session),
) -> JSONResponse:
    """Delete a routine, detaching (never deleting) its member habits.

    Members drop to the Unassigned group with all history intact — the
    preserve-history invariant applies to habit completions like everything
    else. POST rather than DELETE to match the habits surface's verb style.
    """
    routine_store, habit_store = _stores()
    loop = asyncio.get_running_loop()
    if await loop.run_in_executor(None, routine_store.get, routine_id) is None:
        raise HTTPException(status_code=404, detail={"error": "routine not found"})
    detached = await loop.run_in_executor(
        None, routine_store.delete, routine_id, habit_store
    )
    return JSONResponse(content={"ok": True, "detached_habits": detached})
