"""Web Push subscriptions and their delivery health.

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
        self._client = base._make_firestore_client(project_id, database)
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
