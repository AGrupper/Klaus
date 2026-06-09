"""Tests for memory/firestore_db.py::RunDetailStore.

Covers:
  - upsert writes to doc_id == activity_id with merge=True + source/updated_at
  - upsert raises ValueError when activity_id missing
  - delete targets the right doc
  - get_run returns the doc / None (presence check)
  - get_range / get_recent filter by date and sort newest-first
  - reads strip SERVER_TIMESTAMP so json.dumps never raises
  - reads never raise on Firestore errors (return [] / None)

Mocks google.cloud.firestore at sys.modules level — mirrors
tests/test_strength_session_store.py.
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


RunDetailStore = None  # type: ignore[assignment]
_FS = None  # type: ignore[assignment]


@pytest.fixture(autouse=True)
def _firestore_mock(isolated_modules):
    global RunDetailStore, _FS
    import importlib
    _FS = _install_firestore_mock()
    RunDetailStore = importlib.import_module("memory.firestore_db").RunDetailStore


def _store():
    s = RunDetailStore.__new__(RunDetailStore)
    s._client = MagicMock()
    s._col = MagicMock()
    return s


def _snap(activity_id: str, date_str: str) -> MagicMock:
    snap = MagicMock()
    snap.id = activity_id
    snap.exists = True
    snap.to_dict.return_value = {
        "activity_id": activity_id,
        "date": date_str,
        "type": "running",
        "avg_pace_sec_per_km": 300.0,
        "updated_at": datetime(2026, 6, 8, 22, 0, 0),  # resolved SERVER_TIMESTAMP
    }
    return snap


# ------------------------------------------------------------------ #
# upsert / delete                                                    #
# ------------------------------------------------------------------ #

def test_upsert_uses_activity_id_as_doc_and_merge():
    s = _store()
    doc = MagicMock()
    s._col.document.return_value = doc
    s.upsert({"activity_id": "555", "date": "2026-06-08"})
    s._col.document.assert_called_once_with("555")
    args, kwargs = doc.set.call_args
    assert kwargs.get("merge") is True
    assert args[0]["source"] == "garmin"
    assert args[0]["updated_at"] is _FS.SERVER_TIMESTAMP


def test_upsert_missing_activity_id_raises():
    s = _store()
    with pytest.raises(ValueError):
        s.upsert({"date": "2026-06-08"})


def test_upsert_none_string_activity_id_raises():
    s = _store()
    with pytest.raises(ValueError):
        s.upsert({"activity_id": "None"})


def test_delete_targets_doc():
    s = _store()
    doc = MagicMock()
    s._col.document.return_value = doc
    s.delete("99")
    s._col.document.assert_called_once_with("99")
    doc.delete.assert_called_once()


# ------------------------------------------------------------------ #
# get_run (presence check)                                           #
# ------------------------------------------------------------------ #

def test_get_run_returns_doc():
    s = _store()
    s._col.document.return_value.get.return_value = _snap("5", "2026-06-08")
    out = s.get_run("5")
    assert out["activity_id"] == "5"
    assert isinstance(out["updated_at"], str)  # json-safe


def test_get_run_absent_returns_none():
    s = _store()
    missing = MagicMock()
    missing.exists = False
    s._col.document.return_value.get.return_value = missing
    assert s.get_run("nope") is None


def test_get_run_error_returns_none():
    s = _store()
    s._col.document.return_value.get.side_effect = RuntimeError("firestore down")
    assert s.get_run("5") is None


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
    assert [d["activity_id"] for d in out] == ["b", "a"]


def test_get_recent_uses_cutoff():
    s = _store()
    today = date.today()
    s._col.stream.return_value = [
        _snap("recent", today.isoformat()),
        _snap("old", (today - timedelta(days=60)).isoformat()),
    ]
    out = s.get_recent(7)
    assert [d["activity_id"] for d in out] == ["recent"]


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
