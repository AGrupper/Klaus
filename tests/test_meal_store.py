"""Tests for memory/firestore_db.py::MealStore — date-partitioned meal log.

PHASE 19 Plan 03 NUTR-02:
- upsert(source_id, meal): idempotent on source_id, written at
  meals/{YYYY-MM-DD}/timestamps/{source_id} with merge=True.
- get_day(date_str): all meals for a date, sorted by timestamp ascending.
- get_day_aggregate(date_str): {} on empty (Pitfall 4), else aggregate dict.

Mocks google.cloud.firestore at sys.modules level so the tests run without
the lib installed — mirrors the pattern in tests/test_firestore_db.py.
"""
from __future__ import annotations

import sys
from types import ModuleType
from unittest.mock import MagicMock


def _install_firestore_mock() -> MagicMock:
    """Install mock google.cloud.firestore + force re-import of firestore_db.

    Mirrors tests/test_user_profile_store.py — same module had its mocks
    set up by an earlier-running test (test_firestore_db.py) using a
    different SERVER_TIMESTAMP sentinel, so we MUST evict and re-import
    memory.firestore_db with our sentinel bound.
    """
    try:
        import google  # noqa: F401
        import google.cloud  # noqa: F401
        google_mod = sys.modules["google"]
        google_cloud_mod = sys.modules["google.cloud"]
    except ImportError:
        if "google" not in sys.modules or isinstance(sys.modules["google"], MagicMock):
            google_mod = ModuleType("google")
            google_mod.__path__ = []
            sys.modules["google"] = google_mod
        else:
            google_mod = sys.modules["google"]
        if "google.cloud" not in sys.modules or isinstance(sys.modules["google.cloud"], MagicMock):
            google_cloud_mod = ModuleType("google.cloud")
            google_cloud_mod.__path__ = []
            sys.modules["google.cloud"] = google_cloud_mod
            setattr(google_mod, "cloud", google_cloud_mod)
        else:
            google_cloud_mod = sys.modules["google.cloud"]

    firestore_mock = MagicMock()
    firestore_mock.SERVER_TIMESTAMP = object()  # distinguishable sentinel

    sys.modules["google.cloud.firestore"] = firestore_mock
    google_cloud_mod.firestore = firestore_mock

    # google.api_core.exceptions stub (firestore_db imports GoogleAPICallError)
    exc_mod = sys.modules.get("google.api_core.exceptions", MagicMock())
    exc_mod.GoogleAPICallError = Exception
    sys.modules["google.api_core.exceptions"] = exc_mod
    if "google.api_core" in sys.modules:
        sys.modules["google.api_core"].exceptions = exc_mod
    else:
        api_core = MagicMock()
        api_core.exceptions = exc_mod
        sys.modules["google.api_core"] = api_core

    # google.oauth2 — used inside _make_firestore_client when FIRESTORE_CREDENTIALS set
    sys.modules.setdefault("google.oauth2", MagicMock())
    sys.modules.setdefault("google.oauth2.service_account", MagicMock())

    # dotenv — top-level import in firestore_db
    dotenv_mod = MagicMock()
    dotenv_mod.load_dotenv = MagicMock()
    sys.modules.setdefault("dotenv", dotenv_mod)

    # Force re-import of firestore_db so its `from google.cloud import firestore`
    # re-binds to OUR mock (with our SERVER_TIMESTAMP sentinel).
    if "memory.firestore_db" in sys.modules:
        del sys.modules["memory.firestore_db"]

    return firestore_mock


import pytest

# Bound per-test by the autouse fixture below. We deliberately do NOT install
# the mock or import memory.firestore_db at module/collection time — that leaks
# fake google.* modules into sys.modules for the whole session and breaks
# sibling test files.
MealStore = None  # type: ignore[assignment]
_FS = None  # type: ignore[assignment]


@pytest.fixture(autouse=True)
def _firestore_mock(isolated_modules):
    global MealStore, _FS
    import importlib
    _FS = _install_firestore_mock()
    MealStore = importlib.import_module("memory.firestore_db").MealStore


