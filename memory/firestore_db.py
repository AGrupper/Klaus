"""Firestore-backed state storage.

Three store classes (per `docs/TECHNICAL_PLAN.md` §1 and §3.4):

1. `UserProfileStore` — read/write static user configuration (stub, Phase 5).
2. `RosterStore` — five_fingers_roster collection; one doc per teammate.
3. `AttendanceStore` — five_fingers_practices collection; one doc per practice day.

Note: FirestoreQueue (the Things 3 task queue) was removed when the task backend
was migrated to TickTick Open API (see mcp_tools/ticktick_tool.py).
"""
from __future__ import annotations

import logging
import os

from dotenv import load_dotenv
from google.cloud import firestore
from google.api_core.exceptions import GoogleAPICallError

logger = logging.getLogger(__name__)


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


class RosterStore:
    """Manages the five_fingers_roster Firestore collection.

    One document per teammate. Documents are soft-deleted via the ``active``
    flag — hard deletes are never performed so attendance history remains intact.
    """

    def __init__(self, project_id: str, collection: str = "five_fingers_roster",
                 database: str = "(default)") -> None:
        """
        Args:
            project_id: GCP project ID.
            collection: Firestore collection name for the roster.
            database: Firestore database name.

        Auth:
            Uses gcloud application-default credentials. If FIRESTORE_CREDENTIALS
            env var is set to a service-account JSON path, that is used instead.
        """
        self._client = _make_firestore_client(project_id, database)
        self._col = self._client.collection(collection)

    def add(self, name: str, phone_e164: str, nickname: str | None = None,
            notes: str | None = None) -> str:
        """Create a new roster entry.

        Args:
            name: Display name (Hebrew or English).
            phone_e164: Already-normalised E.164 number (e.g. ``"972521234567"``).
            nickname: Used in outbound messages when set; falls back to ``name``.
            notes: Free-text notes.

        Returns:
            The auto-generated Firestore document ID.

        Raises:
            GoogleAPICallError: If the Firestore write fails.
        """
        payload = {
            "name": name,
            "nickname": nickname,
            "phone_e164": phone_e164,
            "notes": notes,
            "active": True,
            "created_at": firestore.SERVER_TIMESTAMP,
            "updated_at": firestore.SERVER_TIMESTAMP,
        }
        try:
            _, doc_ref = self._col.add(payload)
        except GoogleAPICallError:
            logger.error("RosterStore.add failed for name=%r", name)
            raise
        return doc_ref.id

    def list_active(self) -> list[dict]:
        """Return all active roster entries.

        Returns:
            List of dicts, each with all stored fields plus ``"doc_id"``.
        """
        try:
            from google.cloud.firestore_v1.base_query import FieldFilter
            snapshots = (
                self._col
                .where(filter=FieldFilter("active", "==", True))
                .stream()
            )
        except GoogleAPICallError:
            logger.error("RosterStore.list_active failed")
            return []

        results = []
        for snap in snapshots:
            data = snap.to_dict() or {}
            data["doc_id"] = snap.id
            results.append(data)
        return results

    def get(self, doc_id: str) -> dict | None:
        """Return a single roster entry by document ID.

        Args:
            doc_id: Firestore document ID.

        Returns:
            Dict with all fields plus ``"doc_id"``, or ``None`` if not found or
            inactive.

        Returns ``None`` if the document does not exist OR if the player has
        been deactivated. Callers that need to distinguish these cases must
        query the collection directly.
        """
        try:
            snap = self._col.document(doc_id).get()
        except GoogleAPICallError:
            logger.error("RosterStore.get(%r) failed", doc_id)
            raise
        if not snap.exists:
            return None
        data = snap.to_dict() or {}
        if not data.get("active", False):
            return None
        data["doc_id"] = snap.id
        return data

    def deactivate(self, doc_id: str) -> None:
        """Soft-delete a roster entry by setting ``active=False``.

        Args:
            doc_id: Firestore document ID.

        Raises:
            GoogleAPICallError: If the Firestore update fails.
        """
        try:
            self._col.document(doc_id).update({
                "active": False,
                "updated_at": firestore.SERVER_TIMESTAMP,
            })
        except GoogleAPICallError:
            logger.error("RosterStore.deactivate(%r) failed", doc_id)
            raise

    def update(self, doc_id: str, **fields) -> None:
        """Merge arbitrary fields into an existing roster document.

        Always sets ``updated_at`` to the server timestamp.

        Args:
            doc_id: Firestore document ID.
            **fields: Any subset of the doc shape to overwrite.

        Raises:
            GoogleAPICallError: If the Firestore update fails.
        """
        fields["updated_at"] = firestore.SERVER_TIMESTAMP
        try:
            self._col.document(doc_id).update(fields)
        except GoogleAPICallError:
            logger.error("RosterStore.update(%r) failed", doc_id)
            raise


