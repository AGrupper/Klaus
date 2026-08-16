"""Append-only ledgers: what Klaus said, what Klaus did, and how Amit
reacted.

Split out of memory/firestore_db.py, which re-exports everything here.
"""
from __future__ import annotations

import logging

from google.cloud import firestore

logger = logging.getLogger(__name__)

from memory.stores import base
from memory.stores.base import (
    _jsonsafe_doc,
)


class OutreachLogStore:
    """Per-day record of autonomous outreach sends for repeat-suppression context.

    Schema (collection: ``outreach_log/{YYYY-MM-DD}``):
        date: str                   # YYYY-MM-DD (also the doc id)
        entries: list[dict]         # each entry = {topic_key, time, draft, final, tick_index}
        updated_at: SERVER_TIMESTAMP  # doc-level only — set by append(), NOT inside entries

    D-07 — `topic_key` comes from the tick-brain JSON output.
    D-09 — daily reset: each new date key is a fresh document; no cross-day carryover.
    D-10 — written only after `send_and_inject` succeeds (caller responsibility).

    Reads (`get_today`, `topics_today`) never raise — they return `[]` on
    Firestore error so the next tick can keep ticking. Writes (`append`)
    re-raise after logging so the caller can decide whether to abort.

    Phase 18 — AUTO-03.

    NOTE 2 — DO NOT include ``firestore.SERVER_TIMESTAMP`` (or any other
    sentinel value) inside the ``entry`` dict you pass to ``append()``.
    ``ArrayUnion`` compares list elements by deep equality, and each
    ``SERVER_TIMESTAMP`` sentinel is a freshly allocated object — so two
    ticks emitting the "same" entry with embedded sentinels would NOT
    de-duplicate, defeating the atomic-append-without-duplicates semantic.
    Keep ``updated_at`` at the document level (handled inside ``append``)
    and use static ISO strings (``"time": "HH:MM"``) inside entries.
    """

    _COLLECTION = "outreach_log"

    def __init__(self, project_id: str, database: str = "(default)") -> None:
        """
        Args:
            project_id: GCP project ID.
            database:   Firestore database name (defaults to "(default)").
        """
        self._client = base._make_firestore_client(project_id, database)
        self._col = self._client.collection(self._COLLECTION)

    def append(self, date_str: str, entry: dict) -> None:
        """Atomically append `entry` to today's outreach_log doc.

        Uses ``firestore.ArrayUnion([entry])`` with ``merge=True`` so
        concurrent ticks cannot clobber each other and so the doc is
        created on the first call of the day without a separate `set`.

        Args:
            date_str: YYYY-MM-DD (Israel-time calendar date — same key the
                autonomous tick uses for the current day's outreach context).
            entry:    Per-send record. Recommended shape:
                ``{"topic_key": str, "time": "HH:MM", "draft": str,
                   "final": str, "tick_index": int}``

        Raises:
            Exception: Re-raises any Firestore write failure after logging it.

        NOTE 2 — ``entry`` MUST NOT contain ``firestore.SERVER_TIMESTAMP``
        sentinels. ArrayUnion's deep-equality comparison treats each sentinel
        object as distinct, which breaks the atomic-append-without-duplicates
        semantic that the autonomous engine relies on for repeat-suppression.
        Use static ISO strings (e.g. ``"time": "14:20"``) inside entries.
        The doc-level ``updated_at`` set below is the only place
        SERVER_TIMESTAMP appears.
        """
        try:
            self._col.document(date_str).set(
                {
                    "date": date_str,
                    "entries": firestore.ArrayUnion([entry]),
                    "updated_at": firestore.SERVER_TIMESTAMP,
                },
                merge=True,
            )
        except Exception:
            logger.error("OutreachLogStore.append(%r) failed", date_str, exc_info=True)
            raise

    def get_today(self, date_str: str) -> list[dict]:
        """Return today's `entries` list. Never raises.

        Args:
            date_str: YYYY-MM-DD calendar date.

        Returns:
            The list of entry dicts. Empty list when the doc does not exist
            OR when Firestore is unreachable.
        """
        try:
            snap = self._col.document(date_str).get()
            if not snap.exists:
                return []
            data = snap.to_dict() or {}
            return list(data.get("entries") or [])
        except Exception:
            logger.warning("OutreachLogStore.get_today(%r) failed", date_str, exc_info=True)
            return []

    def topics_today(self, date_str: str) -> list[str]:
        """Return today's list of `topic_key` strings, in append order. Never raises.

        Used by the tick-brain triage prompt (D-06: informative
        repeat-suppression — Klaus is *told* what was already raised today
        but is not blocked from re-raising).

        Args:
            date_str: YYYY-MM-DD calendar date.

        Returns:
            List of `topic_key` strings. Empty list when the doc does not exist.
            Entries without a `topic_key` field are skipped silently.
        """
        entries = self.get_today(date_str)
        return [str(e.get("topic_key", "")) for e in entries if e.get("topic_key")]


