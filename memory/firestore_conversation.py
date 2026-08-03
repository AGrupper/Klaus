"""Firestore-backed conversation history store.

Persists per-user conversation history as a single Firestore document,
keyed by Telegram user ID. Survives Cloud Run scale-to-zero evictions.

Document layout:
    collection: conversations  (FIRESTORE_COLLECTION_CONVERSATIONS env var)
    doc id:     "<telegram_user_id>"   (string)
    fields:
        messages:    [{"role": "user"|"assistant", "content": str,
                        "ts": str (ISO-8601, Asia/Jerusalem)}, ...]
                     `ts` is stamped on every message by `_txn_append`. It is
                     an ISO string, never `firestore.SERVER_TIMESTAMP` — a
                     Firestore `DatetimeWithNanoseconds` breaks `json.dumps`
                     on read (same bug class fixed for MealStore /
                     TrainingLogStore). Messages written before this field
                     existed have no `ts` — readers must tolerate a missing
                     or malformed value, never crash on it.
        updated_at:  Firestore server timestamp (document-level; tracks the
                     last write to the doc, not any single message's time)

The `messages` array is capped at `max_messages` entries (oldest are dropped
first). Writes are wrapped in a Firestore transaction to prevent lost updates
if two messages arrive near-simultaneously.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from google.api_core.exceptions import GoogleAPICallError
from google.cloud import firestore

logger = logging.getLogger(__name__)

# WHY Asia/Jerusalem, not UTC: per-message `ts` values are for humans (hub
# display, autonomous-tick "hours since contact" reasoning) — storing them in
# the user's own timezone matches every other Klaus-authored ISO timestamp
# convention (TZ=Asia/Jerusalem, CLAUDE.md). The string still carries an
# explicit UTC offset, so `datetime.fromisoformat` parses it as tz-aware and
# every existing comparison (`ts >= cutoff`, `astimezone(timezone.utc)`)
# continues to work unchanged regardless of which offset was stored.
_TZ = ZoneInfo("Asia/Jerusalem")

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
    messages.append({
        "role": role,
        "content": content,
        # ISO-8601 string (NOT firestore.SERVER_TIMESTAMP) — a Firestore
        # DatetimeWithNanoseconds breaks json.dumps on read (the same class
        # of bug fixed for MealStore/TrainingLogStore). Every message gets a
        # timestamp on append, so a "some messages have ts, some don't"
        # split only ever happens for pre-existing legacy records written
        # before this field existed — readers must still tolerate those.
        "ts": datetime.now(_TZ).isoformat(),
    })
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


@firestore.transactional
def _txn_pop_trailing_assistant(
    transaction: firestore.Transaction,
    doc_ref: firestore.DocumentReference,
) -> str | None:
    """Transactional helper: drop the trailing assistant message.

    Returns the content of the user message that precedes it (the text to
    re-run for a regenerate), or None when there is nothing to pop — history
    empty, or a turn already in flight (last message is the user's).
    """
    snapshot = doc_ref.get(transaction=transaction)
    if not snapshot.exists:
        return None
    doc_data: dict = snapshot.to_dict() or {}
    messages: list[dict] = list(doc_data.get("messages", []))
    if not messages or messages[-1].get("role") != "assistant":
        return None
    messages = messages[:-1]
    if not messages or messages[-1].get("role") != "user":
        return None
    session_start = min(int(doc_data.get("session_start_index", 0)), len(messages))
    transaction.set(
        doc_ref,
        {
            "messages": messages,
            "session_start_index": session_start,
            "updated_at": firestore.SERVER_TIMESTAMP,
        },
    )
    return str(messages[-1].get("content", ""))


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

    def get_recent_window(
        self, user_id: int, hours: int = 24, max_messages: int = 60,
    ) -> list[dict]:
        """Return messages from the last `hours`, ignoring the session-idle timeout.

        Built for the Phase 31 reflection learning-loop fix (the 6h-timeout-bounded
        `get()` is empty at nightly reflection time on most nights). Also the shared
        dependency for Phase 32's ambient-recall tail-prepend and conversation_tail
        gather.

        Legacy messages without a `ts` field (pre-Phase-31) are tolerated: kept by
        array position (best-effort), not KeyError'd or dropped outright. A
        malformed/unparseable `ts` is tolerated the same way.

        Deliberately does NOT consult `session_start_index` or the idle timeout —
        this method is timeout-independent by design.
        """
        doc_ref = self._col.document(str(user_id))
        try:
            snapshot = doc_ref.get()
        except GoogleAPICallError:
            logger.warning(
                "FirestoreConversationStore.get_recent_window failed for user_id=%d",
                user_id,
            )
            return []
        if not snapshot.exists:
            return []
        messages = list((snapshot.to_dict() or {}).get("messages", []))
        cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
        windowed = []
        for m in messages:
            ts_raw = m.get("ts")
            if ts_raw is None:
                windowed.append(m)  # legacy message — no ts, keep by position
                continue
            try:
                ts = datetime.fromisoformat(ts_raw)
            except (ValueError, TypeError):
                windowed.append(m)  # malformed ts — tolerate, keep by position
                continue
            if ts >= cutoff:
                windowed.append(m)
        return windowed[-max_messages:]

    def pop_trailing_assistant(self, user_id: int) -> str | None:
        """Remove the trailing assistant message (hub regenerate feature).

        Returns the preceding user message's text — the content to re-run —
        or None when there is nothing to pop (empty history, or a turn already
        in flight). Transactional: safe against a concurrent append.
        """
        doc_ref = self._col.document(str(user_id))
        transaction = self._client.transaction()
        try:
            return _txn_pop_trailing_assistant(transaction, doc_ref)
        except GoogleAPICallError:
            logger.error(
                "FirestoreConversationStore.pop_trailing_assistant failed for user_id=%d",
                user_id,
            )
            return None

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

        Every message written by ``append`` now carries its own per-message
        ``ts`` (ISO-8601 string, Asia/Jerusalem) — see ``_txn_append``. We
        prefer that: it's the actual moment the message arrived, not the
        moment the *document* was last touched (which ``updated_at`` tracks
        and can be a later, unrelated write — e.g. an assistant reply
        appended after the user's turn). Legacy messages written before this
        field existed have no ``ts``; for those we fall back to the
        document-level ``updated_at`` (the previous behaviour), which is
        still correct for a document whose only messages predate ``ts``.

        Returns ``None`` on empty/expired conversation, on Firestore error,
        or when no user message exists in the array. Never raises.

        Added in Phase 18 (Plan 06) for the autonomous tick's
        ``hours_since_contact`` signal (BLOCKER 1 fix). Updated to read
        per-message timestamps once they became available.
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
        for msg in reversed(messages):
            if msg.get("role") != "user":
                continue
            ts_raw = msg.get("ts")
            if ts_raw:
                try:
                    return datetime.fromisoformat(ts_raw)
                except (ValueError, TypeError):
                    # Malformed ts on this message — fall through to the
                    # doc-level signal rather than crashing (tolerate, don't
                    # raise, matching get_recent_window's leniency).
                    pass
            return updated_at if isinstance(updated_at, datetime) else None
        return None