class AttendanceStore:
    """Manages the five_fingers_practices Firestore collection.

    One document per practice day, keyed by YYYY-MM-DD date string.
    """

    _VALID_STATUSES = {"came", "missed", "unknown"}

    def __init__(self, project_id: str, collection: str = "five_fingers_practices",
                 database: str = "(default)") -> None:
        """
        Args:
            project_id: GCP project ID.
            collection: Firestore collection name for practice records.
            database: Firestore database name.

        Auth:
            Uses gcloud application-default credentials. If FIRESTORE_CREDENTIALS
            env var is set to a service-account JSON path, that is used instead.
        """
        self._client = _make_firestore_client(project_id, database)
        self._col = self._client.collection(collection)

    def get_practice(self, date_str: str) -> dict | None:
        """Return the practice document for a given date.

        Args:
            date_str: YYYY-MM-DD date string (also the document ID).

        Returns:
            Dict with all fields plus ``"doc_id"``, or ``None`` if not found.

        Raises:
            GoogleAPICallError: If the Firestore read fails.
        """
        try:
            snap = self._col.document(date_str).get()
        except GoogleAPICallError:
            logger.error("AttendanceStore.get_practice(%r) failed", date_str)
            raise
        if not snap.exists:
            return None
        data = snap.to_dict() or {}
        data["doc_id"] = snap.id
        return data

    def upsert_practice(self, date_str: str, **fields) -> None:
        """Create or merge fields into the practice document for a date.

        Args:
            date_str: YYYY-MM-DD date string used as the document ID.
            **fields: Any subset of the practice doc shape to set or overwrite.

        Raises:
            GoogleAPICallError: If the Firestore write fails.
        """
        payload = {"practice_date": date_str, **fields}
        try:
            self._col.document(date_str).set(payload, merge=True)
        except GoogleAPICallError:
            logger.error("AttendanceStore.upsert_practice(%r) failed", date_str)
            raise

    def mark_attendance(self, date_str: str, roster_id: str, status: str) -> None:
        """Record whether a player came to or missed a practice.

        Args:
            date_str: YYYY-MM-DD practice date.
            roster_id: Firestore document ID from RosterStore.
            status: One of ``"came"``, ``"missed"``, or ``"unknown"``.

        Raises:
            ValueError: If ``status`` is not a recognised value.
            GoogleAPICallError: If the Firestore update fails.
        """
        if status not in self._VALID_STATUSES:
            raise ValueError(
                f"Invalid attendance status {status!r}; "
                f"must be one of {sorted(self._VALID_STATUSES)}"
            )
        try:
            self._col.document(date_str).update({f"attendance.{roster_id}": status})
        except GoogleAPICallError:
            logger.error(
                "AttendanceStore.mark_attendance(%r, %r) failed", date_str, roster_id
            )
            raise

    def add_pinged_pre(self, date_str: str, roster_ids: list[str]) -> None:
        """Atomically extend the pre-practice ping list without duplicating IDs.

        Args:
            date_str: YYYY-MM-DD practice date.
            roster_ids: Roster document IDs that were pinged.

        Raises:
            GoogleAPICallError: If the Firestore update fails.
        """
        try:
            self._col.document(date_str).update({
                "pinged_pre_practice": firestore.ArrayUnion(roster_ids),
            })
        except GoogleAPICallError:
            logger.error("AttendanceStore.add_pinged_pre(%r) failed", date_str)
            raise

    def add_pinged_post(self, date_str: str, roster_ids: list[str]) -> None:
        """Atomically extend the post-practice follow-up list without duplicating IDs.

        Args:
            date_str: YYYY-MM-DD practice date.
            roster_ids: Roster document IDs that were pinged.

        Raises:
            GoogleAPICallError: If the Firestore update fails.
        """
        try:
            self._col.document(date_str).update({
                "pinged_post_practice": firestore.ArrayUnion(roster_ids),
            })
        except GoogleAPICallError:
            logger.error("AttendanceStore.add_pinged_post(%r) failed", date_str)
            raise

    def recent_practices(self, n: int) -> list[dict]:
        """Return the most-recent practice documents, newest-first.

        Args:
            n: Maximum number of documents to return.

        Returns:
            List of practice dicts, each with all stored fields plus ``"doc_id"``.
            Returns an empty list on Firestore error.
        """
        try:
            # WHY stream() + sort in Python: five_fingers_practices will hold at most
            # a few hundred documents in a single-user context. Sorting by practice_date
            # in Python avoids a composite-index requirement.
            snapshots = self._col.stream()
        except GoogleAPICallError:
            logger.error("AttendanceStore.recent_practices failed")
            return []

        results = []
        for snap in snapshots:
            data = snap.to_dict() or {}
            data["doc_id"] = snap.id
            results.append(data)

        results.sort(key=lambda d: d.get("practice_date", ""), reverse=True)
        return results[:n]


