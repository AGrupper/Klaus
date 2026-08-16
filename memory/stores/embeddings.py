"""Embedding request accounting against the daily quota.

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


class EmbeddingUsageStore:
    """Atomic per-user embedding quota and provider-reported usage ledger."""

    _COLLECTION = "embedding_usage"

    def __init__(self, project_id: str, database: str = "(default)") -> None:
        self._client = base._make_firestore_client(project_id, database)

    @staticmethod
    def _document_id(user_id: str | int, now=None) -> tuple[str, str]:
        """Return the canonical user/day ledger key in Asia/Jerusalem."""
        from datetime import datetime, timezone
        from zoneinfo import ZoneInfo

        instant = now or datetime.now(timezone.utc)
        if instant.tzinfo is None:
            instant = instant.replace(tzinfo=timezone.utc)
        day = instant.astimezone(ZoneInfo("Asia/Jerusalem")).date().isoformat()
        canonical_user = str(user_id).strip()
        if not canonical_user or "/" in canonical_user:
            raise ValueError("user_id must be a non-empty canonical identifier")
        return f"{canonical_user}:{day}", day

    def reserve(
        self,
        user_id: str | int,
        *,
        now=None,
        limit: int = 200,
    ) -> bool:
        """Atomically reserve one provider request before Gemini is called.

        Returns ``False`` when the daily cap is already exhausted. Firestore
        errors raise so callers can fail closed instead of bypassing the cap.
        """
        document_id, day = self._document_id(user_id, now)
        document = self._client.collection(self._COLLECTION).document(document_id)
        transaction = self._client.transaction()

        @firestore.transactional
        def reserve_once(txn):
            snapshot = document.get(transaction=txn)
            current = snapshot.to_dict() or {} if snapshot.exists else {}
            request_count = max(0, int(current.get("embedding_calls", 0)))
            if request_count >= max(1, int(limit)):
                return False
            txn.set(
                document,
                {
                    "user_id": str(user_id),
                    "date": day,
                    "model": "gemini-embedding-2",
                    "embedding_calls": request_count + 1,
                    "daily_limit": max(1, int(limit)),
                    "updated_at": firestore.SERVER_TIMESTAMP,
                },
                merge=True,
            )
            return True

        return bool(reserve_once(transaction))

    def record(
        self,
        *,
        user_id: str | int,
        input_tokens: int,
        item_count: int,
        cost_usd: float,
        now=None,
    ) -> None:
        """Best-effort provider metrics for an already-reserved request."""
        try:
            document_id, day = self._document_id(user_id, now)
            self._client.collection(self._COLLECTION).document(document_id).set(
                {
                    "user_id": str(user_id),
                    "date": day,
                    "model": "gemini-embedding-2",
                    "embedding_input_tokens": firestore.Increment(max(0, int(input_tokens))),
                    "embedding_items": firestore.Increment(max(0, int(item_count))),
                    "embedding_cost_usd": firestore.Increment(max(0.0, float(cost_usd))),
                },
                merge=True,
            )
        except Exception:
            logger.warning("EmbeddingUsageStore.record() failed", exc_info=True)

    def summary(
        self,
        user_id: str | int,
        period: str = "today",
        *,
        now=None,
    ) -> dict:
        """Return today's embedding meter; month aggregation is intentionally deferred."""
        try:
            if period != "today":
                return {}
            document_id, _day = self._document_id(user_id, now)
            snap = self._client.collection(self._COLLECTION).document(document_id).get()
            return snap.to_dict() or {} if snap.exists else {}
        except Exception:
            logger.warning("EmbeddingUsageStore.summary() failed", exc_info=True)
            return {}
