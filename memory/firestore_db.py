"""Firestore-backed state storage.

Two responsibilities (per `docs/TECHNICAL_PLAN.md` §1 and §3.4):

1. `FirestoreQueue` — write-side of the cloud-to-local Things 3 bridge.
   The cloud agent appends task documents here; the local Mac poller
   (see `local_mac/things_poller.py`) drains them.

2. `UserProfileStore` — read/write static user configuration (routines,
   travel buffers, hardcoded rules from `docs/USER.md`) so they're not
   baked into source code.

Phase 4 implements `FirestoreQueue`. `UserProfileStore` remains a stub.
"""
from __future__ import annotations

import logging
import os

from dotenv import load_dotenv
from google.cloud import firestore
from google.api_core.exceptions import GoogleAPICallError

logger = logging.getLogger(__name__)


class FirestoreQueue:
    """Cloud queue of pending Things 3 to-dos.

    Each enqueued document has the shape:
        {
            "title": str,
            "notes": str,
            "deadline": ISO8601 str | None,
            "tags": list[str],
            "status": "pending" | "consumed",
            "created_at": Firestore server timestamp,
            "consumed_at": Firestore server timestamp | None,
        }
    The local poller marks documents as "consumed" once injected into Things 3.
    """

    def __init__(self, project_id: str, collection: str = "things_queue",
                 database: str = "(default)") -> None:
        """
        Args:
            project_id: GCP project ID.
            collection: Firestore collection name for the queue.
            database: Firestore database name. Defaults to "(default)" but can be
                overridden via FIRESTORE_DATABASE env var (e.g. "klaus-firestore").

        Auth:
            Uses gcloud application-default credentials (run `gcloud auth
            application-default login` once). If FIRESTORE_CREDENTIALS env var
            is set to a service-account JSON path, that is used instead.
        """
        self.project_id = project_id
        self.collection = collection

        # WHY eager init: the client performs no network I/O at construction time;
        # credential resolution is deferred to the first actual API call.
        credentials_path = os.getenv("FIRESTORE_CREDENTIALS")
        if credentials_path:
            from google.oauth2 import service_account
            credentials = service_account.Credentials.from_service_account_file(
                credentials_path,
                scopes=["https://www.googleapis.com/auth/datastore"],
            )
            self._client = firestore.Client(
                project=project_id, credentials=credentials, database=database,
            )
        else:
            # WHY database param: Firestore databases are not always named "(default)".
            # The Klaus project uses "klaus-firestore" — set FIRESTORE_DATABASE accordingly.
            self._client = firestore.Client(project=project_id, database=database)

        self._col = self._client.collection(collection)

    def enqueue(self, title: str, notes: str = "", deadline: str | None = None,
                reminder: str | None = None,
                tags: list[str] | None = None) -> str:
        """Append a task to the cloud queue.

        Args:
            title: Task title shown in Things 3.
            notes: Optional notes body.
            deadline: Optional ISO 8601 date string (e.g. "2025-12-31").
            reminder: Optional datetime string (YYYY-MM-DDTHH:MM, local time). The Mac
                poller converts this to an AppleScript `activation date` so Things 3
                fires a notification.
            tags: Optional list of Things 3 tag names.

        Returns:
            The newly created Firestore document ID.

        Raises:
            GoogleAPICallError: If the Firestore write fails.
        """
        payload = {
            "title": title,
            "notes": notes or "",
            "deadline": deadline,
            "reminder": reminder,
            "tags": list(tags) if tags else [],
            "status": "pending",
            # WHY SERVER_TIMESTAMP: lets Firestore set creation time server-side,
            # avoiding clock skew between the cloud agent and the Mac poller.
            "created_at": firestore.SERVER_TIMESTAMP,
        }
        try:
            # add() auto-generates a document ID and returns (update_time, doc_ref).
            _, doc_ref = self._col.add(payload)
        except GoogleAPICallError:
            logger.error("FirestoreQueue.enqueue failed for title=%r", title)
            raise
        return doc_ref.id

    def fetch_pending(self, limit: int = 25) -> list[dict]:
        """Read up to `limit` pending tasks, ordered oldest-first.

        Each returned dict includes the document's own "doc_id" key so the
        caller can pass it back to mark_consumed without a separate lookup.

        Args:
            limit: Maximum number of documents to fetch.

        Returns:
            List of task dicts, each containing all stored fields plus "doc_id".
            Returns an empty list on Firestore error so the poller can retry.

        Note:
            WHY sort in Python rather than Firestore order_by: a Firestore query
            combining where() + order_by() requires a composite index. For a
            single-user queue that rarely holds more than a handful of items,
            fetching all pending docs and sorting in Python is equivalent and
            avoids the one-time index setup friction.
        """
        try:
            from google.cloud.firestore_v1.base_query import FieldFilter
            query = (
                self._col
                .where(filter=FieldFilter("status", "==", "pending"))
                .limit(limit)
            )
            snapshots = query.stream()
        except GoogleAPICallError:
            logger.error("FirestoreQueue.fetch_pending failed — will retry on next poll")
            return []

        results = []
        for snap in snapshots:
            data = snap.to_dict() or {}
            data["doc_id"] = snap.id
            results.append(data)

        # Sort oldest-first using created_at; docs without the field sort last.
        results.sort(key=lambda d: d.get("created_at") or 0)
        return results

    def mark_consumed(self, doc_id: str) -> None:
        """Flip a task's status to "consumed" after local injection succeeds.

        Args:
            doc_id: Firestore document ID returned by enqueue or fetch_pending.

        Raises:
            GoogleAPICallError: If the Firestore update fails.
        """
        try:
            self._col.document(doc_id).update({
                "status": "consumed",
                # WHY SERVER_TIMESTAMP: consistent with created_at; lets us audit
                # the injector latency (consumed_at - created_at) in the console.
                "consumed_at": firestore.SERVER_TIMESTAMP,
            })
        except GoogleAPICallError:
            logger.error("FirestoreQueue.mark_consumed(%r) failed", doc_id)
            raise


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
        credentials_path = os.getenv("FIRESTORE_CREDENTIALS")
        if credentials_path:
            from google.oauth2 import service_account
            credentials = service_account.Credentials.from_service_account_file(
                credentials_path,
                scopes=["https://www.googleapis.com/auth/datastore"],
            )
            self._client = firestore.Client(
                project=project_id, credentials=credentials, database=database,
            )
        else:
            self._client = firestore.Client(project=project_id, database=database)

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
        credentials_path = os.getenv("FIRESTORE_CREDENTIALS")
        if credentials_path:
            from google.oauth2 import service_account
            credentials = service_account.Credentials.from_service_account_file(
                credentials_path,
                scopes=["https://www.googleapis.com/auth/datastore"],
            )
            self._client = firestore.Client(
                project=project_id, credentials=credentials, database=database,
            )
        else:
            self._client = firestore.Client(project=project_id, database=database)

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


