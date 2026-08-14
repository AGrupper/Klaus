"""Things-backed task store — the read/write surface Klaus's tools call.

Drop-in replacement for ``memory.firestore_db.TaskStore``: same method names and
return shapes, so ``core/tools.py`` handlers, the morning briefing, the nightly
review, and the autonomous tick need no changes.  In particular
:meth:`get_today_and_overdue` preserves the ``ticktick_overdue`` contract that the
autonomous engine, its prompts, and all 25 eval fixtures depend on.

Three layers of state:

  * **Things Cloud** — the source of truth.  A journaled delta protocol; see
    ``docs/things_protocol.md``.
  * **Firestore mirror** (``things_items/{uuid}`` + ``things_sync/state``) — durable
    materialized state and write/sync aid.  It survives Cloud Run cold starts, but
    is never returned as an authoritative task read.
  * **Process cache** — a module-level singleton.  ``core.tools._get_task_store()``
    constructs a fresh store per call, so an instance-level cache would never hit.

Read discipline is deliberately stricter than the retired ``TaskStore``: reads and
writes **raise** when Things is unavailable.  That preserves a visible provider
outage instead of silently turning the Firestore mirror into task authority.

Klaus-only planning fields (``priority``, ``estimated_minutes``, ``auto_schedule``,
``manual_lock``, ``calendar_event_id``) have no home in Things.  They live in a
sidecar collection ``task_meta/{uuid}`` and are merged over the Things payload on
read, keeping Amit's real Things data clean and the integration reversible.
"""
from __future__ import annotations

import logging
import os
import threading
import time
from datetime import datetime, timezone

from mcp_tools import things_tool as things
from mcp_tools.things_tool import (
    ThingsAuthError,
    ThingsUnavailableError,
)

logger = logging.getLogger(__name__)

_ITEMS_COLLECTION = "things_items"
_STATE_COLLECTION = "things_sync"
_STATE_DOC = "state"
_META_COLLECTION = "task_meta"

# Klaus-side fields with no Things equivalent, kept in the sidecar.
_SIDECAR_FIELDS = (
    "priority",
    "estimated_minutes",
    "auto_schedule",
    "manual_lock",
    "calendar_event_id",
)

_DEFAULT_UPCOMING_DAYS = 7       # "the coming week" horizon
_DEFAULT_FRESHNESS_TTL = 60      # seconds between head-index checks
_FIRESTORE_BATCH = 400           # under the 500-op batch ceiling

# Process-wide cache.  Keyed by nothing — Klaus serves exactly one Things account.
_cache_lock = threading.RLock()
_cache: dict = {
    "state": None,        # dict[uuid, payload] | None when cold
    "cursor": 0,
    "history_key": None,
    "checked_at": 0.0,
    "stale_reason": None,
}


def reset_cache() -> None:
    """Drop the process cache.  For tests and for forcing a clean rebuild."""
    with _cache_lock:
        _cache.update({
            "state": None, "cursor": 0, "history_key": None,
            "checked_at": 0.0, "stale_reason": None,
        })


def _freshness_ttl() -> int:
    try:
        return int(os.environ.get("THINGS_FRESHNESS_TTL_SECONDS", _DEFAULT_FRESHNESS_TTL))
    except ValueError:
        return _DEFAULT_FRESHNESS_TTL


