"""Tasks, task lists, and the recurrence engine.

`get_task_store` returns a ThingsTaskStore, not the TaskStore in this
module: Things 3 is authoritative and Firestore is its mirror.

Split out of memory/firestore_db.py, which re-exports everything here.
"""
from __future__ import annotations

import logging
import os
from decimal import Decimal
from zoneinfo import ZoneInfo as _ZoneInfo

from google.cloud import firestore
from google.api_core.exceptions import GoogleAPICallError

logger = logging.getLogger(__name__)

from memory.stores import base
from memory.stores.base import (
    _DESCENDING,
    _cache_get,
    _cache_invalidate_prefix,
    _cache_put,
    _jsonsafe_doc,
    _jsonsafe_value,
    _where,
)


_TZ = _ZoneInfo("Asia/Jerusalem")


def _advance_once(base, rule: dict):
    """Advance *base* (a ``datetime.date``) by exactly one cadence step.

    Used by ``_next_due_date`` so the roll-forward loop can call this
    repeatedly without any D-06 guard inside it.  The D-06 guard lives
    in ``_next_due_date`` instead.

    cadence values: "daily" | "weekdays" | "weekly" | "monthly" | "every_n_days"
    """
    from datetime import date as _date, timedelta
    import calendar

    cadence = rule.get("cadence", "daily")

    if cadence == "daily":
        return base + timedelta(days=1)

    elif cadence == "weekdays":
        candidate = base + timedelta(days=1)
        while candidate.weekday() >= 5:  # 5=Saturday, 6=Sunday
            candidate += timedelta(days=1)
        return candidate

    elif cadence == "weekly":
        return base + timedelta(weeks=1)

    elif cadence == "monthly":
        # Month-end clamping: Jan 31 → Feb 28 (or Feb 29 in a leap year)
        year = base.year + (base.month // 12)
        month = (base.month % 12) + 1
        max_day = calendar.monthrange(year, month)[1]
        return base.replace(year=year, month=month, day=min(base.day, max_day))

    elif cadence == "every_n_days":
        n = int(rule.get("every_n_days") or rule.get("every_n") or 1)
        return base + timedelta(days=n)

    else:
        # Unknown cadence — default to daily so we never return the same date
        return base + timedelta(days=1)


def _next_due_date(current_due, completed_on, rule: dict):
    """Compute the next due date for a recurring task.

    Args:
        current_due:  The task's current ``due_date`` as a ``datetime.date``
                      object (or YYYY-MM-DD string — auto-converted).
        completed_on: The date the task was completed (Asia/Jerusalem) as a
                      ``datetime.date`` object or YYYY-MM-DD string.
        rule:         The recurrence-rule dict:
                      ``{"cadence": ..., "every_n_days": int|null, "anchor": ...}``

    Returns:
        Next due ``datetime.date``.  Always strictly > *completed_on* (D-06).

    D-06 (roll-forward):  A schedule-anchored ``candidate`` that lands on or
    before *completed_on* is advanced repeatedly (a real loop — not a single
    step) until it clears *completed_on*.  This handles tasks several cadences
    in the past (e.g. a weekly task last set for May 1 completed June 18
    requires multiple weekly advances to land after June 18).
    """
    from datetime import date as _date

    # Coerce strings to date objects
    if isinstance(current_due, str):
        current_due = _date.fromisoformat(current_due)
    if isinstance(completed_on, str):
        completed_on = _date.fromisoformat(completed_on)

    anchor = rule.get("anchor", "schedule")
    base = current_due if anchor == "schedule" else completed_on

    candidate = _advance_once(base, rule)

    # D-06: schedule-anchored next that still lands on/before completed_on
    # must roll forward until strictly future.  This MUST be a real loop —
    # a task many cadences behind needs multiple iterations.
    if anchor == "schedule":
        while candidate <= completed_on:
            candidate = _advance_once(candidate, rule)

    return candidate


def is_auto_schedule_candidate(task: dict) -> bool:
    """Return whether Klaus may place an existing task into a movable time block.

    Missing ``auto_schedule`` is intentionally treated as eligible so tasks
    created before v7 participate without a destructive migration. Fixed
    timing, recurrence, explicit deadline language, and a manual lock always
    win over the opt-in flag.

    Args:
        task: Provider-neutral task document.

    Returns:
        ``True`` when the task may be scheduled or repaired automatically.
    """
    import re

    if task.get("auto_schedule") is False or task.get("manual_lock") is True:
        return False
    if task.get("due_time") or task.get("recurrence") or task.get("hard_deadline_at"):
        return False

    text = " ".join(
        str(value or "") for value in (task.get("title"), task.get("notes"))
    )
    hard_deadline_pattern = re.compile(
        r"\b(hard\s+deadline|final\s+deadline|must\s+be\s+done|due\s+by|no\s+later\s+than)\b",
        flags=re.IGNORECASE,
    )
    return hard_deadline_pattern.search(text) is None


def get_task_store(project_id: str | None = None, database: str | None = None):
    """Return the one authoritative Things task store.

    Firestore retains a Things mirror and outbox only during the soak.  It is
    deliberately not selectable as a runtime authority: an unavailable Things
    account must surface as unavailable rather than silently serving abandoned
    Klaus-owned task data.
    """
    project_id = project_id if project_id is not None else os.environ.get("GCP_PROJECT_ID", "")
    database = database if database is not None else os.environ.get("FIRESTORE_DATABASE", "(default)")

    from memory.things_store import ThingsTaskStore
    return ThingsTaskStore(project_id=project_id, database=database)


class TaskStore:
    """Native task store — replaces TickTick as the single source of truth.

    Collection: ``tasks/{task_id}``

    Document shape:
        id: str               (uuid4 hex — doc ID)
        title: str
        notes: str | null
        due_date: str | null  ("YYYY-MM-DD" plain string — NEVER a Timestamp)
        due_time: str | null  ("HH:MM")
        priority: str         ("none"|"low"|"medium"|"high")
        list_id: str          ("inbox" or a task_list uuid)
        status: str           ("active"|"completing")
        recurrence: dict|null {"cadence", "every_n_days", "anchor"}
        series_id: str|null
        estimated_minutes: int|null
        hard_deadline_at: str|null  (ISO-8601 timestamp)
        auto_schedule: bool|null    (missing/None remains backward compatible)
        manual_lock: bool|null
        calendar_event_id: str|null
        created_at: str       (ISO-8601 UTC plain string)
        updated_at: SERVER_TIMESTAMP  (stripped by _jsonsafe_doc before json.dumps)

    T-27-IV: ``due_date``/``due_time`` are ALWAYS stored as plain strings —
    never as Firestore Timestamps or SERVER_TIMESTAMP.  Only ``updated_at``
    uses SERVER_TIMESTAMP.  All reads apply ``_jsonsafe_doc``.

    Read discipline:
        list / get / get_overdue / get_summary never raise — return [] / None / {}
        on any Firestore error (logger.warning with exc_info=True).

    Write discipline:
        create / update / complete / undo_complete / delete re-raise after
        logger.error so callers know the operation failed.

    Phase 27 — TASK-01/02/04/07.
    """

    _COLLECTION = "tasks"

    def __init__(self, project_id: str, database: str = "(default)") -> None:
        self._client = base._make_firestore_client(project_id, database)
        self._col = self._client.collection(self._COLLECTION)

    def create(self, task: dict) -> dict:
        """Create a task.  Returns the stored dict with ``id`` populated.

        ``status`` defaults to ``"active"`` if not provided.
        ``list_id`` defaults to ``"inbox"`` if not provided.
        ``priority`` defaults to ``"none"`` if not provided.

        Raises:
            Exception: Re-raises any Firestore write failure after logging.
        """
        import uuid
        from datetime import datetime, timezone

        task_id = task.get("id") or uuid.uuid4().hex
        payload = {
            "list_id": "inbox",
            "priority": "none",
            "status": "active",
            **task,
            "id": task_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "updated_at": firestore.SERVER_TIMESTAMP,
        }
        try:
            self._col.document(task_id).set(payload)
        except Exception:
            logger.error("TaskStore.create failed (title=%r)", task.get("title"), exc_info=True)
            raise
        # Return the payload without the SERVER_TIMESTAMP (not yet resolved)
        result = {k: v for k, v in payload.items() if k != "updated_at"}
        return result

    def get(self, task_id: str) -> dict | None:
        """Fetch a single task by ID.  Returns None if not found.  Never raises."""
        try:
            snap = self._col.document(task_id).get()
            if not snap.exists:
                return None
            return _jsonsafe_doc(snap.to_dict() or {})
        except Exception:
            logger.warning("TaskStore.get(%r) failed", task_id, exc_info=True)
            return None

    def list(self, list_id: str | None = None) -> list[dict]:
        """Return active tasks, optionally filtered by ``list_id``.

        Server-side filters: status==active + (list_id if provided).
        Never raises — returns [] on error.
        """
        try:
            from google.cloud.firestore_v1.base_query import FieldFilter

            query = self._col.where(filter=FieldFilter("status", "==", "active"))
            if list_id is not None:
                query = query.where(filter=FieldFilter("list_id", "==", list_id))
            return [_jsonsafe_doc(snap.to_dict() or {}) for snap in query.stream()]
        except Exception:
            logger.warning("TaskStore.list(list_id=%r) failed", list_id, exc_info=True)
            return []

    def update(self, task_id: str, fields: dict) -> dict | None:
        """Patch a task with ``fields`` and return the updated doc.  Re-raises on failure.

        ``updated_at`` is refreshed automatically.
        ``due_date``/``due_time`` fields in *fields* must be plain strings —
        the caller is responsible for format ("YYYY-MM-DD" / "HH:MM").

        Returns the re-fetched task dict so callers (the HTTP route) can echo
        the updated task back to the client — Firestore ``.update()`` itself
        returns write metadata, not the document.
        """
        try:
            self._col.document(task_id).update(
                {**fields, "updated_at": firestore.SERVER_TIMESTAMP}
            )
        except Exception:
            logger.error("TaskStore.update(%r) failed", task_id, exc_info=True)
            raise
        return self.get(task_id)

    def soft_delete(self, task_id: str) -> None:
        """Soft-mark a task as ``completing`` for the delete→undo→hard-delete flow.

        Unlike ``complete``, this NEVER generates a recurring next instance — a
        deleted recurring task must not spawn a replacement.  The ``completing``
        status opens the same undo window and satisfies the hard-delete gate
        (T-27-REP); ``undo_complete`` reverts it to ``active``.

        Re-raises any Firestore write failure after logging.
        """
        try:
            self._col.document(task_id).update({
                "status": "completing",
                "updated_at": firestore.SERVER_TIMESTAMP,
            })
        except Exception:
            logger.error("TaskStore.soft_delete(%r) failed", task_id, exc_info=True)
            raise

    def complete(self, task_id: str, completed_on_iso: str) -> dict:
        """Soft-mark a task as completing and generate the next instance for recurring tasks.

        Sets ``status="completing"`` on the current task.  For recurring tasks,
        creates a new ``status="active"`` next-instance document using
        ``_next_due_date`` and sharing the same ``series_id``.

        Args:
            task_id:          ID of the task being completed.
            completed_on_iso: Completion date as "YYYY-MM-DD" (Asia/Jerusalem).

        Returns:
            ``{"next_id": <str or None>}``

        Raises:
            Exception: Re-raises any Firestore write failure after logging.
        """
        import uuid
        from datetime import date

        snap = self._col.document(task_id).get()
        if not snap.exists:
            raise Exception(f"TaskStore.complete: task {task_id!r} not found")

        data = snap.to_dict() or {}
        try:
            self._col.document(task_id).update({
                "status": "completing",
                "updated_at": firestore.SERVER_TIMESTAMP,
            })
        except Exception:
            logger.error("TaskStore.complete(%r) failed at soft-mark", task_id, exc_info=True)
            raise

        # Generate next instance for recurring tasks
        rule = data.get("recurrence")
        next_id = None
        if rule:
            current_due = data.get("due_date")
            if current_due:
                next_due = _next_due_date(current_due, completed_on_iso, rule)
                next_id = uuid.uuid4().hex
                from datetime import datetime, timezone
                next_doc = {
                    **{k: v for k, v in data.items()
                       if k not in ("id", "status", "due_date", "created_at", "updated_at")},
                    "id": next_id,
                    "status": "active",
                    "due_date": next_due.isoformat(),
                    "created_at": datetime.now(timezone.utc).isoformat(),
                    "updated_at": firestore.SERVER_TIMESTAMP,
                }
                try:
                    self._col.document(next_id).set(next_doc)
                except Exception:
                    logger.error(
                        "TaskStore.complete(%r) failed creating next instance",
                        task_id, exc_info=True,
                    )
                    raise

        return {"next_id": next_id}

    def undo_complete(self, task_id: str, next_id: str | None = None) -> None:
        """Revert a task from ``completing`` back to ``active``.

        For recurring tasks, also deletes the generated next-instance doc.

        Args:
            task_id:  ID of the task to revert.
            next_id:  (optional) ID of the next-instance doc to delete.
                      If not provided the method looks up ``next_id`` in the
                      task doc itself (not stored by default — caller should
                      pass it explicitly for reliability).

        Raises:
            Exception: Re-raises any Firestore write failure after logging.
        """
        snap = self._col.document(task_id).get()
        if not snap.exists:
            raise Exception(f"TaskStore.undo_complete: task {task_id!r} not found")

        try:
            self._col.document(task_id).update({
                "status": "active",
                "updated_at": firestore.SERVER_TIMESTAMP,
            })
        except Exception:
            logger.error("TaskStore.undo_complete(%r) failed", task_id, exc_info=True)
            raise

        if next_id:
            try:
                self._col.document(next_id).delete()
            except Exception:
                logger.error(
                    "TaskStore.undo_complete: failed deleting next instance %r",
                    next_id, exc_info=True,
                )
                raise

    def delete(self, task_id: str) -> None:
        """Hard-delete a task document from Firestore.

        Note: the route layer (27-02) enforces that only ``status="completing"``
        tasks can be hard-deleted.  This method does the raw removal without
        any status check — keep the gate at the HTTP layer.

        Raises:
            Exception: Re-raises any Firestore failure after logging.
        """
        try:
            self._col.document(task_id).delete()
        except Exception:
            logger.error("TaskStore.delete(%r) failed", task_id, exc_info=True)
            raise

    def get_overdue(self, today_iso: str) -> list[dict]:
        """Return active tasks with ``due_date < today_iso``.

        Used by the autonomous gather and the /api/tasks/summary endpoint.
        Never raises — returns [] on error.

        Args:
            today_iso: Today's date as "YYYY-MM-DD" (Asia/Jerusalem).
        """
        try:
            from google.cloud.firestore_v1.base_query import FieldFilter

            query = (
                self._col
                .where(filter=FieldFilter("status", "==", "active"))
                .where(filter=FieldFilter("due_date", "<", today_iso))
            )
            return [_jsonsafe_doc(snap.to_dict() or {}) for snap in query.stream()]
        except Exception:
            logger.warning("TaskStore.get_overdue(%r) failed", today_iso, exc_info=True)
            return []

    def get_summary(self, today_iso: str) -> dict:
        """Return ``{due_today: int, overdue: int}`` counts.

        Reads all active tasks and counts:
          - ``due_today``:  due_date == today_iso
          - ``overdue``:    due_date < today_iso

        Never raises — returns ``{due_today: 0, overdue: 0}`` on error.

        Args:
            today_iso: Today's date as "YYYY-MM-DD" (Asia/Jerusalem).
        """
        try:
            from google.cloud.firestore_v1.base_query import FieldFilter

            query = self._col.where(filter=FieldFilter("status", "==", "active"))
            due_today = 0
            overdue = 0
            for snap in query.stream():
                doc = snap.to_dict() or {}
                due = doc.get("due_date")
                if not due:
                    continue
                if due == today_iso:
                    due_today += 1
                elif due < today_iso:
                    overdue += 1
            return {"due_today": due_today, "overdue": overdue}
        except Exception:
            logger.warning("TaskStore.get_summary(%r) failed", today_iso, exc_info=True)
            return {"due_today": 0, "overdue": 0}

    def get_today_and_overdue(self, today_iso: str) -> dict:
        """Return today's + overdue active tasks for the cron readers.

        Drop-in replacement for the retired ``ticktick_tool.get_today_tasks()``
        (D-09 cutover) — the morning briefing, nightly review, and reflection
        crons consume this exact shape:

            {
                "today":    [{"title": str, "tags": []}, ...],
                "overdue":  [{"title": str, "due": str, "tags": []}, ...],
                "due_today": [],            # legacy key; matches "today"
                "staleness_warning": None,  # Firestore is the source of truth
            }

        Native tasks have no tags concept → ``tags`` is always ``[]``.
        Never raises.
        """
        today: list[dict] = []
        overdue: list[dict] = []
        try:
            for t in self.list():  # active tasks only
                due = t.get("due_date")
                if not due:
                    continue
                if due == today_iso:
                    today.append({"title": t.get("title", ""), "tags": []})
                elif due < today_iso:
                    overdue.append({"title": t.get("title", ""), "due": due, "tags": []})
        except Exception:
            logger.warning("TaskStore.get_today_and_overdue(%r) failed", today_iso, exc_info=True)
        return {"today": today, "overdue": overdue, "due_today": [], "staleness_warning": None}


class TaskListStore:
    """Deprecated Firestore task-list storage retained only for migration reads.

    The runtime never constructs this class: Things projects are authoritative
    for every retained task-list endpoint, while Firestore's Things mirror is
    cache/outbox only. This implementation remains temporarily so historical
    migration tools can inspect legacy documents without becoming a fallback.

    Collection: ``task_lists/{list_id}``

    Document shape:
        id: str          (uuid4 hex)
        name: str
        created_at: str  (ISO-8601 UTC plain string)
        updated_at: SERVER_TIMESTAMP

    The Inbox list (``list_id="inbox"``) is IMPLICIT — it is NOT stored in
    Firestore and is NOT returned by ``list()``.  The app treats ``list_id="inbox"``
    as a UI-level constant.

    Read discipline: list never raises — returns [] on error.
    Write discipline: create / rename / delete re-raise after logging.

    Phase 27 — TASK-01.
    """

    _COLLECTION = "task_lists"

    def __init__(self, project_id: str, database: str = "(default)") -> None:
        self._client = base._make_firestore_client(project_id, database)
        self._col = self._client.collection(self._COLLECTION)

    def create(self, name: str) -> dict:
        """Create a new task list.  Returns the stored dict.

        Raises:
            Exception: Re-raises any Firestore write failure after logging.
        """
        import uuid
        from datetime import datetime, timezone

        list_id = uuid.uuid4().hex
        doc = {
            "id": list_id,
            "name": name,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "updated_at": firestore.SERVER_TIMESTAMP,
        }
        try:
            self._col.document(list_id).set(doc)
        except Exception:
            logger.error("TaskListStore.create(%r) failed", name, exc_info=True)
            raise
        return {"id": list_id, "name": name}

    def list(self) -> list[dict]:
        """Return all user-created task lists.  Never raises.

        NOTE: The Inbox list (list_id="inbox") is NOT included — it is
        implicit and has no Firestore document.
        """
        try:
            return [_jsonsafe_doc(snap.to_dict() or {}) for snap in self._col.stream()]
        except Exception:
            logger.warning("TaskListStore.list() failed", exc_info=True)
            return []

    def rename(self, list_id: str, name: str) -> None:
        """Rename a task list.  Re-raises on failure."""
        try:
            self._col.document(list_id).update({
                "name": name,
                "updated_at": firestore.SERVER_TIMESTAMP,
            })
        except Exception:
            logger.error("TaskListStore.rename(%r) failed", list_id, exc_info=True)
            raise

    def delete(self, list_id: str) -> None:
        """Delete a task list document.  Re-raises on failure.

        Note: tasks within the list are NOT automatically deleted — the route
        layer (27-02) handles cascading or reassignment to Inbox.
        """
        try:
            self._col.document(list_id).delete()
        except Exception:
            logger.error("TaskListStore.delete(%r) failed", list_id, exc_info=True)
            raise
