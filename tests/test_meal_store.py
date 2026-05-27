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
from unittest.mock import MagicMock


def _install_firestore_mock():
    """Install firestore mocks at sys.modules level BEFORE importing MealStore."""
    firestore_mock = MagicMock()
    firestore_mock.SERVER_TIMESTAMP = object()
    google_cloud_mod = MagicMock()
    google_cloud_mod.firestore = firestore_mock
    sys.modules["google.cloud"] = google_cloud_mod
    sys.modules["google.cloud.firestore"] = firestore_mock
    return firestore_mock


_FS = _install_firestore_mock()

from memory.firestore_db import MealStore  # noqa: E402


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
            "carbs_g": 50, "fat_g": 15, "meal_type": mt,
        }
        snaps.append(m)
    s._col.document.return_value.collection.return_value.stream.return_value = snaps
    agg = s.get_day_aggregate("2026-05-26")
    assert agg["meal_count"] == 3
    assert agg["totals"]["calories"] == 1700
    assert agg["totals"]["protein_g"] == 100
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