class ThingsTaskStore:
    """Task store backed by Things Cloud, mirrored in Firestore."""

    def __init__(self, project_id: str, database: str = "(default)") -> None:
        self._project_id = project_id
        self._database = database
        self._client = None

    # -------------------------------------------------------------- #
    # Firestore mirror/outbox plumbing (never a task-read authority) #
    # -------------------------------------------------------------- #

    def _fs(self):
        if self._client is None:
            from memory.firestore_db import _make_firestore_client
            self._client = _make_firestore_client(self._project_id, self._database)
        return self._client

    def _load_mirror(self) -> tuple[dict[str, dict] | None, int]:
        """Load a warm mirror for sync diagnostics, never task reads."""
        try:
            client = self._fs()
            snap = client.collection(_STATE_COLLECTION).document(_STATE_DOC).get()
            meta = (snap.to_dict() or {}) if snap.exists else {}
            cursor = int(meta.get("cursor") or 0)
            if not cursor:
                return None, 0
            state = {
                doc.id: (doc.to_dict() or {})
                for doc in client.collection(_ITEMS_COLLECTION).stream()
            }
            return (state or None), cursor
        except Exception:
            logger.warning("ThingsTaskStore: mirror load failed", exc_info=True)
            return None, 0

    def _persist_mirror(self, state: dict[str, dict], cursor: int,
                        touched: set[str] | None = None) -> None:
        """Write state + cursor to Firestore.  Never raises.

        ``touched`` limits the write to the UUIDs a delta actually changed; passing
        None rewrites everything (full replay).  UUIDs that are touched but absent
        from ``state`` were deleted, so their mirror docs are removed.
        """
        try:
            client = self._fs()
            col = client.collection(_ITEMS_COLLECTION)
            uuids = list(state) if touched is None else list(touched)

            batch, ops = client.batch(), 0
            for uuid in uuids:
                payload = state.get(uuid)
                if payload is None:
                    batch.delete(col.document(uuid))
                else:
                    batch.set(col.document(uuid), payload)
                ops += 1
                if ops >= _FIRESTORE_BATCH:
                    batch.commit()
                    batch, ops = client.batch(), 0
            if ops:
                batch.commit()

            client.collection(_STATE_COLLECTION).document(_STATE_DOC).set({
                "cursor": cursor,
                "entity_count": len(state),
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }, merge=True)
        except Exception:
            logger.warning("ThingsTaskStore: mirror persist failed", exc_info=True)

    # -------------------------------------------------------------- #
    # Freshness                                                       #
    # -------------------------------------------------------------- #

    def _refresh(self, force: bool = False) -> dict[str, dict]:
        """Return a fresh Things Cloud state; never promote Firestore to authority.

        The Firestore mirror is maintained as a recovery/outbox aid, but a
        runtime task read always validates Things first.  An outage is raised to
        the boundary so it can report an unavailable authoritative provider
        rather than quietly serving stale mirror data.
        """
        with _cache_lock:
            now = time.monotonic()
            fresh_enough = (now - _cache["checked_at"]) < _freshness_ttl()
            if _cache["state"] is not None and fresh_enough and not force:
                return _cache["state"]

            try:
                account = things.fetch_history_key()
                history_key = account["history-key"]
                head = int(account.get("latest-server-index") or 0)
                _cache["history_key"] = history_key
                _cache["checked_at"] = now

                if _cache["state"] is None:
                    state, cursor = things.replay_journal(history_key)
                    _cache["state"], _cache["cursor"] = state, cursor
                    self._persist_mirror(state, cursor)
                    logger.info("ThingsTaskStore: full replay (%d entities, cursor %d)",
                                len(state), cursor)
                elif head > _cache["cursor"]:
                    touched: set[str] = set()
                    state, cursor = things.replay_journal(
                        history_key,
                        state=_cache["state"],
                        start_index=_cache["cursor"],
                        on_records=lambda recs: touched.update(u for u, *_ in recs),
                    )
                    _cache["state"], _cache["cursor"] = state, cursor
                    self._persist_mirror(state, cursor, touched)
                    logger.info("ThingsTaskStore: delta applied (%d touched, cursor %d)",
                                len(touched), cursor)

                _cache["stale_reason"] = None
            except (ThingsAuthError, ThingsUnavailableError) as exc:
                _cache["stale_reason"] = str(exc)
                logger.warning("ThingsTaskStore: authoritative refresh failed: %s", exc)
                raise
            except Exception as exc:                     # noqa: BLE001 — preserve provider outage
                _cache["stale_reason"] = str(exc)
                logger.warning("ThingsTaskStore: unexpected authoritative refresh error", exc_info=True)
                raise ThingsUnavailableError(str(exc)) from exc

            return _cache["state"] or {}

    def _staleness(self) -> str | None:
        with _cache_lock:
            return _cache["stale_reason"]

    # -------------------------------------------------------------- #
    # Sidecar                                                         #
    # -------------------------------------------------------------- #

    def _load_sidecar(self) -> dict[str, dict]:
        """Klaus-only planning fields keyed by Things uuid.  Never raises."""
        try:
            return {
                doc.id: (doc.to_dict() or {})
                for doc in self._fs().collection(_META_COLLECTION).stream()
            }
        except Exception:
            logger.warning("ThingsTaskStore: sidecar load failed", exc_info=True)
            return {}

    def _write_sidecar(self, uuid: str, fields: dict) -> None:
        """Persist Klaus-only fields.  Re-raises — this is a write path."""
        payload = {k: v for k, v in fields.items() if k in _SIDECAR_FIELDS}
        if not payload:
            return
        try:
            self._fs().collection(_META_COLLECTION).document(uuid).set(
                {**payload, "updated_at": datetime.now(timezone.utc).isoformat()},
                merge=True,
            )
        except Exception:
            logger.error("ThingsTaskStore: sidecar write failed for %s", uuid, exc_info=True)
            raise

    def _merge(self, task: dict, sidecar: dict[str, dict]) -> dict:
        extra = sidecar.get(task["id"], {})
        merged = {**task, **{k: extra[k] for k in _SIDECAR_FIELDS if k in extra}}
        merged.setdefault("priority", "none")
        return merged

    # -------------------------------------------------------------- #
    # Authoritative reads — Things failures remain visible             #
    # -------------------------------------------------------------- #

    def list(self, list_id: str | None = None) -> list[dict]:
        """Open, untrashed to-dos, optionally filtered by project or area id.

        Filtering goes through ``things_tool.live_todos``, which encodes both
        containment rules (project resolves via headings; a trashed project hides
        its children without flagging them).
        """
        state = self._refresh()
        sidecar = self._load_sidecar()
        tasks = [self._merge(t, sidecar) for t in things.live_todos(state)]
        if list_id and list_id != "inbox":
            tasks = [t for t in tasks
                     if list_id in (t.get("project_id"), t.get("area_id"))]
        elif list_id == "inbox":
            tasks = [t for t in tasks if t.get("bucket") == "inbox"]
        return tasks

    def get(self, task_id: str) -> dict | None:
        """Fetch one to-do by uuid.  Returns None if unknown.  Never raises."""
        state = self._refresh()
        payload = state.get(task_id)
        if not payload:
            return None
        task = things.normalize_task(
            task_id, payload,
            things.build_name_index(state),
            things.resolve_containers(state),
        )
        return self._merge(task, self._load_sidecar())

    def get_overdue(self, today_iso: str) -> list[dict]:
        """Open to-dos whose scheduled date is before today.  Never raises."""
        return [t for t in self.list()
                if t.get("due_date") and t["due_date"] < today_iso]

    def get_summary(self, today_iso: str) -> dict:
        """Return due-today and overdue counts from Things Cloud."""
        due_today = overdue = 0
        for task in self.list():
            due = task.get("due_date")
            if not due:
                continue
            if due == today_iso:
                due_today += 1
            elif due < today_iso:
                overdue += 1
        return {"due_today": due_today, "overdue": overdue}

    def get_upcoming(self, today_iso: str, days: int = _DEFAULT_UPCOMING_DAYS) -> list[dict]:
        """To-dos landing within the next ``days`` days, soonest first.

        Checks **both** Things date fields, because they mean different things and
        either one makes a to-do part of the coming week:

          * ``due_date``  — the scheduled date ("when I'll do it"; Things holds it
            in ``sr`` once due and ``tir`` while still ahead)
          * ``hard_deadline_at`` — the deadline (Things ``dd``, "when it's due")

        A to-do due Friday but never scheduled is invisible if you only read the
        scheduled field, which is the trap this method exists to avoid.

        One entry per to-do.  ``date`` is whichever in-window date comes first and
        ``kind`` says which field that was, so a caller can tell "I planned to do
        this Tuesday" from "this is due Tuesday".  Overdue items are excluded —
        :meth:`get_today_and_overdue` owns those.  Never raises.
        """
        from datetime import date as _date, timedelta

        try:
            start = _date.fromisoformat(today_iso)
        except ValueError:
            logger.warning("ThingsTaskStore.get_upcoming: bad date %r", today_iso)
            return []
        horizon = (start + timedelta(days=max(0, days))).isoformat()

        upcoming: list[dict] = []
        for task in self.list():
            candidates = [
                (task.get("due_date"), "scheduled"),
                (task.get("hard_deadline_at"), "deadline"),
            ]
            in_window = sorted(
                (d, kind) for d, kind in candidates
                if d and today_iso <= d <= horizon
            )
            if not in_window:
                continue
            when, kind = in_window[0]
            upcoming.append({
                "id": task["id"],
                "title": task.get("title", ""),
                "date": when,
                "kind": kind,
                "days_away": (_date.fromisoformat(when) - start).days,
                "due_date": task.get("due_date"),
                "hard_deadline_at": task.get("hard_deadline_at"),
                "project": task.get("project_name"),
                "area": task.get("area_name"),
                "tags": task.get("tags") or [],
            })

        return sorted(upcoming, key=lambda t: (t["date"], t["title"]))

    def get_today_and_overdue(self, today_iso: str) -> dict:
        """Today's + overdue to-dos in the shape the crons consume.

        Preserves the ``ticktick_overdue`` contract verbatim (D-09 cutover) so the
        morning briefing, nightly review, autonomous triage prompts, and every eval
        fixture keep working untouched.

        Unlike the Firestore-native store, ``tags`` is now populated — Things has
        real tags. ``staleness_warning`` remains a compatibility key and is always
        ``None`` for returned data: a Things outage raises instead of returning a
        stale mirror.

        Two **additive** keys extend the legacy shape without breaking it:
        ``upcoming`` (the coming week, via :meth:`get_upcoming`) and ``open_count``.
        Existing readers ignore them; new prompts can use them.  ``upcoming`` is the
        one Amit actually cares about — he dates almost nothing, so ``today`` and
        ``overdue`` are usually empty and would leave Klaus with nothing to say.
        """
        today: list[dict] = []
        overdue: list[dict] = []
        tasks = self.list()
        open_count = len(tasks)
        for task in tasks:
            due = task.get("due_date")
            if not due:
                continue
            tags = task.get("tags") or []
            if due == today_iso:
                today.append({"title": task.get("title", ""), "tags": tags})
            elif due < today_iso:
                overdue.append({
                    "title": task.get("title", ""), "due": due, "tags": tags,
                })
        return {
            "today": today,
            "overdue": overdue,
            "due_today": [],
            "staleness_warning": self._staleness(),
            "upcoming": self.get_upcoming(today_iso),
            "open_count": open_count,
        }

    # -------------------------------------------------------------- #
    # Writes — re-raise                                               #
    # -------------------------------------------------------------- #

    def _commit_batch(self, batch: dict[str, dict]) -> None:
        """Push a ``{uuid: record}`` batch and refresh.  Re-raises on failure."""
        for uuid, record in batch.items():
            self._commit(uuid, record)

    def _commit(self, uuid: str, record: dict) -> None:
        """Push one record and fold it into the cache.  Re-raises on failure."""
        with _cache_lock:
            history_key = _cache["history_key"]
            cursor = _cache["cursor"]
        if not history_key:
            self._refresh(force=True)
            with _cache_lock:
                history_key, cursor = _cache["history_key"], _cache["cursor"]
        if not history_key:
            raise ThingsUnavailableError("no Things history key available for commit")

        things.commit(history_key, {uuid: record}, cursor)

        # Force a re-read rather than guessing the post-commit index: the server
        # assigns it, and a wrong cursor would silently skip records later.
        with _cache_lock:
            _cache["checked_at"] = 0.0
        self._refresh(force=True)

    def create(self, task: dict) -> dict:
        """Create a to-do in Things.  Returns the stored task.  Re-raises on failure.

        Accepts the same dict shape as ``TaskStore.create``.  Klaus-only fields are
        split off into the sidecar; the rest becomes a Things write sequence.

        The write is a **single self-contained create**.  Following a create with
        an edit is what has repeatedly crashed the app, so nothing here amends the
        to-do it just made.  See :func:`things_tool.build_create_sequence`.
        """
        self._refresh()
        uuid, commits = things.build_create_sequence(
            task.get("title", ""),
            notes=task.get("notes"),
            due_date=task.get("due_date"),
            due_time=task.get("due_time"),
            hard_deadline_at=task.get("hard_deadline_at"),
            project_id=task.get("project_id") or (
                task.get("list_id") if task.get("list_id") not in (None, "inbox") else None
            ),
            area_id=task.get("area_id"),
            tag_ids=task.get("tag_ids"),
            checklist=task.get("checklist"),
        )
        for batch in commits:
            self._commit_batch(batch)
        if any(k in task for k in _SIDECAR_FIELDS):
            self._write_sidecar(uuid, task)
        return self.get(uuid) or {"id": uuid, "title": task.get("title", "")}

    def update(self, task_id: str, fields: dict) -> dict | None:
        """Patch a to-do.  Returns the updated task.  Re-raises on failure.

        Only the supplied keys are transmitted, so Things fields this integration
        does not model survive untouched.
        """
        encoded: dict = {}
        if "title" in fields:
            encoded["tt"] = fields["title"]
        if "notes" in fields:
            # An edit must carry a splice, never the whole note — the create
            # dialect on an edit crashes Things on launch.  The splice is sized
            # to overwrite whatever text the item currently holds.
            current = (self.get(task_id) or {}).get("notes") or ""
            encoded["nt"] = things.build_note_patch(fields["notes"], replacing=current)
        if "hard_deadline_at" in fields:
            encoded["dd"] = things.iso_to_day(fields["hard_deadline_at"])
        if "due_date" in fields or "due_time" in fields:
            reschedule = things.build_reschedule(
                fields.get("due_date"), fields.get("due_time"),
            )
            encoded.update(reschedule["p"])
        if "list_id" in fields:
            list_id = fields["list_id"] or "inbox"
            if list_id == "inbox":
                # A direct project link and heading ancestor would otherwise keep
                # the task filed even after a Hub move back to Inbox.
                encoded.update({"pr": [], "ar": [], "agr": [], "st": things.ST_INBOX})
            else:
                state = self._refresh()
                project = state.get(str(list_id))
                if not project or (
                    project.get("_class") != things.CLASS_TASK
                    or project.get("tp") != things.TP_PROJECT
                    or project.get("tr")
                ):
                    raise ValueError(f"unknown Things project list {list_id!r}")
                encoded.update({"pr": [str(list_id)], "ar": [], "agr": []})

        if encoded:
            self._refresh()
            self._commit(task_id, things.build_edit(encoded))
        if any(k in fields for k in _SIDECAR_FIELDS):
            self._write_sidecar(task_id, fields)
        return self.get(task_id)

    def complete(self, task_id: str, completed_on_iso: str | None = None) -> dict:
        """Mark a to-do complete.  Re-raises on failure.

        Returns ``{"next_id": None}`` always: Things owns recurrence and spawns the
        next instance itself, which arrives on the following delta pull.  Klaus must
        not create it (``docs/things_protocol.md`` §3).
        """
        self._refresh()
        self._commit(task_id, things.build_complete())
        return {"next_id": None}

    def undo_complete(self, task_id: str) -> None:
        """Undo a Hub completion or trash operation in Things Cloud.

        The retained Hub deliberately uses one Undo control for both actions.
        A completed Things to-do is reopened by clearing ``sp`` and restoring
        ``ss=open``; a trashed item is restored by clearing ``tr``.  Both are
        journal edits, not Firestore mutations.
        """
        state = self._refresh()
        task = state.get(task_id)
        if (
            not task
            or task.get("_class") != things.CLASS_TASK
            or task.get("tp") != things.TP_TODO
        ):
            raise ValueError(f"unknown Things task {task_id!r}")
        if task.get("tr"):
            self._commit(task_id, things.build_edit({"tr": False}))
            return
        if task.get("ss") == things.SS_COMPLETED:
            self._commit(
                task_id,
                things.build_edit({"ss": things.SS_OPEN, "sp": None}),
            )
            return
        raise ValueError(f"Things task {task_id!r} is not undoable")

    def list_lists(self) -> list[dict]:
        """Return open, untrashed Things projects in the Hub list contract."""
        state = self._refresh()
        return [
            {"id": uuid, "name": payload.get("tt") or ""}
            for uuid, payload in state.items()
            if payload.get("_class") == things.CLASS_TASK
            and payload.get("tp") == things.TP_PROJECT
            and not payload.get("tr")
        ]

    def create_list(self, name: str) -> dict:
        """Create a Hub task list as a Things project."""
        self._refresh()
        uuid, record = things.build_project_create(name)
        self._commit(uuid, record)
        return {"id": uuid, "name": name}

    def rename_list(self, list_id: str, name: str) -> dict:
        """Rename an existing Things project and preserve the Hub response."""
        state = self._refresh()
        project = state.get(list_id)
        if (
            not project
            or project.get("_class") != things.CLASS_TASK
            or project.get("tp") != things.TP_PROJECT
            or project.get("tr")
        ):
            raise ValueError(f"unknown Things project list {list_id!r}")
        self._commit(list_id, things.build_edit({"tt": name}))
        return {"id": list_id, "name": name}

    def delete_list(self, list_id: str) -> None:
        """Trash a Things project; its children remain recoverable in Things."""
        state = self._refresh()
        project = state.get(list_id)
        if (
            not project
            or project.get("_class") != things.CLASS_TASK
            or project.get("tp") != things.TP_PROJECT
            or project.get("tr")
        ):
            raise ValueError(f"unknown Things project list {list_id!r}")
        self._commit(list_id, things.build_trash())

    def delete(self, task_id: str) -> None:
        """Move a to-do to the Things trash.  Re-raises on failure.

        Deliberately not a journal delete — trashing is recoverable by hand from
        the app, a hard delete is not.
        """
        self._refresh()
        self._commit(task_id, things.build_trash())

    # ``TaskStore`` exposes soft_delete separately; both mean "trash" here.
    soft_delete = delete