def _store():
    """Build a MealStore with a fully-mocked Firestore client."""
    s = MealStore.__new__(MealStore)  # bypass __init__ → no real client
    s._client = MagicMock()
    s._col = MagicMock()
    return s


# ------------------------------------------------------------------ #
# upsert                                                             #
# ------------------------------------------------------------------ #

def test_upsert_idempotent_on_source_id():
    """Two upserts with the same source_id hit the SAME doc path with merge=True."""
    s = _store()
    doc_mock = MagicMock()
    sub_mock = MagicMock()
    inner_doc = MagicMock()
    s._col.document.return_value = doc_mock
    doc_mock.collection.return_value = sub_mock
    sub_mock.document.return_value = inner_doc
    meal = {"timestamp": "2026-05-26T12:00:00+03:00", "calories": 500}
    s.upsert(source_id="abc:123", meal=meal)
    s.upsert(source_id="abc:123", meal=meal)
    # Both calls use same date document + same source_id sub-document
    s._col.document.assert_any_call("2026-05-26")
    doc_mock.collection.assert_any_call("timestamps")
    sub_mock.document.assert_any_call("abc:123")
    assert inner_doc.set.call_count == 2
    for call in inner_doc.set.call_args_list:
        kwargs = call.kwargs
        assert kwargs.get("merge") is True


def test_upsert_includes_updated_at():
    """The written payload stamps updated_at = SERVER_TIMESTAMP + source_id."""
    s = _store()
    inner_doc = MagicMock()
    s._col.document.return_value.collection.return_value.document.return_value = inner_doc
    s.upsert(source_id="x:1", meal={"timestamp": "2026-05-26T12:00", "calories": 100})
    args, kwargs = inner_doc.set.call_args
    written = args[0]
    assert written["updated_at"] is _FS.SERVER_TIMESTAMP
    assert written["source_id"] == "x:1"


# ------------------------------------------------------------------ #
# get_day                                                            #
# ------------------------------------------------------------------ #

def test_get_day_returns_sorted():
    """Meals returned by stream() are sorted by timestamp ascending."""
    s = _store()
    snaps = [MagicMock(), MagicMock(), MagicMock()]
    snaps[0].to_dict.return_value = {"timestamp": "2026-05-26T18:00"}
    snaps[1].to_dict.return_value = {"timestamp": "2026-05-26T08:00"}
    snaps[2].to_dict.return_value = {"timestamp": "2026-05-26T13:00"}
    s._col.document.return_value.collection.return_value.stream.return_value = snaps
    result = s.get_day("2026-05-26")
    assert [m["timestamp"] for m in result] == [
        "2026-05-26T08:00", "2026-05-26T13:00", "2026-05-26T18:00",
    ]


def test_get_day_returns_empty_on_error():
    """stream() raising returns [] — never propagates."""
    s = _store()
    s._col.document.return_value.collection.return_value.stream.side_effect = RuntimeError("boom")
    assert s.get_day("2026-05-26") == []


def test_get_day_dedups_resynced_meals_keeping_latest():
    """2026-06-09 fix: before the source_id fix, the iOS Shortcut's re-syncs of a
    meal-time with a drifting calorie total piled up as multiple docs (e.g. lunch
    stored as both 1177 and 1180 kcal), inflating totals. get_day collapses docs
    sharing (timestamp, source), keeping the most-recently-written (max updated_at).
    """
    s = _store()
    older = MagicMock()
    older.to_dict.return_value = {
        "timestamp": "2026-05-26T12:00:00+03:00", "source": "healthkit",
        "calories": 1177, "updated_at": 1,
    }
    newer = MagicMock()
    newer.to_dict.return_value = {
        "timestamp": "2026-05-26T12:00:00+03:00", "source": "healthkit",
        "calories": 1180, "updated_at": 2,
    }
    s._col.document.return_value.collection.return_value.stream.return_value = [older, newer]
    result = s.get_day("2026-05-26")
    assert len(result) == 1, "duplicate meal-time docs must collapse to one"
    assert result[0]["calories"] == 1180, "latest sync (max updated_at) wins"
    assert "updated_at" not in result[0], "server-write stamp must be stripped"


