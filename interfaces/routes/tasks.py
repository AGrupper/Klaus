"""Hub task and task-list APIs.

Backed by Things 3 through the Firestore mirror: `get_task_store` returns a
`ThingsTaskStore`, so every write here reaches Amit's real Things account. The
Pydantic models are the request contract and enforce bounds at the boundary
(ASVS V5 / T-27-IV) rather than trusting the store to reject bad input.
"""
from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime
from typing import Literal
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from interfaces.hub_auth import require_hub_session

logger = logging.getLogger(__name__)

router = APIRouter()


class RecurrenceInput(BaseModel):
    """Recurrence rule for a task (matches TaskStore + the recurrence engine).

    ``every_n`` is only meaningful for the ``every_n_days`` cadence. The engine
    (``_advance_once``) reads ``every_n``/``every_n_days`` tolerantly.
    """

    cadence: Literal["daily", "weekdays", "weekly", "monthly", "every_n_days"]
    anchor: Literal["schedule", "completion"] = "schedule"
    every_n: int | None = Field(None, ge=1, le=365)


class CreateTaskInput(BaseModel):
    """Pydantic model for POST /api/tasks bodies (ASVS V5 / T-27-IV).

    Field constraints mirror the RESEARCH § Security Domain definition:
      - title: 1..500 chars (non-empty, bounded)
      - notes: optional ≤10 000 chars
      - due_date: YYYY-MM-DD or None
      - due_time: HH:MM (24h) or None
      - priority: one of the four legal values
      - list_id: free string or None (defaults to "inbox" in the route)
      - recurrence: optional recurrence rule or None
    """

    title: str = Field(..., min_length=1, max_length=500)
    notes: str | None = Field(None, max_length=10_000)
    due_date: str | None = Field(None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    due_time: str | None = Field(None, pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    priority: Literal["none", "low", "medium", "high"] = "none"
    list_id: str | None = None  # None → coerced to "inbox" in the route
    recurrence: RecurrenceInput | None = None
    estimated_minutes: int | None = Field(None, ge=1, le=1_440)
    hard_deadline_at: datetime | None = None
    auto_schedule: bool | None = None
    manual_lock: bool | None = None
    calendar_event_id: str | None = Field(None, max_length=1_024)


class UpdateTaskInput(BaseModel):
    """Pydantic model for PATCH /api/tasks/{id} bodies (all fields optional)."""

    title: str | None = Field(None, min_length=1, max_length=500)
    notes: str | None = Field(None, max_length=10_000)
    due_date: str | None = Field(None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    due_time: str | None = Field(None, pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    priority: Literal["none", "low", "medium", "high"] | None = None
    list_id: str | None = None
    recurrence: RecurrenceInput | None = None
    estimated_minutes: int | None = Field(None, ge=1, le=1_440)
    hard_deadline_at: datetime | None = None
    auto_schedule: bool | None = None
    manual_lock: bool | None = None
    calendar_event_id: str | None = Field(None, max_length=1_024)


class CreateListInput(BaseModel):
    """Pydantic model for POST /api/task-lists bodies."""

    name: str = Field(..., min_length=1, max_length=200)


@router.post("/api/tasks")
async def api_create_task(
    body: CreateTaskInput,
    _email: str = Depends(require_hub_session),
) -> JSONResponse:
    """Create a new task in the authoritative Things store.

    POST /api/tasks with a CreateTaskInput body.  list_id defaults to "inbox"
    when None is supplied (Inbox is implicit — no Firestore doc exists for it).

    Returns:
        JSONResponse: The created task dict (id, title, status, …).
    Raises:
        HTTPException 401: No valid session cookie.
        HTTPException 422: Pydantic validation failure (T-27-IV).
    """
    from memory.firestore_db import _jsonsafe_doc, get_task_store  # lazy import — Shared Pattern 5

    task_dict = body.model_dump(exclude_none=False, mode="json")
    # Coerce None list_id → "inbox" (D-07 from RESEARCH: Inbox is implicit)
    if not task_dict.get("list_id"):
        task_dict["list_id"] = "inbox"

    loop = asyncio.get_running_loop()
    store = get_task_store(
        project_id=os.environ.get("GCP_PROJECT_ID", ""),
        database=os.environ.get("FIRESTORE_DATABASE", "(default)"),
    )
    task = await loop.run_in_executor(None, store.create, task_dict)
    return JSONResponse(content=_jsonsafe_doc(task))


@router.get("/api/tasks/summary")
async def api_tasks_summary(
    _email: str = Depends(require_hub_session),
) -> JSONResponse:
    """Return due-today + overdue counts in Asia/Jerusalem.

    GET /api/tasks/summary — TASK-07.

    WHY this route is declared before /api/tasks: FastAPI registers routes in
    declaration order.  The literal path /api/tasks/summary must match before
    the parametric /api/tasks/{task_id} would shadow it.

    Returns:
        JSONResponse: {"due_today": int, "overdue": int}
    Raises:
        HTTPException 401: No valid session cookie.
    """
    from memory.firestore_db import _jsonsafe_doc, get_task_store  # lazy import

    today_iso = datetime.now(ZoneInfo("Asia/Jerusalem")).date().isoformat()
    loop = asyncio.get_running_loop()
    store = get_task_store(
        project_id=os.environ.get("GCP_PROJECT_ID", ""),
        database=os.environ.get("FIRESTORE_DATABASE", "(default)"),
    )
    summary = await loop.run_in_executor(None, store.get_summary, today_iso)
    return JSONResponse(content=_jsonsafe_doc(summary))


@router.get("/api/tasks")
async def api_list_tasks(
    list_id: str | None = None,
    _email: str = Depends(require_hub_session),
) -> JSONResponse:
    """List active tasks, optionally filtered by list_id.

    GET /api/tasks?list_id=<id> — TASK-01.

    Returns:
        JSONResponse: {"tasks": [...]}
    Raises:
        HTTPException 401: No valid session cookie.
    """
    from memory.firestore_db import _jsonsafe_doc, get_task_store  # lazy import

    loop = asyncio.get_running_loop()
    store = get_task_store(
        project_id=os.environ.get("GCP_PROJECT_ID", ""),
        database=os.environ.get("FIRESTORE_DATABASE", "(default)"),
    )
    tasks = await loop.run_in_executor(None, lambda: store.list(list_id=list_id))
    return JSONResponse(content=_jsonsafe_doc({"tasks": tasks}))


@router.patch("/api/tasks/{task_id}")
async def api_update_task(
    task_id: str,
    body: UpdateTaskInput,
    _email: str = Depends(require_hub_session),
) -> JSONResponse:
    """Partially update a task.

    PATCH /api/tasks/{task_id} — TASK-01.

    Returns:
        JSONResponse: The updated task dict.
    Raises:
        HTTPException 401: No valid session cookie.
        HTTPException 422: Pydantic validation failure (T-27-IV).
    """
    from memory.firestore_db import _jsonsafe_doc, get_task_store  # lazy import

    # Only pass fields that were explicitly provided (exclude unset so None
    # values don't overwrite set fields that weren't sent in this PATCH).
    patch = body.model_dump(exclude_unset=True, mode="json")
    loop = asyncio.get_running_loop()
    store = get_task_store(
        project_id=os.environ.get("GCP_PROJECT_ID", ""),
        database=os.environ.get("FIRESTORE_DATABASE", "(default)"),
    )
    updated = await loop.run_in_executor(None, store.update, task_id, patch)
    # store.update re-fetches and returns the doc; guard None so a missing task
    # never reaches _jsonsafe_doc(None) (which would 500 — the old edit bug).
    return JSONResponse(content=_jsonsafe_doc(updated or {}))


@router.post("/api/tasks/{task_id}/complete")
async def api_complete_task(
    task_id: str,
    _email: str = Depends(require_hub_session),
) -> JSONResponse:
    """Soft-mark a task as completing and generate the next recurring instance.

    POST /api/tasks/{task_id}/complete — D-07.

    Returns:
        JSONResponse: {"next_id": str | None}
    Raises:
        HTTPException 401: No valid session cookie.
    """
    from memory.firestore_db import _jsonsafe_doc, get_task_store  # lazy import

    completed_on_iso = datetime.now(ZoneInfo("Asia/Jerusalem")).date().isoformat()
    loop = asyncio.get_running_loop()
    store = get_task_store(
        project_id=os.environ.get("GCP_PROJECT_ID", ""),
        database=os.environ.get("FIRESTORE_DATABASE", "(default)"),
    )
    result = await loop.run_in_executor(None, store.complete, task_id, completed_on_iso)
    return JSONResponse(content=_jsonsafe_doc(result))


@router.post("/api/tasks/{task_id}/undo")
async def api_undo_task(
    task_id: str,
    _email: str = Depends(require_hub_session),
) -> JSONResponse:
    """Revert a completing task back to active.

    POST /api/tasks/{task_id}/undo — D-07.

    Returns:
        JSONResponse: {"ok": True}
    Raises:
        HTTPException 401: No valid session cookie.
    """
    from memory.firestore_db import get_task_store  # lazy import

    loop = asyncio.get_running_loop()
    store = get_task_store(
        project_id=os.environ.get("GCP_PROJECT_ID", ""),
        database=os.environ.get("FIRESTORE_DATABASE", "(default)"),
    )
    await loop.run_in_executor(None, store.undo_complete, task_id)
    return JSONResponse(content={"ok": True})


@router.post("/api/tasks/{task_id}/soft-delete")
async def api_soft_delete_task(
    task_id: str,
    _email: str = Depends(require_hub_session),
) -> JSONResponse:
    """Soft-mark a task as 'completing' for the delete→undo→hard-delete flow.

    POST /api/tasks/{task_id}/soft-delete — D-13/D-14.

    Unlike /complete this NEVER generates a recurring next instance. It opens
    the undo window and satisfies the hard-delete gate (T-27-REP); /undo
    reverts it to active if the user taps Undo.

    Returns:
        JSONResponse: {"ok": True}
    Raises:
        HTTPException 401: No valid session cookie.
    """
    from memory.firestore_db import get_task_store  # lazy import

    loop = asyncio.get_running_loop()
    store = get_task_store(
        project_id=os.environ.get("GCP_PROJECT_ID", ""),
        database=os.environ.get("FIRESTORE_DATABASE", "(default)"),
    )
    await loop.run_in_executor(None, store.soft_delete, task_id)
    return JSONResponse(content={"ok": True})


@router.post("/api/tasks/{task_id}/hard-delete")
async def api_hard_delete_task(
    task_id: str,
    _email: str = Depends(require_hub_session),
) -> JSONResponse:
    """Trash a completing Things task after the Hub undo window.

    POST /api/tasks/{task_id}/hard-delete — T-27-REP.

    A replayed or forged delete of an active task is rejected with 409: the task
    must first go through the soft-complete flow so the UI always has an undo
    window. Things receives a recoverable trash edit, never a hard delete.

    Returns:
        JSONResponse: {"ok": True}
    Raises:
        HTTPException 401: No valid session cookie.
        HTTPException 409: Task is not in 'completing' state (T-27-REP).
    """
    from memory.firestore_db import get_task_store  # lazy import

    loop = asyncio.get_running_loop()
    store = get_task_store(
        project_id=os.environ.get("GCP_PROJECT_ID", ""),
        database=os.environ.get("FIRESTORE_DATABASE", "(default)"),
    )

    task = await loop.run_in_executor(None, store.get, task_id)
    if task is None or task.get("status") != "completing":
        raise HTTPException(
            status_code=409,
            detail={"error": "task not in completing state"},
        )

    await loop.run_in_executor(None, store.delete, task_id)
    return JSONResponse(content={"ok": True})


@router.post("/api/task-lists")
async def api_create_task_list(
    body: CreateListInput,
    _email: str = Depends(require_hub_session),
) -> JSONResponse:
    """Create a user-defined task list.

    POST /api/task-lists — TASK-02.

    Returns:
        JSONResponse: The created list dict (id, name).
    Raises:
        HTTPException 401: No valid session cookie.
    """
    from memory.firestore_db import _jsonsafe_doc, get_task_store  # lazy import

    loop = asyncio.get_running_loop()
    store = get_task_store(
        project_id=os.environ.get("GCP_PROJECT_ID", ""),
        database=os.environ.get("FIRESTORE_DATABASE", "(default)"),
    )
    created = await loop.run_in_executor(None, store.create_list, body.name)
    return JSONResponse(content=_jsonsafe_doc(created))


@router.get("/api/task-lists")
async def api_list_task_lists(
    _email: str = Depends(require_hub_session),
) -> JSONResponse:
    """List all user-defined task lists, with the implicit Inbox prepended.

    GET /api/task-lists — TASK-02.

    WHY Inbox is prepended: the "inbox" list_id is implicit (no Things project).
    The route always inserts it at
    position 0 so the frontend can render a stable "Inbox" entry without
    special-casing an empty-document fallback.

    Returns:
        JSONResponse: {"lists": [{"id": "inbox", "name": "Inbox"}, ...user lists]}
    Raises:
        HTTPException 401: No valid session cookie.
    """
    from memory.firestore_db import _jsonsafe_doc, get_task_store  # lazy import

    loop = asyncio.get_running_loop()
    store = get_task_store(
        project_id=os.environ.get("GCP_PROJECT_ID", ""),
        database=os.environ.get("FIRESTORE_DATABASE", "(default)"),
    )
    user_lists = await loop.run_in_executor(None, store.list_lists)
    # Prepend implicit Inbox (decision from 27-01: Inbox has no Firestore doc)
    lists = [{"id": "inbox", "name": "Inbox"}, *user_lists]
    return JSONResponse(content=_jsonsafe_doc({"lists": lists}))


@router.patch("/api/task-lists/{list_id}")
async def api_rename_task_list(
    list_id: str,
    body: CreateListInput,
    _email: str = Depends(require_hub_session),
) -> JSONResponse:
    """Rename a user-defined task list.

    PATCH /api/task-lists/{list_id} — TASK-02.

    Returns:
        JSONResponse: The updated list dict (id, name).
    Raises:
        HTTPException 401: No valid session cookie.
    """
    from memory.firestore_db import _jsonsafe_doc, get_task_store  # lazy import

    loop = asyncio.get_running_loop()
    store = get_task_store(
        project_id=os.environ.get("GCP_PROJECT_ID", ""),
        database=os.environ.get("FIRESTORE_DATABASE", "(default)"),
    )
    updated = await loop.run_in_executor(None, store.rename_list, list_id, body.name)
    return JSONResponse(content=_jsonsafe_doc(updated))


@router.delete("/api/task-lists/{list_id}")
async def api_delete_task_list(
    list_id: str,
    _email: str = Depends(require_hub_session),
) -> JSONResponse:
    """Delete a user-defined task list.

    DELETE /api/task-lists/{list_id} — TASK-02.

    Tasks previously in the deleted list retain their list_id.  They will
    appear under "Unknown list" in the UI until reassigned.  A future plan may
    add a reassign-to-inbox sweep; for now the behaviour matches TickTick's
    own delete-list semantics (tasks persist under their prior list_id).

    Returns:
        JSONResponse: {"ok": True}
    Raises:
        HTTPException 401: No valid session cookie.
    """
    from memory.firestore_db import get_task_store  # lazy import

    loop = asyncio.get_running_loop()
    store = get_task_store(
        project_id=os.environ.get("GCP_PROJECT_ID", ""),
        database=os.environ.get("FIRESTORE_DATABASE", "(default)"),
    )
    await loop.run_in_executor(None, store.delete_list, list_id)
    return JSONResponse(content={"ok": True})
