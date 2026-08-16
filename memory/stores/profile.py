"""Amit's stored profile, Klaus's own self-state, the reflection journal,
and Hub settings. SelfStateStore and HubSettingsStore deliberately share
the `config` collection.

Split out of memory/firestore_db.py, which re-exports everything here.
"""
from __future__ import annotations

import logging

from google.cloud import firestore

logger = logging.getLogger(__name__)

from memory.stores import base
from memory.stores.base import (
    _DESCENDING,
    _cache_get,
    _cache_invalidate_prefix,
    _cache_put,
)


class UserProfileStore:
    """Read/write the user's static profile + coaching plan in Firestore.

    PHASE 19 (Plan 02): filled in (was a Phase-5 stub raising NotImplementedError).
    PHASE 21 (Plan 01): _SCAFFOLD expanded to v4.0 structured-field contract.
    Mirrors SelfStateStore discipline (this module's `class SelfStateStore` below):
      - Reads NEVER raise — return {} on any error.
      - Writes (update) re-raise after logger.error, caller decides.
      - bootstrap_if_empty is a startup safety call — NEVER raises (Pitfall 7).
      - Every merge write stamps `updated_at: firestore.SERVER_TIMESTAMP`.

    Singleton document at collection='users', document='amit'.

    v4.0 structured fields (schema_version 2):
        dated_goals       (list)  — Tier A peak targets: [{target_date, goal_label, metrics}].
                                    Populated by ingest_blueprint.py. NEVER contains current
                                    performance baselines (Tier B — derived from Garmin at
                                    read time).
        weekly_split      (dict)  — Flexible AM/PM session template keyed by day name.
                                    Each day: {"am": {label, modality, priority},
                                               "pm": {label, modality, priority}}.
                                    This is a TEMPLATE, not an attendance contract.
                                    Per-session done/attendance booleans are STRUCTURALLY
                                    ABSENT — Klaus must never nag about a single missed session.
        nutrition_targets (dict)  — Daily macro targets: {protein_g, carbs_g, ...}.
        supplement_schedule (list)— Ordered supplement slots: [{slot, items}].
        fueling_timeline  (list)  — Ordered 6-slot fueling architecture: [{slot, timing, ...}].
        plan_start_date   (str)   — ISO date "2026-06-21" (Block Week 1 anchor).
                                    Phase 23 derives block/week numbers from this field.
        schema_version    (int)   — 2 (bumped from 1 at Phase 21).

    Legacy fields retained for backward compatibility:
        athletic_goals    (list)  — Read by core/weekly_training_review.py:188 (Sunday cron).
                                    Do NOT remove — removing breaks `data["athletic_goals"]`.
                                    v4.0 primary is `dated_goals`; this stays for v3.0 compat.
        training_constraints (list)  — Kept for forward-compat (may be used by future phases).
        recovery_preferences (dict)  — Kept for forward-compat.

    JSON serialization note: `updated_at` and `bootstrapped_at` are Firestore
    SERVER_TIMESTAMPs (DatetimeWithNanoseconds) — strip them before json.dumps.
    Use _jsonsafe_doc() helper or the render_smart_system non_empty filter.
    """

    _COLLECTION = "users"
    _DOCUMENT_ID = "amit"
    _SCAFFOLD = {
        # v4.0 structured fields (primary coaching reference — Tier A targets only)
        "dated_goals": [],            # [{target_date, goal_label, metrics}] — Oct/Nov peaks
        "weekly_split": {},           # {day: {am: {label, modality, priority}, pm: {...}}}
                                      # Template shape — NO attendance/done/completed booleans
        "nutrition_targets": {},      # {protein_g, carbs_g, ...} daily macro targets
        "supplement_schedule": [],    # [{slot, items}] ordered supplement list
        "fueling_timeline": [],       # [{slot, timing, content, notes}] 6-slot fueling arch
        "plan_start_date": "",        # "2026-06-21" — Block Week 1 anchor for Phase 23
        "schema_version": 2,          # bumped from 1 → 2 at Phase 21
        # Phase 23 — block tracking FK
        "current_block_id": None,     # FK → training_blocks doc id (primed by seed_training_blocks.py)
        # Phase 26 — v5.0 Klaus Hub auth fields
        "session_version": 0,         # bumped by /api/auth/revoke-all (D-02); invalidates all session cookies
        "telegram_user_id": None,     # Amit's Telegram user_id; hub keys FirestoreConversationStore on this (RESEARCH Open Question 2)
        # Legacy fields — retained for backward compatibility
        "athletic_goals": [],         # read by weekly_training_review.py:188 — do NOT remove
        "training_constraints": [],   # kept for forward-compat
        "recovery_preferences": {},   # kept for forward-compat
    }

    def __init__(self, project_id: str, database: str = "(default)") -> None:
        self._client = base._make_firestore_client(project_id, database)
        self._doc_ref = (
            self._client.collection(self._COLLECTION).document(self._DOCUMENT_ID)
        )
        self._cache_key = ("user_profile", project_id, database)

    def load(self) -> dict:
        """PROFILE-01: return the user profile dict. Returns {} on any error — never raises.

        Served from the module TTL cache between writes — the profile changes
        rarely but is read on chat turns and coaching prompts (BRAIN-07).
        """
        cache_key = getattr(self, "_cache_key", None)
        if cache_key is not None:
            cached = _cache_get(cache_key)
            if cached is not None:
                return dict(cached)
        try:
            snap = self._doc_ref.get()
            result = snap.to_dict() or {} if snap.exists else {}
        except Exception:
            logger.warning("UserProfileStore.load() failed — returning empty", exc_info=True)
            return {}
        if cache_key is not None:
            _cache_put(cache_key, dict(result))
        return result

    def update(self, patch: dict) -> None:
        """PROFILE-02: merge patch and stamp updated_at SERVER_TIMESTAMP. Re-raises on failure.

        Invalidates the read cache on the success path so a same-instance
        load() never serves the pre-write value.
        """
        try:
            self._doc_ref.set(
                {**patch, "updated_at": firestore.SERVER_TIMESTAMP},
                merge=True,
            )
        except Exception:
            logger.error("UserProfileStore.update() failed", exc_info=True)
            raise
        cache_key = getattr(self, "_cache_key", None)
        if cache_key is not None:
            _cache_invalidate_prefix(cache_key)

    def bootstrap_if_empty(self) -> None:
        """PROFILE-03: seed users/amit with empty scaffold if absent.

        Safe to call on every startup — only writes when the document is absent.
        Never raises (Pitfall 7: startup must not fail due to Firestore unavailability).
        """
        try:
            snap = self._doc_ref.get()
            if snap.exists:
                return
            self._doc_ref.set({
                **self._SCAFFOLD,
                "bootstrapped_at": firestore.SERVER_TIMESTAMP,
                "updated_at": firestore.SERVER_TIMESTAMP,
            })
            logger.info("UserProfileStore: bootstrapped users/amit")
        except Exception:
            logger.warning(
                "UserProfileStore.bootstrap_if_empty() failed — skipping",
                exc_info=True,
            )


