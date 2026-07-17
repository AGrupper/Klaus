"""Firestore-backed state storage.

One store class (per `docs/TECHNICAL_PLAN.md` §1 and §3.4):

1. `UserProfileStore` — read/write static user configuration (stub, Phase 5).

Note: FirestoreQueue (the Things 3 task queue) was removed when the task backend
was migrated to TickTick Open API (see mcp_tools/ticktick_tool.py).
"""
from __future__ import annotations

import logging
import os
from decimal import Decimal

from dotenv import load_dotenv
from google.cloud import firestore
from google.api_core.exceptions import GoogleAPICallError

logger = logging.getLogger(__name__)


def _where(query, field: str, op: str, value):
    """Apply a server-side filter to a collection/query.

    Prefers the keyword ``filter=FieldFilter(...)`` form (the positional
    ``where(field, op, value)`` form is deprecated in google-cloud-firestore),
    falling back to positional if the FieldFilter import is unavailable.

    WHY server-side: the read paths previously streamed entire collections
    and filtered in Python — O(lifetime docs) billed reads per call. A range
    filter + order_by on the same single field uses Firestore's automatic
    indexes (no composite index needed).
    """
    try:
        from google.cloud.firestore_v1.base_query import FieldFilter
        return query.where(filter=FieldFilter(field, op, value))
    except ImportError:
        return query.where(field, op, value)


# Sort-direction constant for order_by. The client library's
# firestore.Query.DESCENDING is literally this string; using the literal keeps
# the query builders independent of the (test-mocked) firestore module object.
_DESCENDING = "DESCENDING"


# ------------------------------------------------------------------ #
# In-process TTL read cache (self_state + journal)                    #
#                                                                     #
# self_state and journal change ~once a day but are read on every     #
# chat turn (render_smart_system) and 4x per autonomous tick          #
# (43 ticks/day) — hundreds of identical Firestore reads daily.       #
# In-process writers (reflection / nightly review) go through set()   #
# which invalidates, so same-instance staleness is zero; cross-       #
# instance staleness is bounded by the TTL, acceptable for fields     #
# that change once a day. Stores built via __new__ in tests have no   #
# _cache_key attribute and bypass the cache entirely.                 #
# ------------------------------------------------------------------ #

_READ_CACHE: dict[tuple, tuple[float, object]] = {}
_READ_CACHE_TTL_SEC = 600  # 10 minutes


def _cache_get(key: tuple):
    """Return the cached value for key, or None if absent/expired."""
    import time
    hit = _READ_CACHE.get(key)
    if hit is None:
        return None
    stored_at, value = hit
    if time.monotonic() - stored_at > _READ_CACHE_TTL_SEC:
        _READ_CACHE.pop(key, None)
        return None
    return value


def _cache_put(key: tuple, value) -> None:
    import time
    _READ_CACHE[key] = (time.monotonic(), value)


def _cache_invalidate_prefix(prefix: tuple) -> None:
    """Drop every cache entry whose key starts with prefix."""
    for key in [k for k in _READ_CACHE if k[: len(prefix)] == prefix]:
        _READ_CACHE.pop(key, None)


def _make_firestore_client(project_id: str, database: str) -> firestore.Client:
    """Return an authenticated Firestore client.

    Uses a service-account key file when FIRESTORE_CREDENTIALS is set;
    falls back to gcloud application-default credentials otherwise.
    """
    credentials_path = os.getenv("FIRESTORE_CREDENTIALS")
    if credentials_path:
        from google.oauth2 import service_account
        credentials = service_account.Credentials.from_service_account_file(
            credentials_path,
            scopes=["https://www.googleapis.com/auth/datastore"],
        )
        return firestore.Client(
            project=project_id, credentials=credentials, database=database
        )
    return firestore.Client(project=project_id, database=database)


def record_cron_run(job_id: str, ok: bool, *, backlog_done: bool | None = None) -> None:
    """Write a liveness ledger entry to heartbeat_runs/{job_id}.

    Called once per cron-endpoint invocation. On success, consecutive_failures
    is reset to 0; on failure it is incremented. Never raises.

    Args:
        job_id:       Stable identifier for the cron job (e.g. "ingest-chats").
        ok:           True if the endpoint succeeded, False on exception.
        backlog_done: For batch-processing pipelines: True when the backlog is
                      fully drained (no remaining work), False when items were
                      processed but more remain. None for non-batch crons.
                      When True, the heartbeat suppresses staleness alerts — the
                      pipeline has nothing to do and doesn't need to run again
                      until new work appears.
    """
    try:
        from datetime import datetime, timezone
        project_id = os.environ["GCP_PROJECT_ID"]
        database = os.getenv("FIRESTORE_DATABASE", "(default)")
        client = _make_firestore_client(project_id, database)
        payload = {
            "job_id": job_id,
            "last_run_at": datetime.now(timezone.utc),
            "last_ok": ok,
        }
        if ok:
            payload["consecutive_failures"] = 0
            payload["last_ok_at"] = datetime.now(timezone.utc)
        else:
            payload["consecutive_failures"] = firestore.Increment(1)
        if backlog_done is not None:
            payload["backlog_done"] = backlog_done
        client.collection("heartbeat_runs").document(job_id).set(payload, merge=True)
    except Exception:
        logger.warning("record_cron_run(%s, ok=%s) failed", job_id, ok, exc_info=True)


def increment_fallback_counter() -> None:
    """Increment today's Gemini->Haiku fallback counter in heartbeat_metrics. Never raises."""
    try:
        from datetime import date
        project_id = os.environ["GCP_PROJECT_ID"]
        database = os.getenv("FIRESTORE_DATABASE", "(default)")
        client = _make_firestore_client(project_id, database)
        today = date.today().isoformat()
        client.collection("heartbeat_metrics").document(today).set(
            {"date": today, "fallback_count": firestore.Increment(1)}, merge=True)
    except Exception:
        logger.warning("increment_fallback_counter failed", exc_info=True)


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
        self._client = _make_firestore_client(project_id, database)
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


_HEARTBEAT_CONFIG_DEFAULTS: dict = {
    "enabled": True,
    "quiet_start": "22:00",
    "quiet_end": "07:00",
    "timezone": "Asia/Jerusalem",
    "digest_hour": 9,
    "weekly_digest_day": 1,
    "reping_interval_hours": 24,
}


class HeartbeatConfigStore:
    """Read/write heartbeat scheduler config stored in Firestore.

    Config doc lives at collection='config', document='heartbeat'.
    If the document is absent, defaults are returned without writing them.
    """

    _COLLECTION = "config"
    _DOCUMENT = "heartbeat"

    def __init__(self, project_id: str, database: str = "(default)") -> None:
        self._client = _make_firestore_client(project_id, database)
        self._doc_ref = self._client.collection(self._COLLECTION).document(self._DOCUMENT)

    def get(self) -> dict:
        """Return the heartbeat config, falling back to defaults for missing fields."""
        try:
            snap = self._doc_ref.get()
            stored = snap.to_dict() or {} if snap.exists else {}
        except GoogleAPICallError:
            logger.warning("HeartbeatConfigStore.get() failed — using defaults")
            stored = {}
        return {**_HEARTBEAT_CONFIG_DEFAULTS, **stored}

    def set(self, patch: dict) -> None:
        """Merge `patch` into the stored config document (creates it if absent)."""
        try:
            self._doc_ref.set(
                {**patch, "updated_at": firestore.SERVER_TIMESTAMP},
                merge=True,
            )
        except GoogleAPICallError:
            logger.error("HeartbeatConfigStore.set() failed")
            raise


class IncidentStore:
    """Dedup and escalation tracking for heartbeat signals.

    Firestore collection: heartbeat_incidents
    Document id: signal fingerprint (colons are legal; slashes replaced with underscores).
    """

    _COLLECTION = "heartbeat_incidents"

    def __init__(self, project_id: str, database: str = "(default)") -> None:
        self._client = _make_firestore_client(project_id, database)
        self._col = self._client.collection(self._COLLECTION)

    @staticmethod
    def _should_ping(doc: dict | None, *, reping_interval_hours: int) -> bool:
        """Return True if this incident should trigger a ping.

        True when: doc is None (new incident) or last_pinged is older than reping_interval_hours.
        """
        if doc is None:
            return True
        last_pinged = doc.get("last_pinged")
        if last_pinged is None:
            return True
        from datetime import datetime, timezone, timedelta
        now = datetime.now(timezone.utc)
        if last_pinged.tzinfo is None:
            last_pinged = last_pinged.replace(tzinfo=timezone.utc)
        return (now - last_pinged) >= timedelta(hours=reping_interval_hours)

    def record_open(self, signal, *, reping_interval_hours: int) -> bool:
        """Upsert an open incident. Returns True if a ping should be sent."""
        from datetime import datetime, timezone
        doc_id = signal.fingerprint.replace("/", "_")
        doc_ref = self._col.document(doc_id)
        try:
            snap = doc_ref.get()
            existing = snap.to_dict() if snap.exists else None
        except Exception:
            existing = None
        should_ping = self._should_ping(existing, reping_interval_hours=reping_interval_hours)
        now = datetime.now(timezone.utc)
        payload: dict = {
            "fingerprint": signal.fingerprint,
            "severity": signal.severity,
            "title": signal.title,
            "status": "open",
            "last_seen": now,
        }
        if existing is None:
            payload["first_seen"] = now
        if should_ping:
            payload["last_pinged"] = now
        try:
            doc_ref.set(payload, merge=True)
        except Exception:
            logger.warning("IncidentStore.record_open failed for %s", signal.fingerprint, exc_info=True)
        return should_ping

    def resolve_absent(self, active_fingerprints: set) -> list[dict]:
        """Mark resolved any open incidents whose fingerprint is not in active_fingerprints."""
        from datetime import datetime, timezone
        from google.cloud.firestore_v1.base_query import FieldFilter
        resolved = []
        try:
            snaps = self._col.where(filter=FieldFilter("status", "==", "open")).stream()
            for snap in snaps:
                data = snap.to_dict() or {}
                if data.get("fingerprint") not in active_fingerprints:
                    now = datetime.now(timezone.utc)
                    snap.reference.set({"status": "resolved", "resolved_at": now}, merge=True)
                    resolved.append(data)
        except Exception:
            logger.warning("IncidentStore.resolve_absent failed", exc_info=True)
        return resolved


