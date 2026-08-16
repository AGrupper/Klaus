"""Behavioral tests for the retained embedding cost breaker.

The Google Routes breaker lived here too, until Routes was retired: departure
windows now come from a configured travel time, so there is no per-call billing
left to cap. Embeddings remain the only metered provider call in the runtime.
"""
from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from memory import firestore_db
from memory.pinecone_db import MemoryStore


class _Snapshot:
    def __init__(self, data: dict | None) -> None:
        self._data = data

    @property
    def exists(self) -> bool:
        return self._data is not None

    def to_dict(self) -> dict:
        return dict(self._data or {})


class _Document:
    def __init__(self, backing: dict[str, dict], key: str) -> None:
        self._backing = backing
        self._key = key

    def get(self, transaction=None) -> _Snapshot:
        del transaction
        return _Snapshot(self._backing.get(self._key))

    def set(self, payload: dict, merge: bool = False) -> None:
        if merge:
            current = dict(self._backing.get(self._key) or {})
            current.update(payload)
            self._backing[self._key] = current
        else:
            self._backing[self._key] = dict(payload)


class _Collection:
    def __init__(self, backing: dict[str, dict]) -> None:
        self._backing = backing

    def document(self, key: str) -> _Document:
        return _Document(self._backing, key)


class _Transaction:
    def set(self, document: _Document, payload: dict, merge: bool = False) -> None:
        document.set(payload, merge=merge)


class _FirestoreClient:
    def __init__(self) -> None:
        self.data: dict[str, dict[str, dict]] = {}
        self.transaction_count = 0

    def collection(self, name: str) -> _Collection:
        return _Collection(self.data.setdefault(name, {}))

    def transaction(self) -> _Transaction:
        self.transaction_count += 1
        return _Transaction()


class _ConcurrentEmbeddingQuota:
    """Thread-safe persisted-ledger stand-in; provider calls stay real to the store."""

    def __init__(self, limit: int = 200) -> None:
        self.limit = limit
        self.count = 0
        self.records = 0
        self._lock = threading.Lock()

    def reserve(self, user_id, *, now=None, limit=200) -> bool:
        del user_id, now
        assert limit == self.limit
        with self._lock:
            if self.count >= self.limit:
                return False
            self.count += 1
            return True

    def record(self, **_kwargs) -> None:
        with self._lock:
            self.records += 1


def _embedding_response() -> SimpleNamespace:
    return SimpleNamespace(
        embeddings=[SimpleNamespace(values=[0.1] * 768)],
        usage_metadata=SimpleNamespace(prompt_token_count=3),
    )


def test_embedding_provider_is_never_called_above_concurrent_daily_cap(monkeypatch):
    """Removing the pre-provider reservation would permit the 201st paid call."""
    quota = _ConcurrentEmbeddingQuota()
    store = MemoryStore(
        api_key="pinecone",
        index_name="index",
        embedding_usage_store=quota,
    )
    provider = MagicMock()
    provider.models.embed_content.return_value = _embedding_response()
    store._genai = provider

    def embed_once(_index: int) -> str:
        try:
            store._embed("bounded input", user_id="canonical-user")
            return "allowed"
        except RuntimeError:
            return "blocked"

    with ThreadPoolExecutor(max_workers=32) as executor:
        outcomes = list(executor.map(embed_once, range(240)))

    assert outcomes.count("allowed") == 200
    assert outcomes.count("blocked") == 40
    assert provider.models.embed_content.call_count == 200
    assert quota.count == 200


def test_embedding_quota_failure_is_fail_closed_before_provider_call():
    """A Firestore outage must not turn the application cap into a paid bypass."""
    quota = MagicMock()
    quota.reserve.side_effect = RuntimeError("ledger unavailable")
    store = MemoryStore(
        api_key="pinecone",
        index_name="index",
        embedding_usage_store=quota,
    )
    provider = MagicMock()
    store._genai = provider

    with pytest.raises(RuntimeError, match="unavailable"):
        store._embed("do not bill", user_id="canonical-user")

    provider.models.embed_content.assert_not_called()


def test_embedding_reservations_use_canonical_user_and_jerusalem_day(monkeypatch):
    """A UTC-date implementation would charge after local midnight to yesterday."""
    client = _FirestoreClient()
    monkeypatch.setattr(firestore_db, "_make_firestore_client", lambda *_args: client)
    monkeypatch.setattr(firestore_db.firestore, "transactional", lambda function: function)
    store = firestore_db.EmbeddingUsageStore("project", "database")

    before_local_midnight = datetime(2026, 1, 1, 21, 59, tzinfo=timezone.utc)
    after_local_midnight = before_local_midnight + timedelta(minutes=2)

    assert store.reserve("amit", now=before_local_midnight, limit=1) is True
    assert store.reserve("amit", now=before_local_midnight, limit=1) is False
    assert store.reserve("amit", now=after_local_midnight, limit=1) is True

    assert set(client.data["embedding_usage"]) == {
        "amit:2026-01-01",
        "amit:2026-01-02",
    }
    assert client.transaction_count == 3