def _smoke_test() -> int:
    """Round-trip a document through the queue. Returns 0 on success, 1 on failure.

    Run with:  python -m memory.firestore_db
    """
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    # WHY override=True: shell-exported vars silently shadow .env without this.
    load_dotenv(override=True)

    project_id = os.getenv("GCP_PROJECT_ID")
    if not project_id:
        logger.error("GCP_PROJECT_ID is not set — check your .env file")
        return 1

    database = os.getenv("FIRESTORE_DATABASE", "(default)")
    print(f"Connecting to Firestore project={project_id!r} database={database!r} …")
    try:
        queue = FirestoreQueue(project_id, database=database)

        # --- Enqueue ---
        doc_id = queue.enqueue(
            title="smoke test todo",
            notes="created by memory.firestore_db._smoke_test",
            deadline="2099-12-31",
            tags=["smoke"],
        )
        print(f"  enqueued → doc_id={doc_id!r}")

        # --- Fetch pending ---
        pending = queue.fetch_pending(limit=5)
        match = [d for d in pending if d.get("doc_id") == doc_id]
        if not match:
            print(f"  WARNING: enqueued doc not found in fetch_pending (index may not exist yet)")
        else:
            print(f"  fetch_pending → found {len(pending)} pending doc(s)")

        # --- Mark consumed ---
        queue.mark_consumed(doc_id)
        print(f"  mark_consumed → done")

    except GoogleAPICallError as exc:
        logger.error("Smoke test failed: %s", exc)
        return 1

    print("Smoke test passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(_smoke_test())