def test_get_day_keeps_distinct_timestamps():
    """Dedup must NOT collapse genuinely different meal-times."""
    s = _store()
    a = MagicMock(); a.to_dict.return_value = {
        "timestamp": "2026-05-26T08:00:00+03:00", "source": "healthkit",
        "calories": 500, "updated_at": 1}
    b = MagicMock(); b.to_dict.return_value = {
        "timestamp": "2026-05-26T12:00:00+03:00", "source": "healthkit",
        "calories": 700, "updated_at": 1}
    s._col.document.return_value.collection.return_value.stream.return_value = [a, b]
    result = s.get_day("2026-05-26")
    assert len(result) == 2


# ------------------------------------------------------------------ #
# get_day_aggregate                                                  #
# ------------------------------------------------------------------ #

def test_get_day_aggregate_empty_returns_empty_dict():
    """Pitfall 4: empty meals returns {} (NOT {meal_count: 0})."""
    s = _store()
    s._col.document.return_value.collection.return_value.stream.return_value = []
    assert s.get_day_aggregate("2026-05-26") == {}


def test_get_day_aggregate_full():
    """A populated day produces meal_count, totals, by_type, biggest_gap, meals."""
    s = _store()
    snaps = []
    for ts, kcal, prot, mt in [
        ("2026-05-26T08:00:00+03:00", 400, 25, 1),
        ("2026-05-26T13:00:00+03:00", 700, 40, 2),
        ("2026-05-26T20:00:00+03:00", 600, 35, 3),
    ]:
        m = MagicMock()
        m.to_dict.return_value = {
            "timestamp": ts, "calories": kcal, "protein_g": prot,
            "carbs_g": 50, "fat_g": 15, "fiber_g": 4, "meal_type": mt,
        }
        snaps.append(m)
    s._col.document.return_value.collection.return_value.stream.return_value = snaps
    agg = s.get_day_aggregate("2026-05-26")
    assert agg["meal_count"] == 3
    assert agg["totals"]["calories"] == 1700
    assert agg["totals"]["protein_g"] == 100
    assert agg["totals"]["fiber_g"] == 12  # Phase 19.2 — fiber summed in totals
    assert set(agg["by_type"].keys()) == {1, 2, 3}
    assert agg["biggest_gap_minutes"] > 0
    assert len(agg["meals"]) == 3


def test_get_day_aggregate_biggest_gap():
    """biggest_gap_minutes = max(t[i] - t[i-1]) in minutes."""
    s = _store()
    snaps = []
    for ts in [
        "2026-05-26T08:00:00+03:00",
        "2026-05-26T09:00:00+03:00",
        "2026-05-26T14:00:00+03:00",
    ]:
        m = MagicMock()
        m.to_dict.return_value = {"timestamp": ts, "calories": 100, "meal_type": 1}
        snaps.append(m)
    s._col.document.return_value.collection.return_value.stream.return_value = snaps
    agg = s.get_day_aggregate("2026-05-26")
    assert agg["biggest_gap_minutes"] == 300.0  # 5 hours


def test_get_day_strips_non_serializable_updated_at():
    """Phase 19.3 live-UAT fix: get_day drops the Firestore updated_at stamp so
    downstream json.dumps (fetch_recent_meals tool, autonomous triage) never
    chokes on a DatetimeWithNanoseconds ('timestamp serialization anomaly')."""
    import json as _json

    class _FakeTs:  # stand-in for Firestore DatetimeWithNanoseconds
        def __repr__(self):
            return "DatetimeWithNanoseconds(...)"

    s = _store()
    snap = MagicMock()
    snap.to_dict.return_value = {
        "timestamp": "2026-05-31T08:00:00+03:00",
        "calories": 300, "protein_g": 20, "fiber_g": 4,
        "source_id": "healthkit:x", "updated_at": _FakeTs(),
    }
    s._col.document.return_value.collection.return_value.stream.return_value = [snap]
    meals = s.get_day("2026-05-31")
    assert "updated_at" not in meals[0]
    # The returned list must be JSON-serializable end-to-end.
    _json.dumps(meals)