class SelfStateStore:
    """Persistent self-model state stored in Firestore.

    Singleton document at collection='config', document='self_state'.
    Fields: identity_summary (str), current_focus (str), recent_context (str),
            mood (str), updated_at (timestamp), bootstrapped_at (timestamp).

    Phase 16: only identity_summary is populated (seeded from SELF.md intro paragraph
    on first startup). current_focus, recent_context, mood are empty strings until
    Phase 17 run_reflection() populates them.
    """

    _COLLECTION = "config"
    _DOCUMENT = "self_state"

    def __init__(self, project_id: str, database: str = "(default)") -> None:
        self._client = base._make_firestore_client(project_id, database)
        self._doc_ref = self._client.collection(self._COLLECTION).document(self._DOCUMENT)
        self._cache_key = ("self_state", project_id, database)

    def get(self) -> dict:
        """Return the self_state document. Returns {} on any error — never raises.

        A failure must never crash a retained status read. Served from the module
        TTL cache between writes because self_state changes infrequently.
        """
        cache_key = getattr(self, "_cache_key", None)
        if cache_key is not None:
            cached = _cache_get(cache_key)
            if cached is not None:
                return dict(cached)
        try:
            snap = self._doc_ref.get()
            result = snap.to_dict() or {} if snap.exists else {}
        except Exception:
            logger.warning("SelfStateStore.get() failed — returning empty", exc_info=True)
            return {}
        if cache_key is not None:
            _cache_put(cache_key, dict(result))
        return result

    def set(self, patch: dict) -> None:
        """Merge patch into the self_state document. Raises on failure (caller decides).

        Always appends updated_at SERVER_TIMESTAMP. Invalidates the read cache
        so a same-instance get() never serves the pre-write value.
        """
        try:
            self._doc_ref.set(
                {**patch, "updated_at": firestore.SERVER_TIMESTAMP},
                merge=True,
            )
        except Exception:
            logger.error("SelfStateStore.set() failed", exc_info=True)
            raise
        cache_key = getattr(self, "_cache_key", None)
        if cache_key is not None:
            _cache_invalidate_prefix(cache_key)

    def bootstrap_if_empty(self, identity_summary: str) -> None:
        """Seed config/self_state with identity_summary if the document does not exist.

        Safe to call on every startup — only writes when the document is absent.
        Never raises (startup must not fail due to Firestore unavailability).
        """
        try:
            snap = self._doc_ref.get()
            if snap.exists:
                return
            self._doc_ref.set({
                "identity_summary": identity_summary,
                "current_focus": "",
                "recent_context": "",
                "mood": "",
                "bootstrapped_at": firestore.SERVER_TIMESTAMP,
                "updated_at": firestore.SERVER_TIMESTAMP,
            })
            logger.info("SelfStateStore: bootstrapped config/self_state")
            cache_key = getattr(self, "_cache_key", None)
            if cache_key is not None:
                _cache_invalidate_prefix(cache_key)
        except Exception:
            logger.warning("SelfStateStore.bootstrap_if_empty() failed — skipping", exc_info=True)


