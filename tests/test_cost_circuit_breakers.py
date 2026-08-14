"""Behavioral tests for the retained embedding and Routes cost breakers."""
from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from memory import firestore_db
from memory.pinecone_db import MemoryStore
from mcp_tools import routes_tool


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


def test_routes_reservations_enforce_daily_and_rolling_minute_caps(monkeypatch):
    """Removing either atomic boundary would allow excess billable computations."""
    client = _FirestoreClient()
    monkeypatch.setattr(firestore_db, "_make_firestore_client", lambda *_args: client)
    monkeypatch.setattr(firestore_db.firestore, "transactional", lambda function: function)
    store = firestore_db.RoutesUsageStore("project", "database")
    start = datetime(2026, 8, 13, 7, 0, tzinfo=timezone.utc)

    for _ in range(5):
        assert store.reserve("amit", now=start, daily_limit=25, minute_limit=5) is True
    assert store.reserve("amit", now=start, daily_limit=25, minute_limit=5) is False
    assert store.reserve(
        "amit", now=start + timedelta(seconds=61), daily_limit=25, minute_limit=5
    ) is True

    for index in range(6, 25):
        assert store.reserve(
            "amit",
            now=start + timedelta(seconds=61 * index),
            daily_limit=25,
            minute_limit=5,
        ) is True
    assert store.reserve(
        "amit", now=start + timedelta(hours=2), daily_limit=25, minute_limit=5
    ) is False


def test_routes_minute_cap_survives_jerusalem_day_rollover(monkeypatch):
    """Local midnight must reset daily quota without resetting the rolling minute."""
    client = _FirestoreClient()
    monkeypatch.setattr(firestore_db, "_make_firestore_client", lambda *_args: client)
    monkeypatch.setattr(firestore_db.firestore, "transactional", lambda function: function)
    store = firestore_db.RoutesUsageStore("project", "database")
    before_midnight = datetime(2026, 1, 1, 21, 59, 45, tzinfo=timezone.utc)

    for offset in range(5):
        assert store.reserve(
            "amit",
            now=before_midnight + timedelta(seconds=offset),
            daily_limit=25,
            minute_limit=5,
        ) is True

    assert store.reserve(
        "amit",
        now=before_midnight + timedelta(seconds=20),
        daily_limit=25,
        minute_limit=5,
    ) is False
    assert set(client.data["routes_usage"]) == {
        "amit:2026-01-01",
    }


def test_routes_cache_is_persisted_by_event_and_departure_window(monkeypatch):
    """Changing Cloud Run instances must not cause a second billable route lookup."""
    client = _FirestoreClient()
    monkeypatch.setattr(firestore_db, "_make_firestore_client", lambda *_args: client)
    store = firestore_db.RoutesUsageStore("project", "database")
    now = datetime(2026, 8, 13, 8, 0, tzinfo=timezone.utc)
    result = {"duration_minutes": 18, "distance_km": 6.2, "summary": "Ayalon"}

    store.put_cached(
        "amit",
        event_id="calendar-123",
        departure_time_iso="2026-08-13T14:01:00+03:00",
        result=result,
        now=now,
    )

    assert store.get_cached(
        "amit",
        event_id="calendar-123",
        departure_time_iso="2026-08-13T14:29:00+03:00",
        now=now + timedelta(minutes=5),
    ) == result
    assert store.get_cached(
        "amit",
        event_id="different-event",
        departure_time_iso="2026-08-13T14:29:00+03:00",
        now=now + timedelta(minutes=5),
    ) is None


def test_routes_quota_block_omits_estimate_without_provider_call(monkeypatch):
    """A cap hit should degrade to None, not call Routes or fail Calendar."""
    usage = MagicMock()
    usage.get_cached.return_value = None
    usage.reserve.return_value = False
    monkeypatch.setattr(routes_tool, "_get_usage_store", lambda: usage)
    session = MagicMock()
    monkeypatch.setattr(routes_tool, "_get_authorized_session", lambda: session)

    result = routes_tool.get_travel_time(
        origin="Tel Aviv",
        destination="Dizengoff Center",
        departure_time_iso="2026-08-13T14:00:00+03:00",
        user_id="amit",
        event_id="calendar-123",
    )

    assert result is None
    session.post.assert_not_called()


def test_routes_persisted_cache_precedes_quota_and_provider(monkeypatch):
    """A cache hit must consume neither the daily cap nor an API request."""
    cached = {"duration_minutes": 11, "distance_km": 4.0, "summary": "Namir"}
    usage = MagicMock()
    usage.get_cached.return_value = cached
    monkeypatch.setattr(routes_tool, "_get_usage_store", lambda: usage)
    session = MagicMock()
    monkeypatch.setattr(routes_tool, "_get_authorized_session", lambda: session)

    result = routes_tool.get_travel_time(
        origin="Tel Aviv",
        destination="University",
        departure_time_iso="2026-08-13T14:00:00+03:00",
        user_id="amit",
        event_id="calendar-123",
    )

    assert result == cached
    usage.reserve.assert_not_called()
    session.post.assert_not_called()


def test_routes_cache_write_failure_does_not_discard_computed_estimate(monkeypatch):
    """A post-provider cache outage must not break the Calendar response."""
    usage = MagicMock()
    usage.get_cached.return_value = None
    usage.reserve.return_value = True
    usage.put_cached.side_effect = RuntimeError("cache write unavailable")
    monkeypatch.setattr(routes_tool, "_get_usage_store", lambda: usage)
    response = MagicMock()
    response.json.return_value = {
        "routes": [{
            "duration": "900s",
            "distanceMeters": 6200,
            "description": "Ayalon",
        }]
    }
    session = MagicMock()
    session.post.return_value = response
    monkeypatch.setattr(routes_tool, "_get_authorized_session", lambda: session)

    result = routes_tool.get_travel_time(
        origin="Tel Aviv",
        destination="Jaffa",
        departure_time_iso="2026-08-13T14:00:00+03:00",
        user_id="amit",
        event_id="calendar-123",
    )

    assert result == {
        "duration_minutes": 15,
        "distance_km": 6.2,
        "summary": "Ayalon",
    }
