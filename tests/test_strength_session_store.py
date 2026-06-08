"""Tests for memory/firestore_db.py::StrengthSessionStore.

Covers:
  - upsert writes to doc_id == workout_id with merge=True + source/updated_at
  - upsert raises ValueError when workout_id missing
  - delete targets the right doc
  - get_range / get_recent filter by date and sort newest-first
  - get_exercise_history matches case-insensitively and returns progression
  - reads strip SERVER_TIMESTAMP so json.dumps never raises
  - reads never raise on Firestore errors (return [])

Mocks google.cloud.firestore at sys.modules level — mirrors
tests/test_training_log_store.py.
"""
from __future__ import annotations

import json
import sys
from datetime import date, datetime, timedelta
from types import ModuleType
from unittest.mock import MagicMock

import pytest


def _install_firestore_mock() -> MagicMock:
    try:
        import google  # noqa: F401
        import google.cloud  # noqa: F401
        google_mod = sys.modules["google"]
        google_cloud_mod = sys.modules["google.cloud"]
    except ImportError:
        google_mod = sys.modules.get("google") or ModuleType("google")
        google_mod.__path__ = []
        sys.modules["google"] = google_mod
        google_cloud_mod = sys.modules.get("google.cloud") or ModuleType("google.cloud")
        google_cloud_mod.__path__ = []
        sys.modules["google.cloud"] = google_cloud_mod
        setattr(google_mod, "cloud", google_cloud_mod)

    firestore_mock = MagicMock()
    firestore_mock.SERVER_TIMESTAMP = object()
    sys.modules["google.cloud.firestore"] = firestore_mock
    google_cloud_mod.firestore = firestore_mock

    exc_mod = sys.modules.get("google.api_core.exceptions", MagicMock())
    exc_mod.GoogleAPICallError = Exception
    sys.modules["google.api_core.exceptions"] = exc_mod
    api_core = sys.modules.get("google.api_core", MagicMock())
    api_core.exceptions = exc_mod
    sys.modules["google.api_core"] = api_core

    sys.modules.setdefault("google.oauth2", MagicMock())
    sys.modules.setdefault("google.oauth2.service_account", MagicMock())
    dotenv_mod = MagicMock()
    dotenv_mod.load_dotenv = MagicMock()
    sys.modules.setdefault("dotenv", dotenv_mod)

    if "memory.firestore_db" in sys.modules:
        del sys.modules["memory.firestore_db"]
    return firestore_mock


StrengthSessionStore = None  # type: ignore[assignment]
_FS = None  # type: ignore[assignment]


@pytest.fixture(autouse=True)
def _firestore_mock(isolated_modules):
    global StrengthSessionStore, _FS
    import importlib
    _FS = _install_firestore_mock()
    StrengthSessionStore = importlib.import_module("memory.firestore_db").StrengthSessionStore


def _store():
    s = StrengthSessionStore.__new__(StrengthSessionStore)
    s._client = MagicMock()
    s._col = MagicMock()
    return s


def _snap(workout_id: str, date_str: str, exercises: list | None = None) -> MagicMock:
    snap = MagicMock()
    snap.id = workout_id
    snap.to_dict.return_value = {
        "workout_id": workout_id,
        "date": date_str,
        "title": "Session",
        "total_volume_kg": 1000.0,
        "exercises": exercises if exercises is not None else [],
        "updated_at": datetime(2026, 6, 7, 22, 0, 0),  # resolved SERVER_TIMESTAMP
    }
    return snap


# ------------------------------------------------------------------ #
# upsert / delete                                                    #
# ------------------------------------------------------------------ #

def test_upsert_uses_workout_id_as_doc_and_merge():
    s = _store()
    doc = MagicMock()
    s._col.document.return_value = doc
    s.upsert({"workout_id": "w1", "date": "2026-06-07"})
    s._col.document.assert_called_once_with("w1")
    args, kwargs = doc.set.call_args
    assert kwargs.get("merge") is True
    assert args[0]["source"] == "hevy"
    assert args[0]["updated_at"] is _FS.SERVER_TIMESTAMP


def test_upsert_missing_workout_id_raises():
    s = _store()
    with pytest.raises(ValueError):
        s.upsert({"date": "2026-06-07"})


def test_delete_targets_doc():
    s = _store()
    doc = MagicMock()
    s._col.document.return_value = doc
    s.delete("w9")
    s._col.document.assert_called_once_with("w9")
    doc.delete.assert_called_once()


# ------------------------------------------------------------------ #
# reads — filtering, sorting, json-safety, fail-open                 #
# ------------------------------------------------------------------ #

def test_get_range_filters_and_sorts_desc():
    s = _store()
    s._col.stream.return_value = [
        _snap("a", "2026-06-01"),
        _snap("b", "2026-06-05"),
        _snap("c", "2026-05-20"),  # outside range
    ]
    out = s.get_range("2026-06-01", "2026-06-07")
    assert [d["workout_id"] for d in out] == ["b", "a"]


def test_get_recent_uses_cutoff():
    s = _store()
    today = date.today()
    s._col.stream.return_value = [
        _snap("recent", today.isoformat()),
        _snap("old", (today - timedelta(days=60)).isoformat()),
    ]
    out = s.get_recent(7)
    assert [d["workout_id"] for d in out] == ["recent"]


def test_reads_strip_server_timestamp_json_safe():
    s = _store()
    s._col.stream.return_value = [_snap("a", date.today().isoformat())]
    out = s.get_recent(7)
    assert isinstance(out[0]["updated_at"], str)
    json.dumps(out)  # must not raise


def test_get_range_returns_empty_on_exception():
    s = _store()
    s._col.stream.side_effect = RuntimeError("firestore down")
    assert s.get_range("2026-06-01", "2026-06-07") == []


def test_get_exercise_history_matches_case_insensitive():
    s = _store()
    s._col.stream.return_value = [
        _snap("w1", "2026-06-05", exercises=[
            {"name": "Bench Press", "top_set": {"weight_kg": 92.5, "reps": 3},
             "est_1rm": 101.8, "volume_kg": 1200.0},
        ]),
        _snap("w2", "2026-06-01", exercises=[
            {"name": "bench press", "top_set": {"weight_kg": 90, "reps": 5},
             "est_1rm": 105.0, "volume_kg": 1100.0},
            {"name": "Squat", "top_set": {"weight_kg": 120, "reps": 3},
             "est_1rm": 132.0, "volume_kg": 2000.0},
        ]),
    ]
    hist = s.get_exercise_history("Bench Press")
    assert [h["workout_id"] for h in hist] == ["w1", "w2"]  # newest first
    assert hist[0]["est_1rm"] == 101.8
    assert all("Squat" not in str(h) for h in hist)


def test_get_exercise_history_respects_limit():
    s = _store()
    s._col.stream.return_value = [
        _snap(f"w{i}", f"2026-06-0{i}", exercises=[{"name": "Squat", "est_1rm": 130 + i}])
        for i in range(1, 6)
    ]
    hist = s.get_exercise_history("Squat", limit=2)
    assert len(hist) == 2
