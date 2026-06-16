"""Firestore-backed conversation history store.

Persists per-user conversation history as a single Firestore document,
keyed by Telegram user ID. Survives Cloud Run scale-to-zero evictions.

Document layout:
    collection: conversations  (FIRESTORE_COLLECTION_CONVERSATIONS env var)
    doc id:     "<telegram_user_id>"   (string)
    fields:
        messages:    [{"role": "user"|"assistant", "content": str}, ...]
        updated_at:  Firestore server timestamp

The `messages` array is capped at `max_messages` entries (oldest are dropped
first). Writes are wrapped in a Firestore transaction to prevent lost updates
if two messages arrive near-simultaneously.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone

from google.api_core.exceptions import GoogleAPICallError
from google.cloud import firestore

logger = logging.getLogger(__name__)

# Default cap matches InMemoryConversationStore (50 turns × 2 messages).
_DEFAULT_MAX_MESSAGES = 100


@firestore.transactional
def _txn_append(
    transaction: firestore.Transaction,
    doc_ref: firestore.DocumentReference,
    role: str,
    content: str,
    max_messages: int,
    timeout_hours: int,
) -> None:
    """Transactional helper: read → append → truncate → write."""
    snapshot = doc_ref.get(transaction=transaction)
    doc_data: dict = (snapshot.to_dict() or {}) if snapshot.exists else {}
    updated_at = doc_data.get("updated_at")
    messages: list[dict] = list(doc_data.get("messages", []))
    session_start = int(doc_data.get("session_start_index", 0))
    # On a new session (idle beyond the timeout) start a fresh LLM-context window
    # WITHOUT deleting history: mark the boundary so the agent only sees the new
    # session via get(), while the hub can still display the whole thread via
    # get_full() (CR-02 — "one continuous conversation"). Telegram's bounded
    # context is unchanged: get() still returns only the active session.
    if updated_at and datetime.now(timezone.utc) - updated_at > timedelta(hours=timeout_hours):
        session_start = len(messages)
    messages.append({"role": role, "content": content})
    if len(messages) > max_messages:
        # WHY: keep the newest messages — they carry the most relevant context.
        drop = len(messages) - max_messages
        messages = messages[drop:]
        session_start = max(0, session_start - drop)
    transaction.set(
        doc_ref,
        {
            "messages": messages,
            "session_start_index": session_start,
            "updated_at": firestore.SERVER_TIMESTAMP,
        },
    )


class FirestoreConversationStore:
    """Firestore-backed per-user conversation history.

    Implements the same `get` / `append` / `clear` interface as
    `InMemoryConversationStore` so the orchestrator can use either
    backend interchangeably.

    Auth:
        If FIRESTORE_CREDENTIALS env var points to a service-account JSON
        file, that is used (local dev with a downloaded key). Otherwise,
        Application Default Credentials are used (Cloud Run metadata server).
    """

    def __init__(
        self,
        project_id: str,
        collection: str = "conversations",
        database: str = "(default)",
        max_messages: int = _DEFAULT_MAX_MESSAGES,
    ) -> None:
        """
        Args:
            project_id:   GCP project ID.
            collection:   Firestore collection name for conversation docs.
            database:     Firestore database name (e.g. "klaus-firestore").
            max_messages: Hard cap on stored messages per user.
        """
        self._max_messages = max_messages
        self._timeout_hours = int(os.getenv("SESSION_TIMEOUT_HOURS", "6"))

        credentials_path = os.getenv("FIRESTORE_CREDENTIALS")
        if credentials_path:
            from google.oauth2 import service_account
            creds = service_account.Credentials.from_service_account_file(
                credentials_path,
                scopes=["https://www.googleapis.com/auth/datastore"],
            )
            self._client = firestore.Client(
                project=project_id, credentials=creds, database=database,
            )
        else:
            # Cloud Run: ADC from metadata server.
            self._client = firestore.Client(project=project_id, database=database)

        self._col = self._client.collection(collection)

    # ------------------------------------------------------------------ #
    # ConversationStore protocol                                         #
    # ------------------------------------------------------------------ #

    def get(self, user_id: int) -> list[dict]:
        """Return the stored message list for user_id, or [] if none."""
        doc_ref = self._col.document(str(user_id))
        try:
            snapshot = doc_ref.get()
        except GoogleAPICallError:
            logger.warning(
                "FirestoreConversationStore.get failed for user_id=%d; "
                "returning empty history.",
                user_id,
            )
            return []
        if not snapshot.exists:
            return []
        doc_data = snapshot.to_dict() or {}
        updated_at = doc_data.get("updated_at")
        # Idle beyond the timeout → the active LLM-context window is empty until
        # the next append opens a fresh session (preserves the bounded-context
        # behaviour the agent relies on). Full history is still available via
        # get_full() for hub display (CR-02).
        if updated_at and datetime.now(timezone.utc) - updated_at > timedelta(hours=self._timeout_hours):
            return []
        messages = list(doc_data.get("messages", []))
        session_start = int(doc_data.get("session_start_index", 0))
        return messages[session_start:]

    def get_full(self, user_id: int) -> list[dict]:
        """Return the entire stored history for display, ignoring the timeout.

        The hub renders one continuous conversation, so it reads the full message
        array (capped at ``max_messages``) regardless of idle time. The agent's
        LLM-context window still comes from ``get()`` (active session only), so
        this does not change what the model sees (CR-02).
        """
        doc_ref = self._col.document(str(user_id))
        try:
            snapshot = doc_ref.get()
        except GoogleAPICallError:
            logger.warning(
                "FirestoreConversationStore.get_full failed for user_id=%d; "
                "returning empty history.",
                user_id,
            )
            return []
        if not snapshot.exists:
            return []
        return list((snapshot.to_dict() or {}).get("messages", []))

    def append(self, user_id: int, role: str, content: str) -> None:
        """Append one message and cap the list via a Firestore transaction."""
        doc_ref = self._col.document(str(user_id))
        transaction = self._client.transaction()
        try:
            _txn_append(transaction, doc_ref, role, content, self._max_messages, self._timeout_hours)
        except GoogleAPICallError:
            logger.error(
                "FirestoreConversationStore.append failed for user_id=%d role=%s; "
                "message will not be persisted.",
                user_id,
                role,
            )

    def clear(self, user_id: int) -> None:
        """Delete the conversation document for user_id."""
        doc_ref = self._col.document(str(user_id))
        try:
            doc_ref.delete()
        except GoogleAPICallError:
            logger.error(
                "FirestoreConversationStore.clear failed for user_id=%d.", user_id
            )

    def get_last_user_timestamp(self, user_id: int) -> datetime | None:
        """Return the timestamp of the most recent user-role message for ``user_id``.

        Per-message timestamps are not stored; the closest signal we have is the
        document-level ``updated_at`` field, written on every append. We return
        ``updated_at`` when the most-recent (or any) message in the array is
        ``role == "user"``, else ``None`` — meaning no user message is stored in
        this session window.

        Returns ``None`` on empty/expired conversation OR on Firestore error.
        Never raises.

        Added in Phase 18 (Plan 06) for the autonomous tick's
        ``hours_since_contact`` signal (BLOCKER 1 fix).
        """
        doc_ref = self._col.document(str(user_id))
        try:
            snapshot = doc_ref.get()
        except GoogleAPICallError:
            logger.warning(
                "FirestoreConversationStore.get_last_user_timestamp failed "
                "for user_id=%d",
                user_id,
            )
            return None
        if not snapshot.exists:
            return None
        data = snapshot.to_dict() or {}
        updated_at = data.get("updated_at")
        messages = data.get("messages") or []
        if not messages:
            return None
        # Per-message timestamps don't exist; the doc-level ``updated_at`` is
        # the closest signal. Return it iff any user message exists in the array.
        for msg in reversed(messages):
            if msg.get("role") == "user":
                return updated_at if isinstance(updated_at, datetime) else None
        return None
