"""Tests for the nutrition-trend read path.

Two halves:
1. The fetch_recent_meals window bug fix — a >48h window must enumerate EVERY
   calendar date it touches (the old two-endpoint union silently skipped the
   days in between).
2. The new fetch_nutrition_trend tool — registration (brain-direct,
   worker-excluded) and handler math (averages over days-with-data only,
   missing_dates, targets/per-kg comparison, clamp, fail-open).
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

import core.tools as tools

_TZ = ZoneInfo("Asia/Jerusalem")


def _iso(days_ago: int) -> str:
    return (datetime.now(_TZ).date() - timedelta(days=days_ago)).isoformat()


def _fake_meal_store(days_with_meals: dict[str, dict]):
    """MealStore mock: get_day_aggregate returns the given totals per date."""
    store = MagicMock(name="MealStore")

    def _agg(date_str):
        totals = days_with_meals.get(date_str)
        if not totals:
            return {}
        return {"totals": totals, "meal_count": totals.get("_meals", 3)}

    def _day(date_str):
        if date_str in days_with_meals:
            return [{"timestamp": f"{date_str}T12:00:00+03:00",
                     "calories": days_with_meals[date_str]["calories"]}]
        return []

    store.get_day_aggregate.side_effect = _agg
    store.get_day.side_effect = _day
    return store


# ------------------------------------------------------------------ #
# fetch_recent_meals window bug regression                            #
# ------------------------------------------------------------------ #

def test_recent_meals_72h_window_includes_middle_days():
    """THE regression: pre-fix, only today and the cutoff day were read — a
    72h window silently dropped the day(s) in between."""
    middle = _iso(1)
    store = _fake_meal_store({middle: {"calories": 1800, "protein_g": 120,
                                       "carbs_g": 200, "fat_g": 60, "fiber_g": 25}})
    with patch("memory.firestore_db.MealStore", return_value=store):
        data = json.loads(tools._handle_fetch_recent_meals(hours=72))
    assert middle in data["totals_by_day"], (
        "a 72h window must read the days BETWEEN today and the cutoff day"
    )
    assert data["window_totals"]["protein_g"] == 120
    assert len(data["meals"]) == 1


def test_recent_meals_default_window_queries_at_most_two_dates():
    store = _fake_meal_store({})
    with patch("memory.firestore_db.MealStore", return_value=store):
        tools._handle_fetch_recent_meals(hours=24)
    queried = {c.args[0] for c in store.get_day.call_args_list}
    assert len(queried) <= 2  # today + possibly the straddled midnight day


# ------------------------------------------------------------------ #
# fetch_nutrition_trend — registration                                #
# ------------------------------------------------------------------ #

def test_nutrition_trend_registered_brain_direct_worker_excluded():
    assert "fetch_nutrition_trend" in tools.SMART_AGENT_DIRECT_TOOLS
    names = {s["name"] for s in tools.TOOL_SCHEMAS}
    assert "fetch_nutrition_trend" in names
    worker_names = {s["name"] for s in tools.WORKER_TOOL_SCHEMAS}
    assert "fetch_nutrition_trend" not in worker_names
    assert "fetch_nutrition_trend" in tools._HANDLERS


def test_nutrition_trend_schema_days_optional_integer():
    schema = next(s for s in tools.TOOL_SCHEMAS if s["name"] == "fetch_nutrition_trend")
    assert schema["input_schema"]["properties"]["days"]["type"] == "integer"
    assert schema["input_schema"]["required"] == []
    # the description must carry the two contract-critical instructions
    assert "missing_dates" in schema["description"]
    assert "VERBATIM" in schema["description"]


# ------------------------------------------------------------------ #
# fetch_nutrition_trend — handler math                                #
# ------------------------------------------------------------------ #

_DAY_TOTALS = {"calories": 2000, "protein_g": 140, "carbs_g": 220, "fat_g": 70, "fiber_g": 30}


def _profile_store(profile: dict):
    ps = MagicMock(name="UserProfileStore")
    ps.load.return_value = profile
    return ps


def test_trend_averages_divide_by_days_with_data_only():
    # 7-day window, 4 days logged — averages divide by 4, not 7.
    logged = {_iso(i): dict(_DAY_TOTALS) for i in (0, 1, 3, 5)}
    store = _fake_meal_store(logged)
    with patch("memory.firestore_db.MealStore", return_value=store), \
         patch("memory.firestore_db.UserProfileStore", return_value=_profile_store({})):
        data = json.loads(tools._handle_fetch_nutrition_trend(days=7))
    assert data["averages"]["days_with_data"] == 4
    assert data["averages"]["protein_g"] == 140.0
    assert data["averages"]["calories"] == 2000.0
    assert sorted(data["missing_dates"]) == sorted([_iso(2), _iso(4), _iso(6)])
    assert len(data["series"]) == 4
    # series runs oldest → newest for trend reading
    assert data["series"][0]["date"] == _iso(5)
    assert data["series"][-1]["date"] == _iso(0)


def test_trend_targets_and_per_kg_included_when_profile_set():
    logged = {_iso(i): dict(_DAY_TOTALS) for i in range(4)}
    store = _fake_meal_store(logged)
    profile = {"nutrition_targets": {"protein_g_floor": 150}, "bodyweight_kg": 70}
    with patch("memory.firestore_db.MealStore", return_value=store), \
         patch("memory.firestore_db.UserProfileStore", return_value=_profile_store(profile)):
        data = json.loads(tools._handle_fetch_nutrition_trend(days=4))
    assert data["targets"] == {"protein_g_floor": 150}
    assert data["avg_protein_g_per_kg"] == 2.0  # 140 / 70


def test_trend_targets_silently_omitted_when_profile_empty():
    logged = {_iso(0): dict(_DAY_TOTALS)}
    store = _fake_meal_store(logged)
    with patch("memory.firestore_db.MealStore", return_value=store), \
         patch("memory.firestore_db.UserProfileStore", return_value=_profile_store({})):
        data = json.loads(tools._handle_fetch_nutrition_trend(days=7))
    assert "targets" not in data
    assert "avg_protein_g_per_kg" not in data


def test_trend_days_clamped_to_sixty():
    store = _fake_meal_store({})
    with patch("memory.firestore_db.MealStore", return_value=store), \
         patch("memory.firestore_db.UserProfileStore", return_value=_profile_store({})):
        data = json.loads(tools._handle_fetch_nutrition_trend(days=500))
    assert data["window_days"] == 60
    assert store.get_day_aggregate.call_count == 60


def test_trend_profile_failure_does_not_break_series():
    logged = {_iso(0): dict(_DAY_TOTALS)}
    store = _fake_meal_store(logged)
    with patch("memory.firestore_db.MealStore", return_value=store), \
         patch("memory.firestore_db.UserProfileStore", side_effect=RuntimeError("fs down")):
        data = json.loads(tools._handle_fetch_nutrition_trend(days=3))
    assert data["averages"]["days_with_data"] == 1
    assert "targets" not in data


def test_trend_fails_open_to_error_payload():
    with patch("memory.firestore_db.MealStore", side_effect=RuntimeError("no firestore")):
        data = json.loads(tools._handle_fetch_nutrition_trend(days=7))
    assert "error" in data
