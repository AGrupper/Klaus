"""Tests for mcp_tools/google_fit_tool.py — Google Fit nutrition reads.

PHASE 19 Plan 03 NUTR-01:
- fetch_recent_meals(hours) — list nutrition entries from Google Fit
- _normalize_point(point, ds_id) — convert Fit dataPoint to Klaus meal shape
- sync_recent_meals(since_hours, store) — fetch + idempotent upsert into MealStore

The googleapiclient module is mocked at sys.modules level BEFORE importing
the tool, mirroring the pattern in tests/test_garmin_tool.py and other
tests that exercise googleapiclient-dependent code without the lib installed.
"""
from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch


# ------------------------------------------------------------------ #
# Mock googleapiclient BEFORE importing the tool                     #
# ------------------------------------------------------------------ #
if "googleapiclient" not in sys.modules:
    gapi = MagicMock()
    gapi.discovery = MagicMock()
    sys.modules["googleapiclient"] = gapi
    sys.modules["googleapiclient.discovery"] = gapi.discovery

from mcp_tools import google_fit_tool as gft  # noqa: E402


# ------------------------------------------------------------------ #
# _normalize_point                                                   #
# ------------------------------------------------------------------ #

def test_normalize_point_basic():
    """A fully-populated Fit dataPoint normalizes to the expected dict shape."""
    point = {
        "startTimeNanos": "1748246400000000000",  # 2025-05-26 12:00 UTC-ish
        "value": [
            {"mapVal": [
                {"key": "calories", "value": {"fpVal": 500.0}},
                {"key": "protein", "value": {"fpVal": 30.0}},
                {"key": "carbs.total", "value": {"fpVal": 50.0}},
                {"key": "fat.total", "value": {"fpVal": 15.0}},
            ]},
            {"intVal": 2},
        ],
    }
    result = gft._normalize_point(point, "ds_abc")
    assert result["source_id"] == "ds_abc:1748246400000000000"
    assert result["meal_type"] == 2
    assert result["calories"] == 500.0
    assert result["protein_g"] == 30.0
    assert result["carbs_g"] == 50.0
    assert result["fat_g"] == 15.0
    assert result["source"] == "google_fit"
    # ISO-formatted timestamp string
    assert result["timestamp"].startswith("20")


def test_normalize_point_missing_values():
    """Missing macros + missing meal_type default cleanly."""
    point = {"startTimeNanos": "1000000000000", "value": []}
    result = gft._normalize_point(point, "ds_xyz")
    assert result["meal_type"] == 1
    assert result["calories"] is None
    assert result["protein_g"] is None
    assert result["carbs_g"] is None
    assert result["fat_g"] is None
    assert result["food_item"] is None
    assert result["source"] == "google_fit"
    assert result["source_id"] == "ds_xyz:1000000000000"


def test_normalize_point_with_food_item():
    """A stringVal value gets stored as food_item."""
    point = {"startTimeNanos": "1000000000000", "value": [{"stringVal": "Sushi roll"}]}
    result = gft._normalize_point(point, "ds_xyz")
    assert result["food_item"] == "Sushi roll"


# ------------------------------------------------------------------ #
# fetch_recent_meals                                                 #
# ------------------------------------------------------------------ #

def test_fetch_recent_meals_calls_fit_api():
    """fetch_recent_meals enumerates data sources and aggregates dataPoints."""
    fake_svc = MagicMock()
    fake_svc.users.return_value.dataSources.return_value.list.return_value.execute.return_value = {
        "dataSource": [{"dataStreamId": "ds_1"}]
    }
    fake_svc.users.return_value.dataSources.return_value.datasets.return_value.get.return_value.execute.return_value = {
        "point": [
            {"startTimeNanos": "1000000000000", "value": [{"intVal": 1}]}
        ]
    }
    with patch.object(gft, "_fit_service", return_value=fake_svc):
        result = gft.fetch_recent_meals(hours=24)
    assert len(result) == 1
    assert result[0]["source_id"] == "ds_1:1000000000000"


def test_fetch_recent_meals_handles_dataset_error():
    """Per-dataset errors are logged + skipped; never raise."""
    fake_svc = MagicMock()
    fake_svc.users.return_value.dataSources.return_value.list.return_value.execute.return_value = {
        "dataSource": [{"dataStreamId": "ds_bad"}, {"dataStreamId": "ds_good"}]
    }
    call_count = {"n": 0}

    def _execute(*a, **k):
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise RuntimeError("500 backend")
        return {"point": [{"startTimeNanos": "2000000000000", "value": [{"intVal": 3}]}]}

    mock_get = fake_svc.users.return_value.dataSources.return_value.datasets.return_value.get
    mock_get.return_value.execute.side_effect = _execute
    with patch.object(gft, "_fit_service", return_value=fake_svc):
        result = gft.fetch_recent_meals(hours=24)
    # Got one good result, error on the other → no raise
    assert len(result) == 1


# ------------------------------------------------------------------ #
# sync_recent_meals                                                  #
# ------------------------------------------------------------------ #

def test_sync_recent_meals_upserts_each():
    """Each fetched meal is upserted by source_id into the supplied store."""
    store = MagicMock()
    with patch.object(gft, "fetch_recent_meals", return_value=[
        {"source_id": "a:1", "timestamp": "2026-05-26T12:00:00+03:00", "calories": 500},
        {"source_id": "a:2", "timestamp": "2026-05-26T18:00:00+03:00", "calories": 700},
    ]):
        out = gft.sync_recent_meals(since_hours=1, store=store)
    assert store.upsert.call_count == 2
    assert len(out) == 2


def test_sync_recent_meals_continues_on_upsert_failure():
    """A single upsert failure does NOT abort the remaining upserts."""
    store = MagicMock()
    store.upsert.side_effect = [RuntimeError("firestore down"), None]
    with patch.object(gft, "fetch_recent_meals", return_value=[
        {"source_id": "a:1", "timestamp": "x", "calories": 1},
        {"source_id": "a:2", "timestamp": "y", "calories": 2},
    ]):
        out = gft.sync_recent_meals(since_hours=1, store=store)
    assert store.upsert.call_count == 2  # second call still happened
    assert len(out) == 2  # both returned
