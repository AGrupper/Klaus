"""Time-based follow-ups and standing directives — the two ways Klaus
remembers to do something later.

Split out of memory/firestore_db.py, which re-exports everything here.
"""
from __future__ import annotations

import logging
import os
from decimal import Decimal

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


class FollowupStore:
    """Persists scheduled follow-ups for Klaus's self-managed check-backs.

    Schema (collection: ``followups/{id}``):
        id: str                # doc-id (uuid4 hex)
        due_at: str            # ISO-8601 UTC — when the follow-up fires
        note: str              # human-readable reminder text
        created_at: str        # ISO-8601 UTC — when scheduled
        status: str            # 'pending' | 'done' | 'cancelled'
        defer_count: int       # incremented each time Klaus defers; force-fire at >=3
        origin: str            # 'user_chat' (user asked) | 'klaus_self' (Klaus scheduled himself)

    Reads (`list_due`, `list_pending`) never raise — they return `[]` on
    Firestore error so the autonomous tick (Plan 06) can keep running even
    when Firestore is briefly unreachable. Writes (`add`, `mark_done`,
    `cancel`, `defer`) re-raise after logging so the caller can decide.

    Phase 18 — AUTO-04, D-12/D-13/D-14/D-15.
    """

    _COLLECTION = "followups"

    def __init__(self, project_id: str, database: str = "(default)") -> None:
        """
        Args:
            project_id: GCP project ID.
            database:   Firestore database name (defaults to "(default)").
        """
        self._client = base._make_firestore_client(project_id, database)
        self._col = self._client.collection(self._COLLECTION)

    def add(self, due_at: str, note: str, origin: str = "user_chat") -> dict:
        """Insert a new pending follow-up.

        Args:
            due_at: ISO-8601 UTC timestamp string. Caller is responsible for
                converting NL inputs to ISO via `dateutil.parser` (see Plan 02).
            note:   Human-readable reminder text.
            origin: 'user_chat' (user asked Klaus to remind them) or
                'klaus_self' (Klaus scheduled this himself mid-conversation).

        Returns:
            ``{"id": <uuid4 hex>, "due_at": <due_at>}`` so the caller can echo
            confirmation back to the user.

        Raises:
            Exception: Re-raises any Firestore write failure after logging it.
        """
        # Inline imports keep the class loadable when running unit tests that
        # mock google.cloud.firestore at the sys.modules level — matches
        # JournalStore/SelfStateStore convention in this module.
        import uuid
        from datetime import datetime, timezone

        fid = uuid.uuid4().hex
        doc = {
            "id": fid,
            "due_at": due_at,
            "note": note,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "status": "pending",
            "defer_count": 0,
            "origin": origin,
        }
        try:
            self._col.document(fid).set(doc)
        except Exception:
            logger.error("FollowupStore.add failed (note=%r)", note, exc_info=True)
            raise
        return {"id": fid, "due_at": due_at}

    def list_due(self, now_iso: str) -> list[dict]:
        """Return pending follow-ups whose `due_at <= now_iso`. Never raises.

        Used by `run_autonomous_tick` (Plan 06) every 20 min to detect
        follow-ups that should fire on this tick.

        NOTE: Firestore requires a composite index on (status, due_at) for
        this query — to be created on first deploy (documented in Plan 09
        DEPLOYMENT.md, §Firestore Composite Indexes).

        Args:
            now_iso: Current time as an ISO-8601 UTC string.

        Returns:
            List of follow-up dicts. Empty list if no docs match or Firestore
            is unreachable.
        """
        from google.cloud.firestore_v1.base_query import FieldFilter

        try:
            snaps = (
                self._col
                .where(filter=FieldFilter("status", "==", "pending"))
                .where(filter=FieldFilter("due_at", "<=", now_iso))
                .stream()
            )
            return [s.to_dict() for s in snaps]
        except Exception:
            logger.warning("FollowupStore.list_due failed", exc_info=True)
            return []

    def list_pending(self) -> list[dict]:
        """Return all status='pending' follow-ups regardless of due_at. Never raises.

        Used by the `list_followups` direct tool (Plan 02) so Klaus can show
        the user every outstanding check-back, not just the ones due now.

        Returns:
            List of follow-up dicts. Empty list on Firestore error.
        """
        from google.cloud.firestore_v1.base_query import FieldFilter

        try:
            snaps = (
                self._col
                .where(filter=FieldFilter("status", "==", "pending"))
                .stream()
            )
            return [s.to_dict() for s in snaps]
        except Exception:
            logger.warning("FollowupStore.list_pending failed", exc_info=True)
            return []

    def mark_done(self, fid: str) -> None:
        """Mark a follow-up complete. Raises on Firestore error.

        Args:
            fid: Follow-up document ID (uuid4 hex).
        """
        try:
            self._col.document(fid).update({"status": "done"})
        except Exception:
            logger.error("FollowupStore.mark_done(%r) failed", fid, exc_info=True)
            raise

    def cancel(self, fid: str) -> bool:
        """Cancel a follow-up. Idempotent — re-cancelling a cancelled doc still returns True.

        Args:
            fid: Follow-up document ID.

        Returns:
            True if the doc exists (and has been transitioned to 'cancelled');
            False only if the doc does not exist. Re-cancelling an already-
            cancelled doc returns True (D-15: cancel is idempotent).

        Raises:
            Exception: On any non-existence Firestore error (logged + re-raised).
        """
        try:
            snap = self._col.document(fid).get()
            if not snap.exists:
                return False
            self._col.document(fid).update({"status": "cancelled"})
            return True
        except Exception:
            logger.error("FollowupStore.cancel(%r) failed", fid, exc_info=True)
            raise

    def defer(self, fid: str, new_due_at: str) -> None:
        """Push the follow-up's `due_at` forward and increment `defer_count`.

        D-14: After `defer_count >= 3` the orchestrator force-fires on the
        next due tick — Klaus can't punt forever. Incrementing atomically
        via `firestore.Increment(1)` so concurrent ticks don't clobber each
        other.

        Args:
            fid:        Follow-up document ID.
            new_due_at: New ISO-8601 UTC `due_at` timestamp.

        Raises:
            Exception: Re-raises any Firestore write failure after logging it.
        """
        try:
            self._col.document(fid).update({
                "due_at": new_due_at,
                "defer_count": firestore.Increment(1),
            })
        except Exception:
            logger.error("FollowupStore.defer(%r) failed", fid, exc_info=True)
            raise


