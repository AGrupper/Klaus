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
) -> None:
    """Transactional helper: read → append → truncate → write."""
    snapshot = doc_ref.get(transaction=transaction)
    messages: list[dict] = (
        list((snapshot.to_dict() or {}).get("messages", []))
        if snapshot.exists
        else []
    )
    messages.append({"role": role, "content": content})
    if len(messages) > max_messages:
        # WHY: keep the newest messages — they carry the most relevant context.
        messages = messages[-max_messages:]
    transaction.set(
        doc_ref,
        {"messages": messages, "updated_at": firestore.SERVER_TIMESTAMP},
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
        return list((snapshot.to_dict() or {}).get("messages", []))

    def append(self, user_id: int, role: str, content: str) -> None:
        """Append one message and cap the list via a Firestore transaction."""
        doc_ref = self._col.document(str(user_id))
        transaction = self._client.transaction()
        try:
            _txn_append(transaction, doc_ref, role, content, self._max_messages)
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