class UserProfileStore:
    """Read/write the user's static profile + scheduling rules in Firestore.

    PHASE 19 (Plan 02): filled in (was a Phase-5 stub raising NotImplementedError).
    Mirrors SelfStateStore discipline (this module's `class SelfStateStore` below):
      - Reads NEVER raise — return {} on any error.
      - Writes (update) re-raise after logger.error, caller decides.
      - bootstrap_if_empty is a startup safety call — NEVER raises (Pitfall 7).
      - Every merge write stamps `updated_at: firestore.SERVER_TIMESTAMP`.

    Singleton document at collection='users', document='amit'.
    Scaffold fields seeded on first run:
        athletic_goals: []
        training_constraints: []
        recovery_preferences: {}
        schema_version: 1
    """

    _COLLECTION = "users"
    _DOCUMENT_ID = "amit"
    _SCAFFOLD = {
        "athletic_goals": [],
        "training_constraints": [],
        "recovery_preferences": {},
        "schema_version": 1,
    }

    def __init__(self, project_id: str, database: str = "(default)") -> None:
        self._client = _make_firestore_client(project_id, database)
        self._doc_ref = (
            self._client.collection(self._COLLECTION).document(self._DOCUMENT_ID)
        )

    def load(self) -> dict:
        """PROFILE-01: return the user profile dict. Returns {} on any error — never raises."""
        try:
            snap = self._doc_ref.get()
            if snap.exists:
                return snap.to_dict() or {}
            return {}
        except Exception:
            logger.warning("UserProfileStore.load() failed — returning empty", exc_info=True)
            return {}

    def update(self, patch: dict) -> None:
        """PROFILE-02: merge patch and stamp updated_at SERVER_TIMESTAMP. Re-raises on failure."""
        try:
            self._doc_ref.set(
                {**patch, "updated_at": firestore.SERVER_TIMESTAMP},
                merge=True,
            )
        except Exception:
            logger.error("UserProfileStore.update() failed", exc_info=True)
            raise

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
        total_in_tokens:   int   — sum of input tokens across all calls
        total_out_tokens:  int   — sum of output tokens across all calls
        total_cost_usd:    float — sum of compute_cost() results
        call_count:        int   — total number of calls
        {purpose}_calls:   int   — per-purpose call counter (e.g. "smart_calls", "worker_calls")
    """

    _COLLECTION = "llm_usage"

    def __init__(self, project_id: str, database: str = "(default)") -> None:
        self._client = _make_firestore_client(project_id, database)

    def record(self, model: str, purpose: str, in_tokens: int,
               out_tokens: int, cost: float) -> None:
        """Increment today's usage doc. Never raises."""
        try:
            from datetime import date
            today = date.today().isoformat()
            doc_ref = self._client.collection(self._COLLECTION).document(today)
            purpose_key = f"{purpose}_calls" if purpose else "unknown_calls"
            doc_ref.set(
                {
                    "date": today,
                    "total_in_tokens":  firestore.Increment(in_tokens),
                    "total_out_tokens": firestore.Increment(out_tokens),
                    "total_cost_usd":   firestore.Increment(cost),
                    "call_count":       firestore.Increment(1),
                    purpose_key:        firestore.Increment(1),
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

    def get(self) -> dict:
        """Return the self_state document. Returns {} on any error — never raises.

        This is intentionally broader than HeartbeatConfigStore.get() because
        SelfStateStore is injected into every prompt; a failure must never crash
        a conversation.
        """
        try:
            snap = self._doc_ref.get()
            return snap.to_dict() or {} if snap.exists else {}
        except Exception:
            logger.warning("SelfStateStore.get() failed — returning empty", exc_info=True)
            return {}

    def set(self, patch: dict) -> None:
        """Merge patch into the self_state document. Raises on failure (caller decides).

        Always appends updated_at SERVER_TIMESTAMP.
        """
        try:
            self._doc_ref.set(
                {**patch, "updated_at": firestore.SERVER_TIMESTAMP},
                merge=True,
            )
        except Exception:
            logger.error("SelfStateStore.set() failed", exc_info=True)
            raise

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

    def get(self, date_str: str) -> dict | None:
        """Return the journal doc for a date, or None. Never raises.

        Args:
            date_str: YYYY-MM-DD date key (Asia/Jerusalem calendar date).

        Returns:
            Dict with all stored fields plus ``date`` == date_str, or None
            if no entry exists for that date or if Firestore is unreachable.
        """
        try:
            snap = self._col.document(date_str).get()
            if not snap.exists:
                return None
            data = snap.to_dict() or {}
            data["date"] = snap.id
            return data
        except Exception:
            logger.warning("JournalStore.get(%r) failed", date_str, exc_info=True)
            return None

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

    def get_recent(self, n: int) -> list[dict]:
        """Return the most-recent n journal docs, newest-first. Returns [] on error.

        Uses stream() + Python sort rather than a Firestore order_by query —
        single-user, low-volume collection (< a few thousand docs lifetime),
        so no composite index is needed. Same approach as LLMUsageStore.summary.

        Args:
            n: Maximum number of entries to return.

        Returns:
            List of journal dicts (each with a ``date`` field), sorted by date
            descending, at most n elements. Empty list on any Firestore error.
        """
        try:
            snaps = list(self._col.stream())
        except Exception:
            logger.warning("JournalStore.get_recent failed", exc_info=True)
            return []
        results = []
        for snap in snaps:
            data = snap.to_dict() or {}
            data["date"] = snap.id
            results.append(data)
        results.sort(key=lambda d: d.get("date", ""), reverse=True)
        return results[:n]


class MealStore:
    """Per-date nutrition log persistence (Phase 19 — NUTR-02).

    Firestore path: ``meals/{YYYY-MM-DD}/timestamps/{source_id}``.

    The date-partitioned layout matches JournalStore's discipline (one
    document per calendar day) but uses a sub-collection of meal entries
    rather than a single doc — Lifesum can log many meals per day and
    each must round-trip through Fit + this store independently.

    Idempotency:
        ``source_id = "{dataStreamId}:{startTimeNanos}"`` (see
        ``mcp_tools/google_fit_tool._normalize_point``). Re-syncs land on
        the same doc with ``merge=True``, so Lifesum sync-timing variance
        cannot produce duplicate rows (Pitfall 2 mitigation).

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
            source_id: ``{dataStreamId}:{startTimeNanos}`` from Fit normalization.
            meal:      Normalized meal dict (see google_fit_tool._normalize_point).

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
            return sorted(
                (s.to_dict() for s in snaps),
                key=lambda d: d.get("timestamp", ""),
            )
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