class JournalStore:
    """Daily reflection journal stored in Firestore.

    Collection: journal
    Document ID: YYYY-MM-DD (Asia/Jerusalem calendar date).

    Each doc stores the 5 LLM reflection fields (summary, mood,
    current_focus, recent_context, highlights) plus the raw gathered
    metrics for auditability (message_count, cost_usd,
    calendar_event_count, tasks_completed, heartbeat_ok).

    Unlike SelfStateStore.set (which uses merge=True to patch), JournalStore.set
    uses .set() WITHOUT merge=True — each reflection run overwrites the whole doc
    so a re-run with fewer fields leaves no stale keys (D-12 idempotency).
    """

    _COLLECTION = "journal"

    def __init__(self, project_id: str, database: str = "(default)") -> None:
        self._client = base._make_firestore_client(project_id, database)
        self._col = self._client.collection(self._COLLECTION)
        self._cache_key = ("journal", project_id, database)

    def get(self, date_str: str) -> dict | None:
        """Return the journal doc for a date, or None. Never raises.

        Served from the module TTL cache between writes — the autonomous tick
        reads 3 journal days on every tick (43x/day) for entries that change
        once a day.

        Args:
            date_str: YYYY-MM-DD date key (Asia/Jerusalem calendar date).

        Returns:
            Dict with all stored fields plus ``date`` == date_str, or None
            if no entry exists for that date or if Firestore is unreachable.
        """
        cache_key = getattr(self, "_cache_key", None)
        full_key = cache_key + ("get", date_str) if cache_key is not None else None
        if full_key is not None:
            cached = _cache_get(full_key)
            if cached is not None:
                return dict(cached)
        try:
            snap = self._col.document(date_str).get()
            if not snap.exists:
                # WHY no caching of misses: today's entry appears at the
                # nightly reflection — caching the miss would hide it for up
                # to the TTL right after it's written by another instance.
                return None
            data = snap.to_dict() or {}
            data["date"] = snap.id
        except Exception:
            logger.warning("JournalStore.get(%r) failed", date_str, exc_info=True)
            return None
        if full_key is not None:
            _cache_put(full_key, dict(data))
        return data

    def set(self, date_str: str, entry: dict) -> None:
        """Overwrite the journal doc for a date. Raises on failure (caller decides).

        Uses .set() WITHOUT merge=True so a re-run for the same date replaces
        the entire document — no stale keys from an earlier run survive (D-12).
        Always appends ``date`` and ``updated_at`` SERVER_TIMESTAMP.

        Args:
            date_str: YYYY-MM-DD date key.
            entry:    Full journal entry dict (5 LLM fields + 5 raw metrics).

        Raises:
            Exception: Re-raises any Firestore write failure after logging it.
        """
        try:
            self._col.document(date_str).set(
                {**entry, "date": date_str, "updated_at": firestore.SERVER_TIMESTAMP}
            )
        except Exception:
            logger.error("JournalStore.set(%r) failed", date_str, exc_info=True)
            raise
        # Invalidate every cached journal read (per-date gets + recents).
        cache_key = getattr(self, "_cache_key", None)
        if cache_key is not None:
            _cache_invalidate_prefix(cache_key)

    def get_recent(self, n: int) -> list[dict]:
        """Return the most-recent n journal docs, newest-first. Returns [] on error.

        Orders by document ID (``__name__`` — the YYYY-MM-DD date itself) with
        a server-side limit, so only n docs are read instead of the lifetime
        collection. Ordering by doc ID rather than the ``date`` field also
        covers any legacy doc written before the field existed.

        Args:
            n: Maximum number of entries to return.

        Returns:
            List of journal dicts (each with a ``date`` field), sorted by date
            descending, at most n elements. Empty list on any Firestore error.
        """
        cache_key = getattr(self, "_cache_key", None)
        full_key = cache_key + ("recent", n) if cache_key is not None else None
        if full_key is not None:
            cached = _cache_get(full_key)
            if cached is not None:
                return [dict(d) for d in cached]
        try:
            query = self._col.order_by("__name__", direction=_DESCENDING).limit(n)
            snaps = list(query.stream())
        except Exception:
            logger.warning("JournalStore.get_recent failed", exc_info=True)
            return []
        results = []
        for snap in snaps:
            data = snap.to_dict() or {}
            data["date"] = snap.id
            results.append(data)
        if full_key is not None:
            _cache_put(full_key, [dict(d) for d in results])
        return results