class StandingDirectiveStore:
    """Persists Amit's lasting behavioral wishes (standing directives).

    Schema (collection: ``standing_directives/{uuid4hex}``):
        id: str                    # doc-id (uuid4 hex)
        text: str                  # verbatim captured wish
        origin: str                # 'user_chat' | 'klaus_self' (D-09/D-11)
        context_quote: str         # the triggering exchange, verbatim (DIR-01/D-03)
        created_at: str            # ISO-8601 UTC
        status: str                # 'active' | 'expired' | 'cancelled' | 'superseded' | 'vetoed'
        expires_at: str | None     # ISO-8601 UTC — hard date expiry (D-05, explicit timeframe)
        condition_text: str | None # event-based expiry text (D-05, e.g. "while I'm in France")
        superseded_by: str | None  # id of the refined directive that replaced this one (D-16)

    Reads (`list_active`, `list_all`, `get`) never raise — `list_active`/`list_all`
    return `[]` and `get` returns `None` on Firestore error so every reasoning
    path (chat, tick triage, Layer-2 compose, interim crons) can keep running
    even when Firestore is briefly unreachable.
    Writes (`add`, `cancel`, `supersede`, `expire`, `veto`) re-raise after logging
    so the caller can decide. NEVER hard-delete — every mutation is a status
    transition, auditable via Firestore doc history (matches FollowupStore
    discipline).

    `list_active()` is served from the module `_READ_CACHE` (directives are read
    on every chat turn + every autonomous tick); every write method invalidates
    the `("standing_directives",)` cache prefix.

    Phase 31 — DIR-01..07.
    """

    _COLLECTION = "standing_directives"

    def __init__(self, project_id: str, database: str = "(default)") -> None:
        """
        Args:
            project_id: GCP project ID.
            database:   Firestore database name (defaults to "(default)").
        """
        self._client = base._make_firestore_client(project_id, database)
        self._col = self._client.collection(self._COLLECTION)

    def add(
        self,
        text: str,
        origin: str = "user_chat",
        context_quote: str = "",
        expires_at: str | None = None,
        condition_text: str | None = None,
    ) -> dict:
        """Insert a new active standing directive.

        Args:
            text:           Verbatim captured wish.
            origin:         'user_chat' (Amit stated it) or 'klaus_self' (reflection
                proposed it — D-09, activated immediately).
            context_quote:  The triggering exchange, verbatim (DIR-01/D-03).
            expires_at:     ISO-8601 UTC hard-date expiry, or None (D-05).
            condition_text: Event-based expiry text, or None (D-05). A directive
                with neither field set persists indefinitely (DIR-02).

        Returns:
            The full persisted doc dict.

        Raises:
            Exception: Re-raises any Firestore write failure after logging it.
        """
        # Inline imports keep the class loadable when running unit tests that
        # mock google.cloud.firestore at the sys.modules level — matches
        # FollowupStore/JournalStore convention in this module.
        import uuid
        from datetime import datetime, timezone

        did = uuid.uuid4().hex
        doc = {
            "id": did,
            "text": text,
            "origin": origin,
            "context_quote": context_quote,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "status": "active",
            "expires_at": expires_at,
            "condition_text": condition_text,
            "superseded_by": None,
        }
        try:
            self._col.document(did).set(doc)
        except Exception:
            logger.error("StandingDirectiveStore.add failed (text=%r)", text, exc_info=True)
            raise
        _cache_invalidate_prefix(("standing_directives",))
        return doc

    def list_active(self) -> list[dict]:
        """Return all status='active' directives. Never raises.

        Served from the module `_READ_CACHE` within `_READ_CACHE_TTL_SEC` —
        this is read on every chat turn and every autonomous tick.

        Returns:
            List of directive dicts. Empty list on Firestore error or cache miss
            with no active directives.
        """
        from google.cloud.firestore_v1.base_query import FieldFilter

        cache_key = ("standing_directives", "active")
        cached = _cache_get(cache_key)
        if cached is not None:
            return list(cached)
        try:
            snaps = (
                self._col
                .where(filter=FieldFilter("status", "==", "active"))
                .stream()
            )
            result = [s.to_dict() for s in snaps]
        except Exception:
            logger.warning("StandingDirectiveStore.list_active failed", exc_info=True)
            return []
        _cache_put(cache_key, list(result))
        return result

    def list_all(self) -> list[dict]:
        """Return every directive regardless of status. Never raises. Uncached —
        history reads (e.g. `list_standing_directives(include_history=True)`) are
        rare, unlike the hot `list_active()` path.

        Returns:
            List of directive dicts. Empty list on Firestore error.
        """
        try:
            snaps = self._col.stream()
            return [s.to_dict() for s in snaps]
        except Exception:
            logger.warning("StandingDirectiveStore.list_all failed", exc_info=True)
            return []

    def cancel(self, did: str) -> bool:
        """Cancel a directive. Never hard-deletes — status transition only.

        Args:
            did: Directive document ID.

        Returns:
            True if the doc exists (and has been transitioned to 'cancelled');
            False if the doc does not exist.

        Raises:
            Exception: On any Firestore error other than non-existence (logged
                + re-raised).
        """
        try:
            snap = self._col.document(did).get()
            if not snap.exists:
                return False
            self._col.document(did).update({"status": "cancelled"})
        except Exception:
            logger.error("StandingDirectiveStore.cancel(%r) failed", did, exc_info=True)
            raise
        _cache_invalidate_prefix(("standing_directives",))
        return True

    def supersede(self, old_id: str, new_directive_id: str) -> bool:
        """Mark an old directive as superseded by a refined one (DIR-05, D-16
        persona-conflict resolution).

        Args:
            old_id:           Document ID of the directive being replaced.
            new_directive_id: Document ID of the refined directive that replaces it.

        Returns:
            True if the old doc exists and was updated; False if it does not exist.

        Raises:
            Exception: On any Firestore error other than non-existence (logged
                + re-raised).
        """
        try:
            snap = self._col.document(old_id).get()
            if not snap.exists:
                return False
            self._col.document(old_id).update({
                "status": "superseded",
                "superseded_by": new_directive_id,
            })
        except Exception:
            logger.error("StandingDirectiveStore.supersede(%r, %r) failed", old_id, new_directive_id, exc_info=True)
            raise
        _cache_invalidate_prefix(("standing_directives",))
        return True

    def expire(self, did: str) -> bool:
        """Mark a directive expired (D-05/D-08 nightly-judged expiry path).

        Args:
            did: Directive document ID.

        Returns:
            True if the doc exists and was updated; False if it does not exist.

        Raises:
            Exception: On any Firestore error other than non-existence (logged
                + re-raised).
        """
        try:
            snap = self._col.document(did).get()
            if not snap.exists:
                return False
            self._col.document(did).update({"status": "expired"})
        except Exception:
            logger.error("StandingDirectiveStore.expire(%r) failed", did, exc_info=True)
            raise
        _cache_invalidate_prefix(("standing_directives",))
        return True

    def veto(self, did: str) -> bool:
        """Mark a klaus_self directive vetoed — a durable anti-lesson (D-13).

        Rejecting a self-proposed directive is training signal: the doc is
        kept forever at status='vetoed' (NEVER hard-deleted) so
        `core/reflection.py`'s ``status == "vetoed"`` guard can read it back
        and refuse to re-propose the same or near-same directive.

        Args:
            did: Directive document ID.

        Returns:
            True if the doc exists and was updated; False if it does not exist.

        Raises:
            Exception: On any Firestore error other than non-existence (logged
                + re-raised).
        """
        try:
            snap = self._col.document(did).get()
            if not snap.exists:
                return False
            self._col.document(did).update({"status": "vetoed"})
        except Exception:
            logger.error("StandingDirectiveStore.veto(%r) failed", did, exc_info=True)
            raise
        _cache_invalidate_prefix(("standing_directives",))
        return True

    def get(self, did: str) -> dict | None:
        """Return one directive doc by id, or None if absent / on error. Never raises.

        Cheap single-doc read used by the cancel handler to check `origin`
        before deciding whether to route to `veto()` or `cancel()` — avoids a
        full-collection scan for a routing decision.

        Args:
            did: Directive document ID.

        Returns:
            The jsonsafe doc dict, or None if the doc does not exist or
            Firestore errors.
        """
        try:
            snap = self._col.document(did).get()
            if not snap.exists:
                return None
            return _jsonsafe_doc(snap.to_dict() or {})
        except Exception:
            logger.warning("StandingDirectiveStore.get(%r) failed", did, exc_info=True)
            return None
