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


def record_cron_run(job_id: str, ok: bool) -> None:
    """Write a liveness ledger entry to heartbeat_runs/{job_id}.

    Called once per cron-endpoint invocation. On success, consecutive_failures
    is reset to 0; on failure it is incremented. Never raises.
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
    """Read/write the user's static profile + scheduling rules in Firestore."""

    def __init__(self, project_id: str, document_path: str = "users/amit") -> None:
        self.project_id = project_id
        self.document_path = document_path

    def load(self) -> dict:
        """Return the full user profile as a plain dict."""
        raise NotImplementedError("stub — Phase 5")

    def update(self, patch: dict) -> None:
        """Merge `patch` into the stored profile document."""
        raise NotImplementedError("stub — Phase 5")


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