class HubSettingsStore:
    """Retained Hub and Web Push settings state.

    Config doc lives at collection='config', document='hub_settings'. Historical
    fields remain in Firestore but are not read or written here.
    """

    _COLLECTION = "config"
    _DOCUMENT = "hub_settings"

    _DEFAULTS: dict = {
        "push_enabled_at": None,
    }

    def __init__(self, project_id: str, database: str = "(default)") -> None:
        self._client = base._make_firestore_client(project_id, database)
        self._doc_ref = self._client.collection(self._COLLECTION).document(self._DOCUMENT)

    def get(self) -> dict:
        """Return hub settings, falling back to defaults for missing fields.

        Never raises — returns defaults on any Firestore error.
        """
        try:
            snap = self._doc_ref.get()
            stored = snap.to_dict() or {} if snap.exists else {}
        except Exception:
            logger.warning("HubSettingsStore.get() failed — using defaults", exc_info=True)
            stored = {}
        return {**self._DEFAULTS, **stored}

    def set(self, patch: dict) -> None:
        """Merge `patch` into the stored settings document (creates it if absent)."""
        try:
            self._doc_ref.set(
                {**patch, "updated_at": firestore.SERVER_TIMESTAMP},
                merge=True,
            )
        except Exception:
            logger.error("HubSettingsStore.set() failed", exc_info=True)
            raise