class LLMUsageStore:
    """Per-day LLM usage accounting stored in Firestore.

    Collection: llm_usage
    Document ID: YYYY-MM-DD (one doc per day)

    Each doc accumulates atomic counters for every call recorded that day.
    Numeric fields use firestore.Increment so concurrent calls are safe.

    Schema (all fields are firestore.Increment targets):
        total_in_tokens:         int   — sum of input tokens across all calls
        total_out_tokens:        int   — sum of output tokens across all calls
        total_cost_usd:          float — sum of compute_cost() results
        call_count:              int   — total number of calls
        {purpose}_calls:         int   — per-purpose call counter (e.g. "smart_calls", "worker_calls")
        total_cache_read_tokens: int   — sum of cache-read tokens across all calls (BRAIN-02)
        total_cache_write_tokens:int   — sum of cache-write tokens across all calls (BRAIN-02)
        {purpose}_cost_usd:      float — per-purpose cost driver (e.g. "smart_cost_usd") — feeds
                                  the daily cost tripwire's "top 2-3 cost drivers by purpose" (BRAIN-04)
    """

    _COLLECTION = "llm_usage"

    def __init__(self, project_id: str, database: str = "(default)") -> None:
        self._client = _make_firestore_client(project_id, database)

    def record(self, model: str, purpose: str, in_tokens: int,
               out_tokens: int, cost: float, cache_read_tokens: int = 0,
               cache_write_tokens: int = 0) -> None:
        """Increment today's usage doc. Never raises.

        cache_read_tokens/cache_write_tokens default to 0 so existing
        5-positional-arg callers keep working unchanged.
        """
        try:
            from datetime import date
            today = date.today().isoformat()
            doc_ref = self._client.collection(self._COLLECTION).document(today)
            purpose_key = f"{purpose}_calls" if purpose else "unknown_calls"
            cost_key = f"{purpose}_cost_usd" if purpose else "unknown_cost_usd"
            doc_ref.set(
                {
                    "date": today,
                    "total_in_tokens":  firestore.Increment(in_tokens),
                    "total_out_tokens": firestore.Increment(out_tokens),
                    "total_cost_usd":   firestore.Increment(cost),
                    "call_count":       firestore.Increment(1),
                    purpose_key:        firestore.Increment(1),
                    "total_cache_read_tokens":  firestore.Increment(cache_read_tokens),
                    "total_cache_write_tokens": firestore.Increment(cache_write_tokens),
                    cost_key:           firestore.Increment(cost),
                },
                merge=True,
            )
        except Exception:
            logger.warning("LLMUsageStore.record() failed", exc_info=True)

    def summary(self, period: str = "today") -> dict:
        """Return usage summary for 'today' or 'month'. Returns {} on error."""
        try:
            from datetime import date
            today = date.today()

            if period == "today":
                snap = self._client.collection(self._COLLECTION).document(
                    today.isoformat()
                ).get()
                return snap.to_dict() or {} if snap.exists else {}

            if period == "month":
                prefix = today.strftime("%Y-%m-")
                # Query docs where date starts with current year-month
                from google.cloud.firestore_v1.base_query import FieldFilter
                snaps = self._client.collection(self._COLLECTION).where(
                    filter=FieldFilter("date", ">=", prefix + "01")
                ).where(
                    filter=FieldFilter("date", "<=", prefix + "31")
                ).stream()
                agg: dict = {"call_count": 0, "total_cost_usd": 0.0,
                             "total_in_tokens": 0, "total_out_tokens": 0}
                for snap in snaps:
                    d = snap.to_dict() or {}
                    agg["call_count"]       += d.get("call_count", 0)
                    agg["total_cost_usd"]   += d.get("total_cost_usd", 0.0)
                    agg["total_in_tokens"]  += d.get("total_in_tokens", 0)
                    agg["total_out_tokens"] += d.get("total_out_tokens", 0)
                return agg

            logger.warning("LLMUsageStore.summary: unknown period '%s'", period)
            return {}
        except Exception:
            logger.warning("LLMUsageStore.summary() failed", exc_info=True)
            return {}

    def summary_for_date(self, date_str: str) -> dict:
        """Return the usage doc for an arbitrary YYYY-MM-DD date.

        Used by the daily cost tripwire (BRAIN-04) to read "yesterday"'s
        spend and per-purpose cost drivers. Returns {} if the doc is absent
        or on any Firestore error — never raises.
        """
        try:
            snap = self._client.collection(self._COLLECTION).document(date_str).get()
            return snap.to_dict() or {} if snap.exists else {}
        except Exception:
            logger.warning("LLMUsageStore.summary_for_date() failed", exc_info=True)
            return {}


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
        self._client = _make_firestore_client(project_id, database)
        self._doc_ref = self._client.collection(self._COLLECTION).document(self._DOCUMENT)
        self._cache_key = ("self_state", project_id, database)

    def get(self) -> dict:
        """Return the self_state document. Returns {} on any error — never raises.

        This is intentionally broader than HeartbeatConfigStore.get() because
        SelfStateStore is injected into every prompt; a failure must never crash
        a conversation. Served from the module TTL cache between writes —
        self_state changes ~once a day but is read on every chat turn and
        autonomous tick.
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
        self._client = _make_firestore_client(project_id, database)
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


def _is_newer(candidate, incumbent) -> bool:
    """True if ``candidate`` is a strictly newer updated_at than ``incumbent``.

    Tolerates ``None`` (treated as oldest) and any comparable timestamp type
    (Firestore ``DatetimeWithNanoseconds`` or ``datetime``). On an
    incomparable pair (e.g. tz-aware vs naive) it returns False so the
    first-seen doc is kept — a stable, deterministic tie-break. Used by
    :meth:`MealStore.get_day` to pick the latest of a duplicate set.
    """
    if candidate is None:
        return False
    if incumbent is None:
        return True
    try:
        return candidate > incumbent
    except TypeError:
        return False


class MealStore:
    """Per-date nutrition log persistence (Phase 19 — NUTR-02).

    Firestore path: ``meals/{YYYY-MM-DD}/timestamps/{source_id}``.

    The date-partitioned layout matches JournalStore's discipline (one
    document per calendar day) but uses a sub-collection of meal entries
    rather than a single doc — Lifesum can log many meals per day and
    each must round-trip through Fit + this store independently.

    Idempotency:
        ``source_id`` is the per-sample stable id the meal normalizer emits
        (currently ``healthkit:{uuid}`` from ``mcp_tools/healthkit_tool``).
        Re-syncs land on the same doc with ``merge=True``, so Lifesum
        sync-timing variance cannot produce duplicate rows (Pitfall 2 mitigation).

    Pitfall 4:
        ``get_day_aggregate`` returns ``{}`` (an EMPTY DICT) when no meals
        are logged for the date — NOT ``{"meal_count": 0}``. The Plan 19-04
        morning briefing uses truthiness on the return value to decide
        between silent-omit and rendering the nutrition section; a
        non-empty placeholder would break silent-omit.
    """

    _COLLECTION = "meals"

    def __init__(self, project_id: str, database: str = "(default)") -> None:
        self._client = _make_firestore_client(project_id, database)
        self._col = self._client.collection(self._COLLECTION)

    def upsert(self, source_id: str, meal: dict) -> None:
        """Idempotent on source_id. Re-raises on Firestore failure (caller decides).

        The meal dict's ``timestamp`` field (ISO-8601) drives the date-bucket
        document — slicing the first 10 chars yields ``YYYY-MM-DD``. The
        full meal payload is written with ``merge=True`` plus a server-side
        ``updated_at`` stamp; ``source_id`` is also written into the payload
        for easier downstream querying.

        Args:
            source_id: the per-sample stable id from the meal normalizer
                       (e.g. ``healthkit:{uuid}``).
            meal:      Normalized meal dict (see mcp_tools/healthkit_tool).

        Raises:
            Exception: re-raises any Firestore write failure after logging.
        """
        try:
            date_str = meal["timestamp"][:10]
            (
                self._col.document(date_str)
                .collection("timestamps")
                .document(source_id)
                .set(
                    {
                        **meal,
                        "source_id": source_id,
                        "updated_at": firestore.SERVER_TIMESTAMP,
                    },
                    merge=True,
                )
            )
        except Exception:
            logger.error("MealStore.upsert(%r) failed", source_id, exc_info=True)
            raise

    def get_day(self, date_str: str) -> list[dict]:
        """Return all meals for a date, sorted by timestamp ascending.

        Never raises — returns ``[]`` on any Firestore error so callers
        (e.g. the morning briefing) can degrade gracefully.

        Args:
            date_str: ``YYYY-MM-DD`` (Asia/Jerusalem calendar date).

        Returns:
            List of meal dicts, ordered by ``timestamp`` ascending. ``[]``
            when the date has no entries OR Firestore is unreachable.
        """
        try:
            snaps = self._col.document(date_str).collection("timestamps").stream()
            # De-duplicate re-synced meals (2026-06-09 fix). The iOS Shortcut
            # re-sends the day on every Lifesum close; before the source_id fix
            # a meal-time whose calorie total changed between syncs produced
            # several docs (e.g. lunch stored as both 1177 and 1180 kcal),
            # inflating daily totals. Collapse docs that share the same
            # (timestamp, source) — the duplicate signature — keeping the
            # most-recently-written one (max updated_at). This corrects totals
            # for days that accumulated duplicates BEFORE the source_id fix,
            # with no mutation of stored data. Google-Fit meals have unique
            # nanosecond timestamps, so they never collapse.
            best: dict[tuple, dict] = {}
            for s in snaps:
                d = s.to_dict() or {}
                # updated_at is the Firestore server-write stamp
                # (DatetimeWithNanoseconds). Use it to pick the latest of a
                # duplicate set, then strip it: it is not json-serializable and
                # would break downstream json.dumps (fetch_recent_meals tool +
                # autonomous triage snapshot); it is write-metadata, not meal data.
                updated_at = d.pop("updated_at", None)
                key = (d.get("timestamp", ""), d.get("source"))
                prev = best.get(key)
                if prev is None or _is_newer(updated_at, prev[0]):
                    best[key] = (updated_at, d)
            meals = [d for _, d in best.values()]
            return sorted(meals, key=lambda d: d.get("timestamp", ""))
        except Exception:
            logger.warning("MealStore.get_day(%r) failed", date_str, exc_info=True)
            return []

    def get_day_aggregate(self, date_str: str) -> dict:
        """Return totals + per-meal-type breakdown + biggest_gap_minutes.

        Used by the Plan 19-04 morning briefing (NUTR-07 silent-omit gate)
        and the autonomous-tick gather (NUTR-04 nudge logic).

        Returns ``{}`` (empty dict) when no meals are logged on ``date_str``
        — Pitfall 4 contract. Callers MUST use truthiness checks
        (``if agg: ...``) rather than key lookups, or silent-omit breaks.

        Args:
            date_str: ``YYYY-MM-DD`` (Asia/Jerusalem calendar date).

        Returns:
            ``{}`` when no meals; else::

                {
                    "meal_count":           int,
                    "totals":               {"calories": int, "protein_g": int, ...},
                    "by_type":              {1: count_of_meal_type_1, ...},
                    "biggest_gap_minutes":  float (rounded to 1 dp),
                    "meals":                ordered list (asc by timestamp),
                }
        """
        import collections
        from datetime import datetime as _dt

        meals = self.get_day(date_str)
        if not meals:
            # Pitfall 4 — silent-omit gate. DO NOT change to {"meal_count": 0}.
            return {}

        totals = {
            "calories":  sum(m.get("calories")  or 0 for m in meals),
            "protein_g": sum(m.get("protein_g") or 0 for m in meals),
            "carbs_g":   sum(m.get("carbs_g")   or 0 for m in meals),
            "fat_g":     sum(m.get("fat_g")     or 0 for m in meals),
            "fiber_g":   sum(m.get("fiber_g")   or 0 for m in meals),  # Phase 19.2
        }
        by_type: dict = collections.defaultdict(list)
        for m in meals:
            by_type[m.get("meal_type", 1)].append(m)

        biggest_gap_minutes = 0.0
        for i in range(1, len(meals)):
            try:
                t_prev = _dt.fromisoformat(meals[i - 1]["timestamp"])
                t_curr = _dt.fromisoformat(meals[i]["timestamp"])
                gap = (t_curr - t_prev).total_seconds() / 60.0
                if gap > biggest_gap_minutes:
                    biggest_gap_minutes = gap
            except (KeyError, ValueError, TypeError):
                # Malformed timestamp on one entry → skip that pair.
                continue

        return {
            "meal_count":          len(meals),
            "totals":              totals,
            "by_type":             {k: len(v) for k, v in by_type.items()},
            "biggest_gap_minutes": round(biggest_gap_minutes, 1),
            "meals":               meals,  # ordered — prompt may render breakdown
        }


def _jsonsafe_doc(d: dict) -> dict:
    """Return a copy of a Firestore doc dict with non-JSON-serialisable values
    coerced to strings, so the result round-trips through ``json.dumps``.

    ``log_session`` stamps ``updated_at`` with ``firestore.SERVER_TIMESTAMP``,
    which reads back as a ``DatetimeWithNanoseconds`` — ``json.dumps`` raises on
    it. ``get_training_history`` json-encodes its result, so the timestamp is
    converted to ISO-8601 here (any other datetime-like value is handled too).
    """
    return {k: _jsonsafe_value(v) for k, v in d.items()}


def _jsonsafe_value(v):
    """Coerce a single value to a JSON-serialisable form, recursing into nested
    dicts and lists. The v4.0 user profile (Phase 21) nests dicts/lists several
    levels deep, so a shallow top-level pass would miss a datetime buried inside
    ``weekly_split`` or ``fueling_timeline`` (WR-21-03).
    """
    if isinstance(v, dict):
        return {k: _jsonsafe_value(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_jsonsafe_value(x) for x in v]
    # psycopg2 returns Postgres NUMERIC/DECIMAL columns as Decimal, which
    # json.dumps cannot serialize (the /api/health/sleep 500). Coerce to float
    # here too, so any Postgres-backed payload that routes through this helper
    # is safe even if a reader forgets to coerce at the source.
    if isinstance(v, Decimal):
        return float(v)
    iso = getattr(v, "isoformat", None)
    if callable(iso):
        try:
            return iso()
        except Exception:
            return str(v)
    return v


class TrainingLogStore:
    """Per-session training log stored in Firestore (Phase 20 — LOG-01/LOG-02).

    Collection: training_log
    Document ID: {YYYY-MM-DD}_{slot}

    Idempotency:
        Garmin silent sync may write before the user replies; merge=True on the
        doc_id key prevents duplicate rows (Pitfall 4 / LOG-01).

    RPE normalisation (Pitfall 7):
        Garmin stores perceived_exertion in steps of 10 (10..100 for 1..10 scale).
        log_session normalises values > 10 that are multiples of 10 to the 1..10
        scale by integer division.  Values already in 1..10 are left unchanged.

    Read discipline (LOG-02):
        get_recent / get_by_date / get_range — never raise on Firestore errors;
        return [] so callers (weekly review, morning briefing) can degrade
        gracefully.

    Write discipline (LOG-01):
        log_session re-raises on Firestore write failures so callers know the
        sync failed (matches UserProfileStore.update / MealStore.upsert convention).
    """

    _COLLECTION = "training_log"

    def __init__(self, project_id: str, database: str = "(default)") -> None:
        self._client = _make_firestore_client(project_id, database)
        self._col = self._client.collection(self._COLLECTION)

    def log_session(
        self,
        date: str,                              # YYYY-MM-DD
        slot: str,                              # calendar event id or YYYYMMDDHHmm
        session_type: str | None = None,
        planned: bool = False,
        completed: bool = False,
        skipped_reason: str | None = None,      # rest_recovery | sick_injured | too_busy | other
        rpe: int | None = None,                 # 1–10 (normalised here from Garmin raw)
        feel: int | None = None,                # Garmin feel value, verbatim
        notes: str | None = None,
        quality: str | None = None,             # "strong" | "neutral" | "grind" | None (D-13 Phase 24)
        source: str = "telegram",               # garmin | telegram | manual_chat
        garmin_activity_id: str | None = None,
    ) -> None:
        """Write one training session to training_log/{date}_{slot}.

        Idempotent via merge=True — safe to call multiple times for the same
        (date, slot) pair (e.g. Garmin silent sync then user Telegram reply).

        Pitfall 7: normalises Garmin raw RPE (steps-of-10, 10..100) to 1..10.
        Values already in 1..10 are left unchanged.

        quality: "strong" | "neutral" | "grind" | None — D-13 derived field.
            Derived from Garmin Feel + RPE + notes by derive_session_quality in
            core/training_checkin.py. Existing entries without quality remain
            valid (merge=True handles backward compatibility).

        Raises:
            Exception: Re-raises any Firestore write failure after logging it.
        """
        doc_id = f"{date}_{slot}"
        # Pitfall 7: normalise Garmin raw RPE (steps-of-10, 10..100) to 1..10
        if rpe is not None and rpe > 10 and rpe % 10 == 0:
            rpe = rpe // 10
        payload = {
            "date": date,
            "slot": slot,
            "type": session_type,
            "planned": planned,
            "completed": completed,
            "skipped_reason": skipped_reason,
            "rpe": rpe,
            "feel": feel,
            "notes": notes,
            "quality": quality,
            "source": source,
            "garmin_activity_id": garmin_activity_id,
            "updated_at": firestore.SERVER_TIMESTAMP,
        }
        try:
            self._col.document(doc_id).set(payload, merge=True)   # merge=True — idempotent
        except Exception:
            logger.error("TrainingLogStore.log_session(%r) failed", doc_id, exc_info=True)
            raise

    def get_recent(self, days: int) -> list[dict]:
        """Return sessions with date >= today-{days}, sorted date desc, with doc_id.

        Never raises — returns [] on any Firestore error (LOG-02).

        Args:
            days: Number of calendar days to look back (inclusive).

        Returns:
            List of session dicts, each with a ``doc_id`` field, sorted by date
            descending.  Empty list on any Firestore error.
        """
        try:
            from datetime import date as _date, timedelta
            cutoff = (_date.today() - timedelta(days=days)).isoformat()
            # Server-side filter + order — only the window's docs are read,
            # not the lifetime collection.
            query = _where(self._col, "date", ">=", cutoff).order_by(
                "date", direction=_DESCENDING
            )
            results = []
            for snap in query.stream():
                d = _jsonsafe_doc(snap.to_dict() or {})
                d["doc_id"] = snap.id
                results.append(d)
            return results
        except Exception:
            logger.warning("TrainingLogStore.get_recent failed", exc_info=True)
            return []

    def get_by_date(self, date_str: str) -> list[dict]:
        """Return all sessions for one calendar date.

        Every doc carries a ``date`` field equal to the YYYY-MM-DD prefix of
        its doc_id, so an equality query replaces the old doc-ID prefix scan.

        Never raises — returns [] on any Firestore error (LOG-02).

        Args:
            date_str: YYYY-MM-DD date.

        Returns:
            List of matching session dicts (each with doc_id).  Empty on error.
        """
        try:
            query = _where(self._col, "date", "==", date_str)
            return [
                {**_jsonsafe_doc(snap.to_dict() or {}), "doc_id": snap.id}
                for snap in query.stream()
            ]
        except Exception:
            logger.warning("TrainingLogStore.get_by_date(%r) failed", date_str, exc_info=True)
            return []

    def get_range(self, start_date: str, end_date: str) -> list[dict]:
        """Return all sessions in [start_date, end_date] (inclusive), sorted date desc.

        Never raises — returns [] on any Firestore error (LOG-02).

        Args:
            start_date: YYYY-MM-DD start of range (inclusive).
            end_date:   YYYY-MM-DD end of range (inclusive).

        Returns:
            List of session dicts with doc_id, sorted date desc.  Empty on error.
        """
        try:
            query = _where(
                _where(self._col, "date", ">=", start_date), "date", "<=", end_date
            ).order_by("date", direction=_DESCENDING)
            results = []
            for snap in query.stream():
                d = _jsonsafe_doc(snap.to_dict() or {})
                d["doc_id"] = snap.id
                results.append(d)
            return results
        except Exception:
            logger.warning(
                "TrainingLogStore.get_range(%r, %r) failed",
                start_date, end_date, exc_info=True,
            )
            return []


class StrengthSessionStore:
    """Per-workout strength-training log synced from Hevy.

    Collection: ``strength_sessions``
    Document ID: the Hevy ``workout_id`` (idempotent — re-syncing the same
    workout lands on the same doc via merge=True).

    Unlike TrainingLogStore (session-level metadata keyed by calendar slot),
    this store holds the FULL per-exercise / per-set detail (weight, reps, RPE)
    plus the derived strength metrics pre-computed at ingest by
    ``mcp_tools.hevy_tool.normalize_workout`` (top_set, est_1rm, volume_kg).
    The two stores are independent and read side-by-side by the weekly review;
    no fragile join on date is attempted.

    Read discipline:
        get_range / get_recent / get_exercise_history never raise on Firestore
        errors — they return ``[]`` so coaching read-paths degrade gracefully.
        Reads strip ``updated_at`` (a DatetimeWithNanoseconds SERVER_TIMESTAMP)
        via _jsonsafe_doc so the result round-trips through ``json.dumps``
        (same hazard that bit MealStore / TrainingLogStore).

    Write discipline:
        upsert / delete re-raise on Firestore failure so the ingest cron knows
        the sync did not land (matches MealStore.upsert / TrainingLogStore).
    """

    _COLLECTION = "strength_sessions"

    def __init__(self, project_id: str, database: str = "(default)") -> None:
        self._client = _make_firestore_client(project_id, database)
        self._col = self._client.collection(self._COLLECTION)

    def upsert(self, workout: dict) -> None:
        """Idempotent write keyed on workout['workout_id']. Re-raises on failure.

        Args:
            workout: Normalized workout dict from
                ``mcp_tools.hevy_tool.normalize_workout`` — must include a
                truthy ``workout_id``.

        Raises:
            ValueError: If ``workout_id`` is missing/empty (would collide).
            Exception:  Re-raises any Firestore write failure after logging.
        """
        workout_id = workout.get("workout_id")
        if not workout_id:
            raise ValueError("StrengthSessionStore.upsert requires a workout_id")
        try:
            self._col.document(str(workout_id)).set(
                {**workout, "source": "hevy", "updated_at": firestore.SERVER_TIMESTAMP},
                merge=True,
            )
        except Exception:
            logger.error("StrengthSessionStore.upsert(%r) failed", workout_id, exc_info=True)
            raise

    def delete(self, workout_id: str) -> None:
        """Delete a workout doc (Hevy 'deleted' event). Re-raises on failure."""
        try:
            self._col.document(str(workout_id)).delete()
        except Exception:
            logger.error("StrengthSessionStore.delete(%r) failed", workout_id, exc_info=True)
            raise

    def get_range(self, start_date: str, end_date: str) -> list[dict]:
        """Return sessions with date in [start_date, end_date], newest-first.

        Never raises — returns ``[]`` on any Firestore error.
        """
        try:
            query = _where(
                _where(self._col, "date", ">=", start_date), "date", "<=", end_date
            ).order_by("date", direction=_DESCENDING)
            return [_jsonsafe_doc(snap.to_dict() or {}) for snap in query.stream()]
        except Exception:
            logger.warning(
                "StrengthSessionStore.get_range(%r, %r) failed",
                start_date, end_date, exc_info=True,
            )
            return []

    def get_recent(self, days: int) -> list[dict]:
        """Return sessions with date >= today-{days}, newest-first.

        Never raises — returns ``[]`` on any Firestore error.
        """
        try:
            from datetime import date as _date, timedelta
            cutoff = (_date.today() - timedelta(days=days)).isoformat()
            query = _where(self._col, "date", ">=", cutoff).order_by(
                "date", direction=_DESCENDING
            )
            return [_jsonsafe_doc(snap.to_dict() or {}) for snap in query.stream()]
        except Exception:
            logger.warning("StrengthSessionStore.get_recent(%r) failed", days, exc_info=True)
            return []

    def get_exercise_history(self, name: str, limit: int | None = None) -> list[dict]:
        """Return the per-session progression for one exercise, newest-first.

        Scans all sessions and, for each that contains an exercise whose name
        matches ``name`` (case-insensitive), emits a compact progression record:
        ``{"date", "workout_id", "top_set", "est_1rm", "volume_kg"}``. This is
        the data Klaus uses to spot trends and stalls on a specific lift.

        Never raises — returns ``[]`` on any Firestore error.

        Args:
            name:  Exercise name to match (case-insensitive, exact).
            limit: Cap on the number of records returned (most-recent first).
        """
        try:
            target = (name or "").strip().lower()
            records: list[dict] = []
            # The nested exercises[].name array isn't Firestore-queryable, so
            # this stays a scan — but ordered newest-first server-side, so a
            # `limit` lets us stop streaming early instead of reading all docs.
            query = self._col.order_by("date", direction=_DESCENDING)
            for snap in query.stream():
                d = _jsonsafe_doc(snap.to_dict() or {})
                for ex in d.get("exercises") or []:
                    if (ex.get("name") or "").strip().lower() == target:
                        records.append({
                            "date": d.get("date"),
                            "workout_id": d.get("workout_id"),
                            "top_set": ex.get("top_set"),
                            "est_1rm": ex.get("est_1rm"),
                            "volume_kg": ex.get("volume_kg"),
                        })
                if limit and len(records) >= limit:
                    break
            return records[:limit] if limit else records
        except Exception:
            logger.warning(
                "StrengthSessionStore.get_exercise_history(%r) failed", name, exc_info=True,
            )
            return []


class RunDetailStore:
    """Per-run Garmin detail — full splits + dynamics for each run.

    Collection: ``run_details``
    Document ID: the Garmin ``activity_id`` (idempotent — re-syncing the same
    run lands on the same doc via merge=True).

    Holds the FULL per-run detail (recorded laps/intervals exactly as the watch
    captured them, plus whole-run {min,avg,max} dynamics summary and derived
    signals) pre-computed at ingest by ``mcp_tools.garmin_tool.normalize_run_detail``.
    This is the running analogue of StrengthSessionStore (which holds per-set
    strength detail) — both are read side-by-side by the coaching read-paths.

    Read discipline:
        get_range / get_recent / get_run never raise on Firestore errors — they
        return ``[]`` / ``None`` so coaching read-paths degrade gracefully.
        Reads strip ``updated_at`` (a DatetimeWithNanoseconds SERVER_TIMESTAMP)
        via _jsonsafe_doc so the result round-trips through ``json.dumps``.

    Write discipline:
        upsert / delete re-raise on Firestore failure so the ingest cron knows
        the sync did not land (matches StrengthSessionStore convention).
    """

    _COLLECTION = "run_details"

    def __init__(self, project_id: str, database: str = "(default)") -> None:
        self._client = _make_firestore_client(project_id, database)
        self._col = self._client.collection(self._COLLECTION)

    def upsert(self, run: dict) -> None:
        """Idempotent write keyed on run['activity_id']. Re-raises on failure.

        Args:
            run: Normalized run dict from
                ``mcp_tools.garmin_tool.normalize_run_detail`` — must include a
                truthy ``activity_id``.

        Raises:
            ValueError: If ``activity_id`` is missing/empty (would collide).
            Exception:  Re-raises any Firestore write failure after logging.
        """
        activity_id = run.get("activity_id")
        if not activity_id or activity_id == "None":
            raise ValueError("RunDetailStore.upsert requires an activity_id")
        try:
            self._col.document(str(activity_id)).set(
                {**run, "source": "garmin", "updated_at": firestore.SERVER_TIMESTAMP},
                merge=True,
            )
        except Exception:
            logger.error("RunDetailStore.upsert(%r) failed", activity_id, exc_info=True)
            raise

    def delete(self, activity_id: str) -> None:
        """Delete a run doc. Re-raises on failure."""
        try:
            self._col.document(str(activity_id)).delete()
        except Exception:
            logger.error("RunDetailStore.delete(%r) failed", activity_id, exc_info=True)
            raise

    def get_run(self, activity_id: str) -> dict | None:
        """Return one run doc by activity_id, or None if absent / on error.

        Used by the ingest cron as a presence check (skip already-synced runs)
        and by the get_run_detail tool for single-run lookups.
        """
        try:
            snap = self._col.document(str(activity_id)).get()
            if not snap.exists:
                return None
            return _jsonsafe_doc(snap.to_dict() or {})
        except Exception:
            logger.warning("RunDetailStore.get_run(%r) failed", activity_id, exc_info=True)
            return None

    def get_range(self, start_date: str, end_date: str) -> list[dict]:
        """Return runs with date in [start_date, end_date], newest-first.

        Never raises — returns ``[]`` on any Firestore error.
        """
        try:
            query = _where(
                _where(self._col, "date", ">=", start_date), "date", "<=", end_date
            ).order_by("date", direction=_DESCENDING)
            return [_jsonsafe_doc(snap.to_dict() or {}) for snap in query.stream()]
        except Exception:
            logger.warning(
                "RunDetailStore.get_range(%r, %r) failed",
                start_date, end_date, exc_info=True,
            )
            return []

    def get_recent(self, days: int) -> list[dict]:
        """Return runs with date >= today-{days}, newest-first.

        Never raises — returns ``[]`` on any Firestore error.
        """
        try:
            from datetime import date as _date, timedelta
            cutoff = (_date.today() - timedelta(days=days)).isoformat()
            query = _where(self._col, "date", ">=", cutoff).order_by(
                "date", direction=_DESCENDING
            )
            return [_jsonsafe_doc(snap.to_dict() or {}) for snap in query.stream()]
        except Exception:
            logger.warning("RunDetailStore.get_recent(%r) failed", days, exc_info=True)
            return []


def _pending_expiry(hours: int = 20) -> tuple[str, str]:
    """Return (created_at_iso, expires_at_iso) in UTC for a pending prompt session.

    Args:
        hours: TTL hours from now (default 20 — prompts sent at 21:30 expire before
               the morning briefing window 6–10 am, per Finding 5).

    Returns:
        Tuple of (created_at, expires_at) as ISO-8601 UTC strings.
    """
    from datetime import datetime, timezone, timedelta
    now = datetime.now(timezone.utc)
    return now.isoformat(), (now + timedelta(hours=hours)).isoformat()


class PendingPromptStore:
    """Session state for multi-step training check-in prompts (Phase 20 — V3 session mgmt).

    Firestore path: pending_prompts/{session_key}

    Each document records where the user is in the check-in flow.  The soft TTL
    (~20h, per Finding 5) prevents stale sessions from the prior evening from
    triggering on the next day.

    Valid state values:
        awaiting_rpe            — RPE inline keyboard sent; waiting for button tap
        awaiting_watchoff       — Watch-off RPE keyboard sent; waiting for button tap
        awaiting_notes          — Notes prompt sent; waiting for reply-to text
        awaiting_skipreason_other — "other" skip reason keyboard; waiting for text

    Document fields (Finding 5):
        session_key:   str  — "{YYYY-MM-DD}_{event_id_fragment}"
        user_id:       int  — Telegram user ID
        state:         str  — one of the four state values above
        message_id:    int  — Telegram message_id of the prompt (reply-to detection)
        event_summary: str  — Calendar event name (user-facing copy)
        event_date:    str  — YYYY-MM-DD
        rpe:           int | None — filled after RPE tap
        created_at:    str  — ISO-8601 UTC
        expires_at:    str  — ISO-8601 UTC (soft TTL ~20h)

    T-20-02 (DoS mitigation): reads enforce the soft TTL; expired sessions return
    None so stale docs are inert even if not yet physically deleted.  delete() is
    called on terminal state transitions (Plans 03/04) to prevent collection growth.

    Write discipline:
        set() NEVER raises — a failed pending-prompt write is logged + silently
        skipped; the check-in degrades to no follow-up, not a crash.

    Read discipline:
        get() / get_open_note_session() NEVER raise — return None on error.
    """

    _COLLECTION = "pending_prompts"

    def __init__(self, project_id: str, database: str = "(default)") -> None:
        self._client = _make_firestore_client(project_id, database)
        self._col = self._client.collection(self._COLLECTION)

    def set(self, session_key: str, payload: dict) -> None:
        """Upsert a pending prompt session.

        Stamps ``session_key`` into the stored payload.  Uses merge=True so
        partial updates (e.g. adding ``rpe`` after the RPE tap) are safe.

        NEVER raises — a Firestore failure is logged at WARNING and silently
        swallowed; the check-in degrades to no follow-up rather than a crash.

        Args:
            session_key: Document ID (``"{YYYY-MM-DD}_{event_id_fragment}"``).
            payload:     Session fields dict (see class docstring for shape).
        """
        try:
            self._col.document(session_key).set(
                {**payload, "session_key": session_key},
                merge=True,
            )
        except Exception:
            logger.warning("PendingPromptStore.set(%r) failed", session_key, exc_info=True)
            # NEVER re-raises — degraded write is silent

    def get(self, session_key: str) -> dict | None:
        """Return the session dict, or None if expired/missing/error.

        Enforces the soft TTL: if ``expires_at`` is in the past, the session
        is silently discarded (returns None) even if the document still exists.
        This prevents stale-replay attacks (T-20-02 / Security Domain V3).

        Args:
            session_key: Document ID.

        Returns:
            Session dict, or None if the session is absent, expired, or
            Firestore is unreachable.
        """
        try:
            from datetime import datetime, timezone
            snap = self._col.document(session_key).get()
            if not snap.exists:
                return None
            data = snap.to_dict() or {}
            expires_at = data.get("expires_at")
            if expires_at:
                if isinstance(expires_at, str):
                    exp = datetime.fromisoformat(expires_at)
                    if exp.tzinfo is None:
                        exp = exp.replace(tzinfo=timezone.utc)
                else:
                    exp = expires_at
                if datetime.now(timezone.utc) > exp:
                    return None   # soft TTL expired — stale-replay rejected
            return data
        except Exception:
            logger.warning("PendingPromptStore.get(%r) failed", session_key, exc_info=True)
            return None

    def delete(self, session_key: str) -> None:
        """Delete a session on terminal state transition (resolved/cancelled).

        Never raises — cleanup failure is logged at WARNING but does not
        propagate (the session is inert after the TTL expires anyway).

        Args:
            session_key: Document ID to delete.
        """
        try:
            self._col.document(session_key).delete()
        except Exception:
            logger.warning("PendingPromptStore.delete(%r) failed", session_key, exc_info=True)

    def get_open_note_session(self, user_id: int) -> dict | None:
        """Return the first open ``awaiting_notes`` session for the given user.

        Used by the router's reply-to detection fallback (Finding 5): when
        there is no ``reply_to_message`` but an open notes session exists,
        the brain decides whether the incoming text is the notes reply.

        Never raises — returns None on Firestore error.

        Args:
            user_id: Telegram user ID.

        Returns:
            The first non-expired ``awaiting_notes`` session dict for the user,
            or None if no such session exists.
        """
        try:
            from datetime import datetime, timezone
            snaps = list(self._col.stream())
            now = datetime.now(timezone.utc)
            for snap in snaps:
                data = snap.to_dict() or {}
                # Both states wait on a free-text reply-to: awaiting_notes (after an
                # RPE log) and awaiting_skipreason_other (after the "Other — tell me"
                # skip reason). The router dispatches on state to the right handler.
                if data.get("state") not in ("awaiting_notes", "awaiting_skipreason_other"):
                    continue
                if data.get("user_id") != user_id:
                    continue
                # enforce soft TTL
                expires_at = data.get("expires_at")
                if expires_at:
                    if isinstance(expires_at, str):
                        exp = datetime.fromisoformat(expires_at)
                        if exp.tzinfo is None:
                            exp = exp.replace(tzinfo=timezone.utc)
                    else:
                        exp = expires_at
                    if now > exp:
                        continue
                return data
            return None
        except Exception:
            logger.warning(
                "PendingPromptStore.get_open_note_session(%r) failed",
                user_id, exc_info=True,
            )
            return None


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
        self._client = _make_firestore_client(project_id, database)
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
        self._client = _make_firestore_client(project_id, database)
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


class CoachingTopicStore:
    """Per-day coaching topic gate for cross-cron dedup (Phase 24 — COACH-05).

    Collection: ``coaching_topics/{YYYY-MM-DD}``
    Schema: { "date": str, "topics": list[str], "updated_at": SERVER_TIMESTAMP }

    D-04: daily reset via date-keyed doc (same pattern as OutreachLogStore).
    D-02: has_topic() hard-blocks; add_topic() writes only for proactive crons.
    D-03: reactive chat never calls either method.

    NOTE: store topic keys as a plain list[str]. DO NOT use list[dict] entries
    with embedded timestamps. ArrayUnion compares by deep equality — dicts
    containing SERVER_TIMESTAMP sentinels are NEVER equal (each sentinel is a
    fresh object), which defeats dedup. See OutreachLogStore NOTE 2.

    Reads (has_topic, topics_today) never raise — fail-open (return False / []).
    Writes (add_topic) re-raise after logging — caller decides whether to abort.
    """

    _COLLECTION = "coaching_topics"   # lowercase — CLAUDE.md §6

    def __init__(self, project_id: str, database: str = "(default)") -> None:
        """
        Args:
            project_id: GCP project ID.
            database:   Firestore database name (defaults to "(default)").
        """
        self._client = _make_firestore_client(project_id, database)
        self._col = self._client.collection(self._COLLECTION)

    def has_topic(self, date_str: str, topic_key: str) -> bool:
        """Hard-block check — returns True if topic_key was already raised today.

        Never raises — fail-open: returns False on any Firestore error so a
        read failure allows the topic to fire rather than silently suppressing it
        (data-integrity bias: prefer false-positive delivery over silent omission).

        Args:
            date_str:  YYYY-MM-DD (Asia/Jerusalem calendar date).
            topic_key: e.g. "protein-miss" or "skipped-session:threshold-run".

        Returns:
            True if the topic was already recorded for this date, False otherwise.
        """
        try:
            snap = self._col.document(date_str).get()
            if not snap.exists:
                return False
            topics = (snap.to_dict() or {}).get("topics") or []
            return topic_key in topics
        except Exception:
            logger.warning("CoachingTopicStore.has_topic failed", exc_info=True)
            return False  # fail-open: let the topic fire rather than silently suppress

    def add_topic(self, date_str: str, topic_key: str) -> None:
        """Atomically add topic_key to today's coaching_topics doc.

        Uses ``firestore.ArrayUnion([topic_key])`` with ``merge=True`` so
        concurrent crons cannot clobber each other and so the doc is created
        on the first call of the day without a separate ``set``.

        Call AFTER ``send_and_inject`` succeeds — mirrors Phase 18 D-10
        OutreachLogStore.append invariant. A crash between write and send
        creates a false-positive block; writing after send is the safer order.

        Args:
            date_str:  YYYY-MM-DD (Asia/Jerusalem calendar date).
            topic_key: Plain string topic key — e.g. "protein-miss".
                       MUST be a plain string, NOT a dict. ArrayUnion deep-
                       equality breaks if the element contains SERVER_TIMESTAMP
                       (see class-level NOTE and OutreachLogStore NOTE 2).

        Raises:
            Exception: Re-raises any Firestore write failure after logging it.
        """
        try:
            self._col.document(date_str).set(
                {
                    "date": date_str,
                    "topics": firestore.ArrayUnion([topic_key]),  # plain string, NOT dict
                    "updated_at": firestore.SERVER_TIMESTAMP,     # doc-level only
                },
                merge=True,
            )
        except Exception:
            logger.error(
                "CoachingTopicStore.add_topic(%r, %r) failed",
                date_str,
                topic_key,
                exc_info=True,
            )
            raise

    def topics_today(self, date_str: str) -> list[str]:
        """Return today's raised topic_keys. Never raises.

        Args:
            date_str: YYYY-MM-DD (Asia/Jerusalem calendar date).

        Returns:
            List of topic_key strings raised for this date. Empty list when
            the doc does not exist OR when Firestore is unreachable.
        """
        try:
            snap = self._col.document(date_str).get()
            if not snap.exists:
                return []
            return list((snap.to_dict() or {}).get("topics") or [])
        except Exception:
            logger.warning("CoachingTopicStore.topics_today failed", exc_info=True)
            return []


class TickLogStore:
    """Per-tick snapshot writer — supports retroactive eval-fixture labeling.

    Schema (collection: ``tick_logs/{YYYY-MM-DD}/ticks/{HH:MM}``):
        captured_at: str           # ISO-8601 UTC — when this tick was logged
        situation_snapshot: dict   # gather_situation output (with 'empty' stripped)
        decision_trail: dict       # run_autonomous_tick decision dict

    Best-effort writes: **never raises**. This matches Plan 06's contract
    that ``_write_tick_log`` must never abort the tick. Used downstream by
    the retroactive-labeling workflow documented in
    ``evals/tick_brain/README.md`` (Plan 04) — over a week of live ticks,
    ~25 snapshots become labeled fixtures for the judgment eval (D-21).

    Phase 18 — D-21 (Claude's discretion: per-tick logging for eval fixture growth).

    NOTE 1 — added in Plan 01 (rather than calling ``_make_firestore_client``
    directly from Plan 06's ``_write_tick_log``) to keep the
    JournalStore/SelfStateStore/FollowupStore/OutreachLogStore
    wrapper-class pattern consistent across stores. Plan 06's executor
    should ``from memory.firestore_db import TickLogStore`` and call
    ``TickLogStore(project_id, database).write(...)`` rather than reach
    into the private ``_make_firestore_client`` helper.
    """

    _COLLECTION = "tick_logs"

    def __init__(self, project_id: str, database: str = "(default)") -> None:
        """
        Args:
            project_id: GCP project ID.
            database:   Firestore database name (defaults to "(default)").
        """
        self._client = _make_firestore_client(project_id, database)
        self._col = self._client.collection(self._COLLECTION)

    def write(self, date_str: str, tick_time: str,
              situation: dict, decision: dict) -> None:
        """Write one tick's snapshot. Best-effort — swallows all exceptions.

        Writes to ``tick_logs/{date_str}/ticks/{tick_time}`` so each day's
        ticks live under a single top-level date doc (cheap retention prune
        in the future — drop the whole date doc).

        Args:
            date_str:  YYYY-MM-DD (Israel time) — top-level doc id under tick_logs.
            tick_time: HH:MM (Israel time) — sub-collection doc id under ticks/.
            situation: ``gather_situation()`` output (Plan 06). The ``empty``
                flag is stripped before persistence — it's transient
                bookkeeping, not part of the eval fixture.
            decision:  ``run_autonomous_tick()`` decision trail dict (Plan 06).

        Returns:
            None always. Errors are logged at WARNING and swallowed so the
            calling tick can continue. **This is the only store method in
            this module that does not re-raise on write failure** — matches
            Plan 06's "_write_tick_log never raises" contract.
        """
        # Inline import keeps the class loadable when google.cloud.firestore
        # is mocked at sys.modules level (test pattern). Same convention as
        # FollowupStore.add.
        from datetime import datetime, timezone

        try:
            (self._col
                .document(date_str)
                .collection("ticks")
                .document(tick_time)
                .set({
                    "captured_at": datetime.now(timezone.utc).isoformat(),
                    "situation_snapshot": {
                        k: v for k, v in situation.items() if k != "empty"
                    },
                    "decision_trail": decision,
                }))
        except Exception:
            logger.warning(
                "TickLogStore.write(%r, %r) failed (non-fatal)",
                date_str, tick_time, exc_info=True,
            )

    def ticks_for_date(self, date_str: str) -> list[dict]:
        """All ticks for one Israel-calendar date, sorted by HH:MM. Never raises.

        Each dict carries the stored fields (``captured_at``,
        ``situation_snapshot``, ``decision_trail``) plus ``time`` — the HH:MM
        doc id, which is not stored inside the doc itself.

        NOTE: callers iterate candidate dates client-side rather than listing
        ``tick_logs`` top-level docs — those parent docs are *virtual* (write()
        only ever sets subcollection docs), so a collection stream() would
        return nothing for them.

        Args:
            date_str: YYYY-MM-DD (Israel time) — top-level doc id under tick_logs.

        Returns:
            Tick dicts sorted by ``time``; [] for a missing date or on any
            Firestore error (read contract matches the write side's
            best-effort design — exporting must not crash on one bad day).
        """
        try:
            ticks = []
            for snap in self._col.document(date_str).collection("ticks").stream():
                d = snap.to_dict() or {}
                d["time"] = snap.id
                ticks.append(d)
            ticks.sort(key=lambda d: d["time"])
            return ticks
        except Exception:
            logger.warning(
                "TickLogStore.ticks_for_date(%r) failed — returning []",
                date_str, exc_info=True,
            )
            return []


def get_week_num(plan_start_date: str, today: str) -> int | None:
    """Return the 1-based week number for ``today`` relative to ``plan_start_date``.

    Returns None when ``today`` is before ``plan_start_date`` (pre-cycle).

    Formula (D-03): ``(today - start).days // 7 + 1``
    Week 1 = days 0..6 inclusive; week 2 = days 7..13; etc.

    Args:
        plan_start_date: ISO date string "YYYY-MM-DD" (e.g. "2026-06-21").
        today:           ISO date string "YYYY-MM-DD" representing today.

    Returns:
        1-based week number, or None if today < plan_start_date.
    """
    from datetime import date as _date
    start = _date.fromisoformat(plan_start_date)
    today_dt = _date.fromisoformat(today)
    if today_dt < start:
        return None
    return (today_dt - start).days // 7 + 1


# 5-facet closed set for benchmark validation (D-06 / T-23-01)
_BENCHMARK_FACETS: frozenset[str] = frozenset({
    "bench_press_1rm",
    "squat_1rm",
    "push_ups",
    "pull_ups",
    "threshold_pace",
})


class BlockStore:
    """Training block tracking stored in Firestore (Phase 23 — BLOCK-01).

    Collection: training_blocks
    Document ID: {YYYY-MM-DD}_{label_slug} (e.g. "2026-06-21_aerobic_base")

    Schema fields:
        block_id:             str  — same as doc id: "{YYYY-MM-DD}_{label_slug}"
        label:                str  — "Aerobic Base", "Capacity Build", etc.
        start_date:           str  — YYYY-MM-DD (stored as string, not timestamp)
        end_date:             str  — YYYY-MM-DD (stored as string, not timestamp)
        focus_facets:         list — ["bench_press_1rm", "squat_1rm", ...]
        weekly_split_override:dict|None — None for auto-seeded blocks
        status:               str  — "active"|"complete"|"abandoned"|"pending"
                                     BOOKKEEPING ONLY — get_current does NOT filter on status
        notes:                str  — ""
        benchmark_due:        bool — False until deload week triggers it
        created_at:           SERVER_TIMESTAMP
        updated_at:           SERVER_TIMESTAMP

    get_current() resolution semantics (D-01 — the critical contract):
        Resolves by DATE RANGE (start_date <= today <= end_date) across all seeded
        blocks. Does NOT filter on status=active. This means Block 1 → Block 2
        transitions are automatic as time advances, even if start_block() is never
        called. The `status` field is bookkeeping for the current_block_id FK —
        not a precondition of get_current's correctness.

    Read discipline: get_current / get_all never raise (return None/[] on error).
    Write discipline: upsert / set_benchmark_due / start_block / end_block re-raise.
    """

    _COLLECTION = "training_blocks"

    def __init__(self, project_id: str, database: str = "(default)") -> None:
        self._client = _make_firestore_client(project_id, database)
        self._col = self._client.collection(self._COLLECTION)

    def get_current(self, today: str | None = None) -> dict | None:
        """Return the block whose date range contains today — or None if none matches.

        Resolution is DATE-RANGE based (D-01): start_date <= today <= end_date.
        Does NOT filter on status field — status is bookkeeping only.
        If multiple blocks overlap (should not happen with contiguous seed), returns
        the one with the earliest start_date.

        Args:
            today: ISO date string "YYYY-MM-DD". Defaults to current date when None.

        Returns:
            Block dict with doc_id attached, or None (pre/post-cycle or on error).
            Never raises.
        """
        try:
            if today is None:
                from datetime import date as _date
                today = _date.today().isoformat()
            snaps = list(self._col.stream())
            matches = []
            for snap in snaps:
                d = _jsonsafe_doc(snap.to_dict() or {})
                d["doc_id"] = snap.id
                start = d.get("start_date", "")
                end = d.get("end_date", "")
                if start and end and start <= today <= end:
                    matches.append(d)
            if not matches:
                return None
            # If multiple (shouldn't happen with contiguous seed), return earliest start
            matches.sort(key=lambda b: b.get("start_date", ""))
            return matches[0]
        except Exception:
            logger.warning("BlockStore.get_current() failed", exc_info=True)
            return None

    def get_all(self) -> list[dict]:
        """Return all training block docs, unordered, with doc_id.

        Never raises — returns [] on any Firestore error.
        """
        try:
            snaps = list(self._col.stream())
            results = []
            for snap in snaps:
                d = _jsonsafe_doc(snap.to_dict() or {})
                d["doc_id"] = snap.id
                results.append(d)
            return results
        except Exception:
            logger.warning("BlockStore.get_all() failed", exc_info=True)
            return []

    def upsert(self, block: dict) -> None:
        """Write or merge a block doc. Re-raises on Firestore failure.

        Uses merge=True so partial updates (e.g. set_benchmark_due) are safe.
        Stamps created_at and updated_at with SERVER_TIMESTAMP.

        Args:
            block: Block dict. Must include 'block_id' key (used as doc id).

        Raises:
            Exception: Re-raises any Firestore write failure.
        """
        doc_id = block["block_id"]
        payload = {
            **block,
            "updated_at": firestore.SERVER_TIMESTAMP,
        }
        try:
            ref = self._col.document(doc_id)
            # WR-02: only stamp created_at on the FIRST write. A --force re-seed
            # uses merge=True, so unconditionally writing created_at would clobber
            # the original creation timestamp on every re-run.
            existing = ref.get()
            if not getattr(existing, "exists", False):
                payload["created_at"] = firestore.SERVER_TIMESTAMP
            ref.set(payload, merge=True)
        except Exception:
            logger.error("BlockStore.upsert(%r) failed", doc_id, exc_info=True)
            raise

    def set_benchmark_due(self, block_id: str, due: bool) -> None:
        """Set or clear the benchmark_due flag on an existing block.

        Uses merge=True — touches only benchmark_due and updated_at.

        Args:
            block_id: Block doc ID.
            due:      True to mark benchmark due; False to clear.

        Raises:
            Exception: Re-raises any Firestore write failure.
        """
        try:
            self._col.document(block_id).set(
                {"benchmark_due": due, "updated_at": firestore.SERVER_TIMESTAMP},
                merge=True,
            )
        except Exception:
            logger.error("BlockStore.set_benchmark_due(%r, %r) failed", block_id, due, exc_info=True)
            raise

    def start_block(self, block_id: str) -> None:
        """Set status='active' on a block (bookkeeping — not a precondition of get_current).

        Also updates the updated_at timestamp via merge.

        Args:
            block_id: Block doc ID.

        Raises:
            Exception: Re-raises any Firestore write failure.
        """
        try:
            self._col.document(block_id).set(
                {"status": "active", "updated_at": firestore.SERVER_TIMESTAMP},
                merge=True,
            )
        except Exception:
            logger.error("BlockStore.start_block(%r) failed", block_id, exc_info=True)
            raise

    def end_block(self, block_id: str) -> None:
        """Set status='complete' on a block (bookkeeping — not a precondition of get_current).

        Also updates the updated_at timestamp via merge.

        Args:
            block_id: Block doc ID.

        Raises:
            Exception: Re-raises any Firestore write failure.
        """
        try:
            self._col.document(block_id).set(
                {"status": "complete", "updated_at": firestore.SERVER_TIMESTAMP},
                merge=True,
            )
        except Exception:
            logger.error("BlockStore.end_block(%r) failed", block_id, exc_info=True)
            raise


class BenchmarkStore:
    """Per-facet benchmark results stored in Firestore (Phase 23 — BLOCK-03).

    Collection: benchmarks
    Document ID: {YYYY-MM-DD}_{facet} (e.g. "2026-07-18_bench_press_1rm")

    Schema fields:
        date:       str   — YYYY-MM-DD
        facet:      str   — one of the 5-facet closed set (D-06)
        value:      float — numeric result
        unit:       str   — "kg" | "reps" | "sec_per_km"
        block_id:   str   — FK → training_blocks doc id
        notes:      str   — optional note (e.g. "Epley estimate from 85kg×5")
        updated_at: SERVER_TIMESTAMP

    Idempotency: doc_id = "{date}_{facet}" — logging the same facet on the same date
    merges (merge=True), so retries are safe.

    Input validation (T-23-01): log_benchmark raises ValueError for any facet outside
    the 5-facet closed set (_BENCHMARK_FACETS) — prevents arbitrary doc creation from
    LLM-supplied facet strings.

    Read discipline: get_facet_history / get_block_benchmarks never raise (return []).
    Write discipline: log_benchmark re-raises on Firestore failure.
    """

    _COLLECTION = "benchmarks"

    def __init__(self, project_id: str, database: str = "(default)") -> None:
        self._client = _make_firestore_client(project_id, database)
        self._col = self._client.collection(self._COLLECTION)

    def log_benchmark(
        self,
        date: str,
        facet: str,
        value: float,
        unit: str,
        block_id: str,
        notes: str = "",
    ) -> None:
        """Write one benchmark result to benchmarks/{date}_{facet}.

        Idempotent via merge=True — safe to call multiple times for the same
        (date, facet) pair (updates the value, e.g. on correction).

        Args:
            date:     YYYY-MM-DD date of the benchmark session.
            facet:    One of the 5 valid facets (T-23-01 validation).
            value:    Numeric result.
            unit:     "kg" | "reps" | "sec_per_km"
            block_id: FK to the training_blocks collection.
            notes:    Optional context note.

        Raises:
            ValueError:  If facet is not in the 5-facet closed set (T-23-01).
            Exception:   Re-raises any Firestore write failure.
        """
        if facet not in _BENCHMARK_FACETS:
            raise ValueError(
                f"Unknown facet {facet!r}. Valid facets: {sorted(_BENCHMARK_FACETS)}"
            )
        # IN-02: validate the date format before it becomes part of the doc id.
        # A malformed LLM-supplied date would otherwise produce an opaque SDK
        # error rather than a clean, catchable ValueError.
        from datetime import date as _date
        try:
            _date.fromisoformat(date)
        except (ValueError, TypeError):
            raise ValueError(f"Invalid date {date!r}; expected ISO YYYY-MM-DD")
        doc_id = f"{date}_{facet}"
        payload = {
            "date": date,
            "facet": facet,
            "value": value,
            "unit": unit,
            "block_id": block_id,
            "notes": notes,
            "updated_at": firestore.SERVER_TIMESTAMP,
        }
        try:
            self._col.document(doc_id).set(payload, merge=True)
        except Exception:
            logger.error("BenchmarkStore.log_benchmark(%r) failed", doc_id, exc_info=True)
            raise

    def get_facet_history(self, facet: str, n: int = 10) -> list[dict]:
        """Return the last n benchmark entries for a specific facet, sorted date-desc.

        Streams all benchmark docs, filters by facet in Python, sorts, and caps.

        Args:
            facet: Facet to filter by (e.g. "bench_press_1rm").
            n:     Maximum number of records to return (default 10).

        Returns:
            List of benchmark dicts, each with doc_id, sorted date desc.
            Empty list on any error — never raises.
        """
        try:
            snaps = list(self._col.stream())
            results = []
            for snap in snaps:
                d = _jsonsafe_doc(snap.to_dict() or {})
                d["doc_id"] = snap.id
                if d.get("facet") == facet:
                    results.append(d)
            results.sort(key=lambda d: d.get("date", ""), reverse=True)
            return results[:n]
        except Exception:
            logger.warning("BenchmarkStore.get_facet_history(%r) failed", facet, exc_info=True)
            return []

    def get_block_benchmarks(self, block_id: str) -> list[dict]:
        """Return all benchmarks for a given block, sorted date-desc.

        Uses a server-side FieldFilter on block_id.

        Args:
            block_id: FK to the training_blocks collection.

        Returns:
            List of benchmark dicts with doc_id, sorted date desc.
            Empty list on any error — never raises.
        """
        try:
            from google.cloud.firestore_v1.base_query import FieldFilter
            snaps = list(
                self._col.where(filter=FieldFilter("block_id", "==", block_id)).stream()
            )
            results = [
                {**_jsonsafe_doc(snap.to_dict() or {}), "doc_id": snap.id}
                for snap in snaps
            ]
            results.sort(key=lambda d: d.get("date", ""), reverse=True)
            return results
        except Exception:
            logger.warning(
                "BenchmarkStore.get_block_benchmarks(%r) failed", block_id, exc_info=True
            )
            return []

    def get_range(self, start_date: str, end_date: str) -> list[dict]:
        """Return benchmarks across ALL 5 facets with date in [start_date, end_date].

        Sorted newest-first (client-side, matching this class's existing
        get_facet_history/get_block_benchmarks style — FieldFilter + Python sort,
        NOT the module-level `_where` helper used by RunDetailStore/StrengthSessionStore).

        Args:
            start_date: ISO YYYY-MM-DD, inclusive lower bound.
            end_date:   ISO YYYY-MM-DD, inclusive upper bound.

        Returns:
            List of benchmark dicts (via _jsonsafe_doc), sorted date desc.
            Empty list on any error — never raises.
        """
        try:
            from google.cloud.firestore_v1.base_query import FieldFilter
            snaps = list(
                self._col
                .where(filter=FieldFilter("date", ">=", start_date))
                .where(filter=FieldFilter("date", "<=", end_date))
                .stream()
            )
            results = [_jsonsafe_doc(snap.to_dict() or {}) for snap in snaps]
            results.sort(key=lambda d: d.get("date", ""), reverse=True)
            return results
        except Exception:
            logger.warning(
                "BenchmarkStore.get_range(%r, %r) failed",
                start_date, end_date, exc_info=True,
            )
            return []


# ---------------------------------------------------------------------------
# Recurrence engine (Phase 27 — TASK-02 / D-05 / D-06)
# ---------------------------------------------------------------------------

from zoneinfo import ZoneInfo as _ZoneInfo

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
        self._client = _make_firestore_client(project_id, database)
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
    """User-creatable task lists.

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
        self._client = _make_firestore_client(project_id, database)
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


def _is_scheduled(target_date: "date", schedule_history: list[dict]) -> bool:
    """Return True if target_date falls on a scheduled day under the active revision.

    Selects the latest ``effective_from <= target_date`` revision from
    ``schedule_history`` (sorted ascending).  If no revision covers the date,
    returns False.

    ``days`` may be:
    - ``"daily"``  → always True
    - ``list[int]`` → Python weekday ints (Mon=0, Sun=6); checks membership.

    DST safety: operates on ``datetime.date`` objects only — no wall-clock
    component, so Israel DST transitions are transparent.
    """
    from datetime import date as _date
    if isinstance(target_date, str):
        target_date = _date.fromisoformat(target_date)

    applicable = None
    for rev in sorted(schedule_history, key=lambda r: r["effective_from"]):
        if rev["effective_from"] <= target_date.isoformat():
            applicable = rev
    if applicable is None:
        return False
    days = applicable["days"]
    if days == "daily":
        return True
    return target_date.weekday() in days


def compute_streak_and_grid(
    habit_id: str,
    schedule_history: list[dict],
    completions: dict,          # keyed by "YYYY-MM-DD"
    today: "date",
    window_days: int = 365,
) -> dict:
    """Pure function — no Firestore calls.

    Computes the current streak and 365-day contribution grid for a habit.

    Args:
        habit_id:         Unused in the calculation; kept for call-site clarity.
        schedule_history: List of ``{"effective_from": "YYYY-MM-DD", "days": ...}``
                          dicts (append-only, sorted by ``effective_from``).
        completions:      Dict keyed by ``"YYYY-MM-DD"`` with any truthy value.
        today:            ``datetime.date`` representing today in Asia/Jerusalem.
        window_days:      Number of days in the rolling grid (default 365).

    Returns::

        {
            "streak": int,
            "grid": [
                {"date": "YYYY-MM-DD", "state": "done"|"missed"|"not-scheduled"|"pending"},
                ...
            ]
        }

    DST safety: all arithmetic is on ``datetime.date`` objects (no time
    component) so Israel DST transitions are invisible.

    Streak rules (D-10/D-11/D-12/D-13):
    - ``done``          — scheduled + completion present.
    - ``missed``        — scheduled, no completion, and date < yesterday (confirmed).
    - ``not-scheduled`` — habit was not scheduled for this date.
    - ``pending``       — today or yesterday: no completion yet but still in the
                          backfill window (D-12); does NOT break the streak.

    Streak counting walks backward from today:
    - ``done``          → +1 to streak.
    - ``missed``        → pure reset: break immediately (streak stays at current total).
    - ``pending`` / ``not-scheduled`` → neutral; skip without incrementing or breaking.
    """
    from datetime import timedelta, date as _date

    if isinstance(today, str):
        today = _date.fromisoformat(today)
    yesterday = today - timedelta(days=1)
    grid = []

    for offset in range(window_days - 1, -1, -1):      # oldest → newest
        d = today - timedelta(days=offset)
        d_iso = d.isoformat()
        scheduled = _is_scheduled(d, schedule_history)

        if not scheduled:
            state = "not-scheduled"
        elif d == today:
            state = "done" if d_iso in completions else "pending"
        elif d == yesterday:
            # D-12: yesterday is still in the backfill window
            state = "done" if d_iso in completions else "pending"
        else:
            # d < yesterday: miss is confirmed (D-12)
            state = "done" if d_iso in completions else "missed"

        grid.append({"date": d_iso, "state": state})

    # Walk backward from today, counting consecutive done; stop on first confirmed miss
    streak = 0
    for cell in reversed(grid):
        if cell["state"] == "done":
            streak += 1
        elif cell["state"] == "missed":
            break           # pure reset (D-10): stop counting
        # "not-scheduled" and "pending" are neutral — pass without incrementing or breaking

    return {"streak": streak, "grid": grid}


class HabitStore:
    """Native habit/supplement store (Phase 28 — HABIT-01).

    Collection 1 — Definitions: ``habits/{habit_id}``
    Collection 2 — Completions: ``habit_completions/{YYYY-MM-DD}/records/{habit_id}``

    H-28-IV: dates are ALWAYS plain strings ("YYYY-MM-DD") — never Timestamps.
    Only ``updated_at`` uses SERVER_TIMESTAMP, stripped by _jsonsafe_doc on reads.

    Read discipline:
        list_active / get / get_completions_for_date / get_pending_today /
        get_history / get_summary never raise — return [] / None / {} on any
        Firestore error (logger.warning with exc_info=True).

    Write discipline:
        create / update / soft_delete / restore / delete / log_completion
        re-raise after logger.error so callers know the operation failed.

    Phase 28 — HABIT-01/03/04.
    """

    _COLLECTION = "habits"
    _COMPLETIONS = "habit_completions"

    def __init__(self, project_id: str, database: str = "(default)") -> None:
        self._client = _make_firestore_client(project_id, database)
        self._col = self._client.collection(self._COLLECTION)

    # ------------------------------------------------------------------ #
    # Definition CRUD                                                     #
    # ------------------------------------------------------------------ #

    def create(self, habit: dict) -> dict:
        """Create a new habit/supplement definition.

        Accepts a ``habit`` dict with at minimum ``name`` and ``type``.
        Optional top-level ``days`` field seeds ``schedule_history`` if
        ``schedule_history`` is not already provided.

        Returns the stored document WITHOUT ``updated_at`` (H-28-IV).
        Re-raises on Firestore failure.
        """
        import uuid
        from datetime import datetime, timezone

        habit_id = habit.get("id") or uuid.uuid4().hex
        today_iso = datetime.now(timezone.utc).date().isoformat()

        # D-19: seed schedule_history from days if not already supplied
        if "schedule_history" in habit:
            schedule_history = habit["schedule_history"]
        else:
            days = habit.get("days", "daily")
            schedule_history = [{"effective_from": today_iso, "days": days}]

        # Build payload; strip caller-provided top-level "days" (it lives in schedule_history)
        base = {k: v for k, v in habit.items() if k not in ("id", "days", "schedule_history")}
        payload = {
            "slot": "Morning",
            "status": "active",
            **base,
            "id": habit_id,
            "schedule_history": schedule_history,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "updated_at": firestore.SERVER_TIMESTAMP,
        }
        try:
            self._col.document(habit_id).set(payload)
        except Exception:
            logger.error("HabitStore.create failed (name=%r)", habit.get("name"), exc_info=True)
            raise
        # Return without updated_at (H-28-IV / T-27-IV precedent)
        return {k: v for k, v in payload.items() if k != "updated_at"}

    def get(self, habit_id: str) -> dict | None:
        """Return the habit definition doc, or None if not found. Never raises."""
        try:
            snap = self._col.document(habit_id).get()
            if not snap.exists:
                return None
            return _jsonsafe_doc(snap.to_dict() or {})
        except Exception:
            logger.warning("HabitStore.get(%r) failed", habit_id, exc_info=True)
            return None

    def reclaim_stale_deletions(self, *, older_than_seconds: int = 120) -> int:
        """Self-heal habits stranded in ``status == 'completing'`` (WR-02).

        The undo-toast hard-delete is a *client-side* 4s timer; if the user
        navigates away or closes the PWA during the undo window the timer never
        fires, leaving the doc invisible (filtered from :meth:`list_active`) yet
        never deleted and with no UI path to restore or remove it.

        This finishes the delete the user intended for any ``completing`` doc
        whose ``updated_at`` is older than ``older_than_seconds`` — chosen well
        above the 4s undo window so a legitimately-pending undo is never
        reclaimed early. Returns the number of docs reclaimed. Never raises.
        """
        from datetime import datetime, timezone, timedelta
        reclaimed = 0
        try:
            from google.cloud.firestore_v1.base_query import FieldFilter
            cutoff = datetime.now(timezone.utc) - timedelta(seconds=older_than_seconds)
            query = self._col.where(filter=FieldFilter("status", "==", "completing"))
            for snap in query.stream():
                data = snap.to_dict() or {}
                updated = data.get("updated_at")
                # updated_at is a Firestore timestamp (tz-aware datetime). A
                # missing/unparseable value means we can't prove the doc is
                # still inside its undo window, so reclaim it rather than risk a
                # permanent strand.
                stale = True
                if isinstance(updated, datetime):
                    aware = updated if updated.tzinfo else updated.replace(tzinfo=timezone.utc)
                    stale = aware < cutoff
                if stale:
                    self.delete(snap.id)
                    reclaimed += 1
        except Exception:
            logger.warning("HabitStore.reclaim_stale_deletions failed", exc_info=True)
        return reclaimed

    def list_active(self) -> list[dict]:
        """Return all habits/supplements with ``status == 'active'``.

        Best-effort self-heals stranded soft-deletes first (WR-02), then lists.
        Never raises — returns [] on any Firestore error.
        """
        # Reclaim never raises; run it before listing so a zombie 'completing'
        # doc is cleaned the next time the Habits page loads.
        self.reclaim_stale_deletions()
        try:
            from google.cloud.firestore_v1.base_query import FieldFilter
            query = self._col.where(filter=FieldFilter("status", "==", "active"))
            return [_jsonsafe_doc(snap.to_dict() or {}) for snap in query.stream()]
        except Exception:
            logger.warning("HabitStore.list_active failed", exc_info=True)
            return []

    def update(self, habit_id: str, fields: dict) -> dict | None:
        """PATCH fields onto the habit definition.

        Schedule changes (``days`` key in ``fields``) are applied forward-only
        via a new ``schedule_history`` revision (D-19 / Pitfall 7): the current
        ``schedule_history`` is read, a new ``{"effective_from": today_iso, "days": ...}``
        entry is appended, and the combined list is written back.  The top-level
        ``days`` key is never stored as a direct field.

        Re-raises on Firestore failure.
        """
        from datetime import datetime, timezone
        try:
            update_payload: dict = {
                k: v for k, v in fields.items() if k != "days"
            }
            update_payload["updated_at"] = firestore.SERVER_TIMESTAMP

            if "days" in fields:
                today_iso = datetime.now(timezone.utc).date().isoformat()
                # Read-modify-write: append new revision
                snap = self._col.document(habit_id).get()
                existing = (snap.to_dict() or {}) if snap.exists else {}
                current_history = existing.get("schedule_history", [])
                new_revision = {"effective_from": today_iso, "days": fields["days"]}
                update_payload["schedule_history"] = current_history + [new_revision]

            self._col.document(habit_id).update(update_payload)
        except Exception:
            logger.error("HabitStore.update(%r) failed", habit_id, exc_info=True)
            raise
        return self.get(habit_id)

    def soft_delete(self, habit_id: str) -> None:
        """Set ``status='completing'`` (soft-delete for undo-toast window).

        Re-raises on failure.
        """
        try:
            self._col.document(habit_id).update({
                "status": "completing",
                "updated_at": firestore.SERVER_TIMESTAMP,
            })
        except Exception:
            logger.error("HabitStore.soft_delete(%r) failed", habit_id, exc_info=True)
            raise

    def restore(self, habit_id: str) -> None:
        """Revert a soft-delete by setting ``status='active'``.

        Re-raises on failure.
        """
        try:
            self._col.document(habit_id).update({
                "status": "active",
                "updated_at": firestore.SERVER_TIMESTAMP,
            })
        except Exception:
            logger.error("HabitStore.restore(%r) failed", habit_id, exc_info=True)
            raise

    def delete(self, habit_id: str) -> None:
        """Hard-delete the definition AND all completion records for this habit.

        Uses a Firestore collection group query to find all ``records``
        subcollection docs with ``habit_id == habit_id``, deletes them in a
        batch, then deletes the definition doc.

        Acceptable at personal scale (Open Question 1 — at most ~365 completion
        records per habit).  Re-raises on failure.
        """
        try:
            from google.cloud.firestore_v1.base_query import FieldFilter
            records_query = (
                self._client.collection_group("records")
                .where(filter=FieldFilter("habit_id", "==", habit_id))
            )
            batch = self._client.batch()
            for snap in records_query.stream():
                batch.delete(snap.reference)
            batch.commit()
            self._col.document(habit_id).delete()
        except Exception:
            logger.error("HabitStore.delete(%r) failed", habit_id, exc_info=True)
            raise

    # ------------------------------------------------------------------ #
    # Completion log                                                       #
    # ------------------------------------------------------------------ #

    def log_completion(
        self,
        date_str: str,
        habit_id: str,
        done: bool,
        dose_taken: str | None = None,
    ) -> None:
        """Idempotent check-off toggle (D-07).

        If ``done=True``: write/merge a completion record at
        ``habit_completions/{date_str}/records/{habit_id}`` recording
        ``dose_taken`` (D-09) and ``logged_at`` as a plain ISO string (H-28-IV).

        If ``done=False``: delete the record for un-check.

        Re-raises on Firestore write/delete failure.
        """
        from datetime import datetime, timezone
        doc_ref = (
            self._client.collection(self._COMPLETIONS)
            .document(date_str)
            .collection("records")
            .document(habit_id)
        )
        if not done:
            try:
                doc_ref.delete()
            except Exception:
                logger.error(
                    "HabitStore.log_completion: delete failed (%r, %r)",
                    date_str, habit_id, exc_info=True,
                )
                raise
            return

        payload = {
            "habit_id": habit_id,
            "date": date_str,                               # plain string (H-28-IV)
            "done": True,
            "dose_taken": dose_taken,
            "logged_at": datetime.now(timezone.utc).isoformat(),   # plain ISO string
            "updated_at": firestore.SERVER_TIMESTAMP,
        }
        try:
            doc_ref.set(payload, merge=True)
        except Exception:
            logger.error(
                "HabitStore.log_completion failed (%r, %r)",
                date_str, habit_id, exc_info=True,
            )
            raise

    def get_completions_for_date(self, date_str: str) -> dict:
        """Return ``{habit_id: completion_doc}`` for a date.

        All docs pass through ``_jsonsafe_doc`` so the result round-trips
        through ``json.dumps`` (Pitfall 1 — DatetimeWithNanoseconds guard).

        Never raises — returns {} on any Firestore error.
        """
        try:
            snaps = (
                self._client.collection(self._COMPLETIONS)
                .document(date_str)
                .collection("records")
                .stream()
            )
            return {
                snap.id: _jsonsafe_doc(snap.to_dict() or {})
                for snap in snaps
            }
        except Exception:
            logger.warning(
                "HabitStore.get_completions_for_date(%r) failed", date_str, exc_info=True
            )
            return {}

    # ------------------------------------------------------------------ #
    # Read helpers                                                         #
    # ------------------------------------------------------------------ #

    def get_pending_today(self, today_iso: str) -> list[dict]:
        """Return active habits scheduled for today that have not been completed.

        Each item in the result has ``streak`` (from ``compute_streak_and_grid``)
        and the habit's ``dose`` attached.

        Never raises — returns [] on error.
        """
        from datetime import date as _date
        try:
            today = _date.fromisoformat(today_iso)
            active = self.list_active()
            completions_today = self.get_completions_for_date(today_iso)

            pending = []
            for habit in active:
                schedule_history = habit.get("schedule_history", [])
                if not _is_scheduled(today, schedule_history):
                    continue
                if habit["id"] in completions_today:
                    continue
                # Fetch history for streak (acceptable at personal scale)
                history = self.get_history(habit["id"], today_iso)
                pending.append({
                    **habit,
                    "streak": history["streak"],
                })
            return pending
        except Exception:
            logger.warning("HabitStore.get_pending_today(%r) failed", today_iso, exc_info=True)
            return []

    def get_history(self, habit_id: str, today_iso: str, window_days: int = 365) -> dict:
        """Return ``compute_streak_and_grid`` output for ``habit_id``.

        Fetches all completion records via a collection group query on
        ``records`` subcollection, keyed by ``habit_id``.

        Never raises — returns ``{"streak": 0, "grid": []}`` on error.
        """
        from datetime import date as _date
        try:
            today = _date.fromisoformat(today_iso)
            habit = self.get(habit_id)
            if not habit:
                return {"streak": 0, "grid": []}
            schedule_history = habit.get("schedule_history", [])

            # Fetch all completion records for this habit across all dates
            try:
                from google.cloud.firestore_v1.base_query import FieldFilter
                records_query = (
                    self._client.collection_group("records")
                    .where(filter=FieldFilter("habit_id", "==", habit_id))
                )
                completions: dict = {}
                for snap in records_query.stream():
                    d = _jsonsafe_doc(snap.to_dict() or {})
                    date_key = d.get("date")
                    if date_key:
                        completions[date_key] = d
            except Exception:
                # WR-05: this must stay non-fatal (get_summary / get_pending_today
                # run inside the autonomous tick and must never crash it), but a
                # failure here silently yields streak 0 + an empty grid for EVERY
                # habit — so log LOUDLY and actionably. The usual cause is a
                # missing COLLECTION_GROUP index on records.habit_id (see
                # DEPLOYMENT.md §21). Falling back to an empty completion set.
                logger.error(
                    "HabitStore.get_history(%r) completions collection-group query "
                    "failed — streaks/grid will read as empty until fixed. If this is "
                    "FAILED_PRECONDITION, create the records.habit_id COLLECTION_GROUP "
                    "index (DEPLOYMENT.md §21).",
                    habit_id, exc_info=True,
                )
                completions = {}

            return compute_streak_and_grid(
                habit_id, schedule_history, completions, today, window_days
            )
        except Exception:
            logger.warning("HabitStore.get_history(%r) failed", habit_id, exc_info=True)
            return {"streak": 0, "grid": []}

    def get_summary(self, today_iso: str) -> dict:
        """Return ``{pending_today: int, streak_leaders: list}`` for the GlanceRail.

        ``streak_leaders`` contains up to 4 active habits sorted by descending
        streak (``[{id, name, streak}]``).

        Never raises — returns ``{"pending_today": 0, "streak_leaders": []}`` on error.
        """
        try:
            pending = self.get_pending_today(today_iso)
            active = self.list_active()

            streak_leaders = []
            for habit in active:
                history = self.get_history(habit["id"], today_iso)
                streak_leaders.append({
                    "id": habit["id"],
                    "name": habit.get("name", ""),
                    "streak": history["streak"],
                })

            streak_leaders.sort(key=lambda x: x["streak"], reverse=True)

            return {
                "pending_today": len(pending),
                "streak_leaders": streak_leaders[:4],
            }
        except Exception:
            logger.warning("HabitStore.get_summary(%r) failed", today_iso, exc_info=True)
            return {"pending_today": 0, "streak_leaders": []}


class PushSubscriptionStore:
    """Web Push subscription registry — multi-device from day one (D-17).

    Collection: ``push_subscriptions``
    Document ID: ``sha256(endpoint).hexdigest()[:32]`` — the endpoint itself
    is too long/unsafe to use directly as a Firestore doc id, and hashing it
    gives an idempotent, deterministic key so re-subscribing the same
    browser/device endpoint always lands on the same doc (merge=True).

    Read discipline:
        list_all never raises — returns [] on any Firestore error, each doc
        passed through _jsonsafe_doc so SERVER_TIMESTAMP fields round-trip
        through json.dumps.

    Write discipline:
        upsert / delete / record_success / record_failure re-raise on
        Firestore failure after logger.error, so `core/push_sender.py`'s
        fan-out loop knows a write did not land.

    Phase 29 — PUSH-01.
    """

    _COLLECTION = "push_subscriptions"

    def __init__(self, project_id: str, database: str = "(default)") -> None:
        self._client = _make_firestore_client(project_id, database)
        self._col = self._client.collection(self._COLLECTION)

    @staticmethod
    def _doc_id(endpoint: str) -> str:
        import hashlib
        return hashlib.sha256(endpoint.encode()).hexdigest()[:32]

    def upsert(self, sub_json: dict, user_agent: str = "") -> None:
        """Idempotent write keyed on sha256(endpoint). Re-raises on failure.

        Args:
            sub_json: Browser PushSubscription JSON — must include a truthy
                ``endpoint`` and a ``keys`` dict ({p256dh, auth}).
            user_agent: Optional device/browser identifier for diagnostics.

        Raises:
            Exception: Re-raises any Firestore write failure after logging.
        """
        endpoint = sub_json.get("endpoint", "")
        doc_id = self._doc_id(endpoint)
        try:
            self._col.document(doc_id).set(
                {
                    "endpoint": endpoint,
                    "keys": sub_json.get("keys", {}),
                    "user_agent": user_agent,
                    "created_at": firestore.SERVER_TIMESTAMP,
                    "last_validated_at": firestore.SERVER_TIMESTAMP,
                },
                merge=True,
            )
        except Exception:
            logger.error("PushSubscriptionStore.upsert(%r) failed", endpoint, exc_info=True)
            raise

    def list_all(self) -> list[dict]:
        """Return every subscription doc, json-safe. Never raises — [] on error."""
        try:
            return [_jsonsafe_doc(snap.to_dict() or {}) for snap in self._col.stream()]
        except Exception:
            logger.warning("PushSubscriptionStore.list_all() failed", exc_info=True)
            return []

    def delete(self, endpoint: str) -> None:
        """Delete the subscription doc for `endpoint`. Re-raises on failure."""
        doc_id = self._doc_id(endpoint)
        try:
            self._col.document(doc_id).delete()
        except Exception:
            logger.error("PushSubscriptionStore.delete(%r) failed", endpoint, exc_info=True)
            raise

    def record_success(self, endpoint: str) -> None:
        """Merge-write a successful delivery timestamp and clear failure_count."""
        from datetime import datetime, timezone
        doc_id = self._doc_id(endpoint)
        try:
            self._col.document(doc_id).set(
                {
                    "last_success_at": datetime.now(timezone.utc),
                    "failure_count": 0,
                },
                merge=True,
            )
        except Exception:
            logger.error("PushSubscriptionStore.record_success(%r) failed", endpoint, exc_info=True)
            raise

    def record_failure(self, endpoint: str, error: str) -> None:
        """Merge-write the last error and increment failure_count."""
        doc_id = self._doc_id(endpoint)
        try:
            self._col.document(doc_id).set(
                {
                    "last_error": str(error),
                    "failure_count": firestore.Increment(1),
                },
                merge=True,
            )
        except Exception:
            logger.error("PushSubscriptionStore.record_failure(%r) failed", endpoint, exc_info=True)
            raise


class HubSettingsStore:
    """Runtime Telegram-mirror flag + push transition state (D-08/D-09/D-14).

    Config doc lives at collection='config', document='hub_settings'. This is
    a RUNTIME Firestore toggle, not an env var — Klaus (via the
    `toggle_telegram_mirror` tool) and the /api/settings route both mutate it.

    Default `telegram_mirror_enabled` is True (mirror ON) — Telegram keeps
    receiving every message until Amit has run the hub with push for at
    least a week (D-08/D-09).

    No `chat_visible_until` field here: the D-02 in-hub chat-visibility gate
    is an in-process module variable in core/scheduled_message.py (RESEARCH
    A5, single Cloud Run instance) — persisting it here would always be
    stale/misleading across instance restarts.

    Phase 29 — PUSH-03.
    """

    _COLLECTION = "config"
    _DOCUMENT = "hub_settings"

    _DEFAULTS: dict = {
        "telegram_mirror_enabled": True,
        "push_enabled_at": None,
    }

    def __init__(self, project_id: str, database: str = "(default)") -> None:
        self._client = _make_firestore_client(project_id, database)
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


def _smoke_test() -> int:
    """Verify Firestore connectivity. Returns 0 on success, 1 on failure.

    Run with:  python -m memory.firestore_db
    """
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    load_dotenv(override=True)

    project_id = os.getenv("GCP_PROJECT_ID")
    if not project_id:
        logger.error("GCP_PROJECT_ID is not set — check your .env file")
        return 1

    database = os.getenv("FIRESTORE_DATABASE", "(default)")
    print(f"Connecting to Firestore project={project_id!r} database={database!r} …")
    try:
        client = _make_firestore_client(project_id, database)
        # Lightweight connectivity check — list collections (returns immediately).
        _ = list(client.collections())
        print("Firestore connection OK.")
    except GoogleAPICallError as exc:
        logger.error("Smoke test failed: %s", exc)
        return 1

    print("Smoke test passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(_smoke_test())