class ActionLogStore:
    """Per-day audit record of every Layer-2 write action (D-25 — Phase 33).

    Schema (collection: ``action_log/{YYYY-MM-DD}``):
        date: str                   # YYYY-MM-DD (also the doc id)
        entries: list[dict]         # each entry = {id, action, detail, occasion,
                                     #   at, disclosed}
        updated_at: SERVER_TIMESTAMP  # doc-level only — set by append(), NOT
                                     # inside entries

    D-25 — deliberately NOT gated on ``send_and_inject`` success. This is the
    exact inverse of ``OutreachLogStore``'s D-10 write-after-send discipline:
    a calendar/task write Layer 2 makes gets its own audit record the moment
    the write happens, whether or not the occasion's message ever ships.
    Nothing Klaus does to Amit's calendar may stay invisible just because the
    send that would have disclosed it failed. The two logs must NEVER be
    merged — ``OutreachLogStore`` answers "what did Klaus say and when",
    ``ActionLogStore`` answers "what did Klaus DO", and mixing the two write
    disciplines into one collection would blur which invariant governs which
    write.

    Reads (``get_recent``, ``undisclosed``) never raise — they return ``[]``
    on any Firestore error so a read failure never blocks an occasion's
    compose step. Writes (``append``) re-raise after logging, matching
    ``OutreachLogStore.append`` — an action write failing silently would
    defeat the D-25 no-invisible-action guarantee. ``mark_disclosed`` never
    raises (see its own docstring for why a missed flip self-heals).

    NOTE 2 (mirrors ``OutreachLogStore``) — do NOT put
    ``firestore.SERVER_TIMESTAMP`` (or any other sentinel) inside an
    ``entry`` dict passed to ``append()``. ``ArrayUnion`` compares list
    elements by deep equality, and each ``SERVER_TIMESTAMP`` sentinel is a
    freshly allocated object, so two "same" entries with embedded sentinels
    would NEVER de-duplicate. Use a static ISO string in ``entry["at"]``
    instead; the doc-level ``updated_at`` set inside ``append()`` is the only
    place ``SERVER_TIMESTAMP`` appears.

    Entry shape (all values JSON-primitive; NEVER firestore.SERVER_TIMESTAMP
    inside)::

        {"id": "<uuid4 hex>",
         "action": "calendar_create" | "calendar_update" | "calendar_delete",
         "detail": "Upper Body, 2026-08-02 18:00",
         "occasion": "nightly" | "morning" | "weekly_review" | "tick" | "chat",
         "at": "2026-08-01T22:14:05+03:00",
         "disclosed": False}
    """

    _COLLECTION = "action_log"

    def __init__(self, project_id: str, database: str = "(default)") -> None:
        """
        Args:
            project_id: GCP project ID.
            database:   Firestore database name (defaults to "(default)").
        """
        self._client = base._make_firestore_client(project_id, database)
        self._col = self._client.collection(self._COLLECTION)

    def append(self, date_str: str, entry: dict) -> None:
        """Atomically append `entry` to `date_str`'s action_log doc.

        Unconditional — call this the moment a calendar/task write happens,
        never gated on whether the occasion's message subsequently sends
        (D-25, the deliberate inverse of ``OutreachLogStore.append``'s D-10
        write-after-send rule). Uses ``firestore.ArrayUnion([entry])`` with
        ``merge=True``, identical mechanics to ``OutreachLogStore.append``.

        Args:
            date_str: YYYY-MM-DD (Asia/Jerusalem calendar date).
            entry:    Per-action record. See the class docstring's entry shape.

        Raises:
            Exception: Re-raises any Firestore write failure after logging it.

        NOTE 2 — ``entry`` MUST NOT contain ``firestore.SERVER_TIMESTAMP``
        sentinels — see the class docstring's NOTE 2 for why (ArrayUnion
        deep-equality dedup breaks). Use a static ISO string in
        ``entry["at"]`` instead.
        """
        try:
            self._col.document(date_str).set(
                {
                    "date": date_str,
                    "entries": firestore.ArrayUnion([entry]),
                    "updated_at": firestore.SERVER_TIMESTAMP,
                },
                merge=True,
            )
        except Exception:
            logger.error("ActionLogStore.append(%r) failed", date_str, exc_info=True)
            raise

    def get_recent(self, days: int, *, today: str | None = None) -> list[dict]:
        """Return entries from the last `days` calendar days, newest-first.

        Iterates date keys backward from `today` (default: today's
        Asia/Jerusalem calendar date) rather than issuing a range query —
        this store is doc-per-date, not field-indexed, mirroring
        ``TrainingLogStore``'s date-key access pattern. Never raises: a
        per-day Firestore error is logged and that day is skipped, so one bad
        day cannot blank the whole window.

        Every returned entry is routed through ``_jsonsafe_doc`` (with its
        `date` key merged in) so a SERVER_TIMESTAMP-derived `updated_at`
        never reaches a read tool's `json.dumps` call — the same
        MealStore/TrainingLogStore trap `get_recent_decisions` (plan 33-09)
        would otherwise hit.

        Args:
            days:  How many calendar days back to look, inclusive of `today`.
            today: YYYY-MM-DD to anchor the window at. Defaults to the
                current Asia/Jerusalem calendar date.

        Returns:
            A flat list of entry dicts, each carrying its own `date` key,
            newest day first. `[]` on any top-level failure.
        """
        from datetime import date as _date, datetime as _datetime, timedelta
        from zoneinfo import ZoneInfo as _ZoneInfo

        try:
            if today is None:
                anchor = _datetime.now(_ZoneInfo("Asia/Jerusalem")).date()
            else:
                anchor = _date.fromisoformat(today)
        except Exception:
            logger.warning("ActionLogStore.get_recent(%r) bad anchor date", today, exc_info=True)
            return []

        results: list[dict] = []
        for offset in range(max(0, days)):
            d_iso = (anchor - timedelta(days=offset)).isoformat()
            try:
                snap = self._col.document(d_iso).get()
                if not snap.exists:
                    continue
                data = snap.to_dict() or {}
                for entry in data.get("entries") or []:
                    results.append(_jsonsafe_doc({**entry, "date": d_iso}))
            except Exception:
                logger.warning("ActionLogStore.get_recent day %r failed", d_iso, exc_info=True)
                continue
        return results

    def undisclosed(self, days: int = 7, *, today: str | None = None) -> list[dict]:
        """Return `get_recent(days)` entries not yet marked disclosed (D-25).

        Feeds the Layer-2 disclosure block (plan 33-04) and the heartbeat's
        undisclosed-actions anomaly check (plan 33-11, D-28 #4) — "I already
        did this but never told him". Never raises — inherits
        ``get_recent``'s fail-soft-per-day contract.

        Args:
            days:  How many calendar days back to look. Defaults to 7.
            today: YYYY-MM-DD anchor; defaults to today (Asia/Jerusalem).

        Returns:
            The subset of `get_recent(days, today=today)` whose `disclosed`
            field is not literally `True`.
        """
        return [
            entry
            for entry in self.get_recent(days, today=today)
            if entry.get("disclosed") is not True
        ]

    def mark_disclosed(self, date_str: str, action_ids: list[str]) -> None:
        """Mark the entries whose `id` is in `action_ids` as disclosed.

        Read-modify-write: ``ArrayUnion`` cannot update a list element in
        place, so this reads `date_str`'s `entries` list, sets
        `disclosed=True` on every entry whose `id` is in `action_ids`, and
        writes the whole list back with `set({"entries": [...]}, merge=True)`.

        Last-writer-wins caveat: a concurrent read-modify-write race could
        drop another caller's flip. Acceptable in practice — the D-19
        in-flight marker enforces one occasion composing at a time, so two
        concurrent callers are not expected. Never raises: a Firestore
        failure here is logged and swallowed, since a missed disclosure flip
        self-heals (the next occasion still sees the entry as undisclosed and
        discloses it again, per D-25 — nothing is lost, only re-said).

        Args:
            date_str:   YYYY-MM-DD (Asia/Jerusalem calendar date) whose doc
                holds the entries to flip.
            action_ids: `id` values (see entry shape) to mark disclosed.
        """
        try:
            snap = self._col.document(date_str).get()
            if not snap.exists:
                return
            data = snap.to_dict() or {}
            entries = list(data.get("entries") or [])
            ids = set(action_ids)
            changed = False
            for entry in entries:
                if entry.get("id") in ids and entry.get("disclosed") is not True:
                    entry["disclosed"] = True
                    changed = True
            if not changed:
                return
            self._col.document(date_str).set({"entries": entries}, merge=True)
        except Exception:
            logger.warning(
                "ActionLogStore.mark_disclosed(%r, %r) failed",
                date_str, action_ids, exc_info=True,
            )


class BehavioralFeedbackStore:
    """Provider-neutral learned-preference proposals with a durable veto path."""

    _COLLECTION = "behavioral_feedback"

    def __init__(self, project_id: str, database: str = "(default)") -> None:
        self._client = base._make_firestore_client(project_id, database)
        self._col = self._client.collection(self._COLLECTION)

    def record(
        self,
        *,
        pattern: str,
        evidence: list[str],
        source: str,
        feedback_id: str | None = None,
    ) -> dict:
        """Persist a vetoable learned preference proposal."""
        import uuid
        from datetime import datetime, timezone

        if not pattern.strip():
            raise ValueError("pattern is required")
        identifier = feedback_id or uuid.uuid4().hex
        record = {
            "id": identifier,
            "pattern": pattern,
            "evidence": [str(item) for item in evidence],
            "source": source,
            "status": "proposed",
            "veto_available": True,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        self._col.document(identifier).set(
            {**record, "updated_at": firestore.SERVER_TIMESTAMP},
        )
        return dict(record)

    def veto(self, feedback_id: str) -> None:
        """Mark feedback vetoed without deleting its training signal."""
        from datetime import datetime, timezone

        self._col.document(feedback_id).set(
            {
                "status": "vetoed",
                "vetoed_at": datetime.now(timezone.utc).isoformat(),
                "updated_at": firestore.SERVER_TIMESTAMP,
            },
            merge=True,
        )
