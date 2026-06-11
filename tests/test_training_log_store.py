"""Tests for memory/firestore_db.py::TrainingLogStore — Phase 20 LOG-01/LOG-02.

RED tests — written before implementation. All should FAIL until TrainingLogStore
is added to memory/firestore_db.py.

Tests cover:
  - log_session writes correct doc_id + payload with merge=True
  - log_session idempotency (same slot → same doc_id)
  - Pitfall 7: Garmin raw RPE (steps-of-10, e.g. 70) normalised to 7
  - Values already in 1..10 are left unchanged
  - get_recent(7) returns entries within cutoff, sorted date desc, with doc_id
  - get_by_date returns entries starting with the date prefix
  - get_recent on Firestore exception returns [] (never raises)

Mocks google.cloud.firestore at sys.modules level so tests run without the lib
installed — mirrors tests/test_meal_store.py pattern.
"""
from __future__ import annotations

import sys
from datetime import date, timedelta
from types import ModuleType
from unittest.mock import MagicMock, call


def _install_firestore_mock() -> MagicMock:
    """Install mock google.cloud.firestore + force re-import of firestore_db.

    Mirrors tests/test_meal_store.py — evict and re-import memory.firestore_db
    with our SERVER_TIMESTAMP sentinel bound.
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

    # google.api_core.exceptions stub
    exc_mod = sys.modules.get("google.api_core.exceptions", MagicMock())
    exc_mod.GoogleAPICallError = Exception
    sys.modules["google.api_core.exceptions"] = exc_mod
    if "google.api_core" in sys.modules:
        sys.modules["google.api_core"].exceptions = exc_mod
    else:
        api_core = MagicMock()
        api_core.exceptions = exc_mod
        sys.modules["google.api_core"] = api_core

    sys.modules.setdefault("google.oauth2", MagicMock())
    sys.modules.setdefault("google.oauth2.service_account", MagicMock())

    dotenv_mod = MagicMock()
    dotenv_mod.load_dotenv = MagicMock()
    sys.modules.setdefault("dotenv", dotenv_mod)

    # Pin base_query so the stores' server-side FieldFilter queries resolve a
    # real class, even if an earlier test file left the slot as a MagicMock.
    from tests.fakes import install_fake_base_query
    install_fake_base_query()

    # Force re-import so `from google.cloud import firestore` rebinds to OUR mock.
    if "memory.firestore_db" in sys.modules:
        del sys.modules["memory.firestore_db"]

    return firestore_mock


import pytest

from tests.fakes import FailingCollection, FakeCollection, make_snap

# Bound per-test by the autouse fixture below. We deliberately do NOT install
# the mock or import memory.firestore_db at module/collection time — that leaks
# fake google.* modules into sys.modules for the whole session and breaks
# sibling test files.
TrainingLogStore = None  # type: ignore[assignment]
_FS = None  # type: ignore[assignment]


@pytest.fixture(autouse=True)
def _firestore_mock(isolated_modules):
    global TrainingLogStore, _FS
    import importlib
    _FS = _install_firestore_mock()
    TrainingLogStore = importlib.import_module("memory.firestore_db").TrainingLogStore


def _store() -> TrainingLogStore:
    """Build a TrainingLogStore with a fully-mocked Firestore client."""
    s = TrainingLogStore.__new__(TrainingLogStore)  # bypass __init__
    s._client = MagicMock()
    s._col = MagicMock()
    return s


# ------------------------------------------------------------------ #
# log_session — writes + idempotency                                  #
# ------------------------------------------------------------------ #

def test_log_session_writes_correct_doc_id():
    """log_session writes to doc_id '{date}_{slot}'."""
    s = _store()
    doc_mock = MagicMock()
    s._col.document.return_value = doc_mock
    s.log_session(date="2026-06-01", slot="evt_abc")
    s._col.document.assert_called_once_with("2026-06-01_evt_abc")


def test_log_session_payload_fields():
    """log_session writes all expected fields in the payload."""
    s = _store()
    doc_mock = MagicMock()
    s._col.document.return_value = doc_mock

    s.log_session(
        date="2026-06-01",
        slot="evt_abc",
        session_type="gym",
        planned=True,
        completed=True,
        rpe=7,
    )

    args, kwargs = doc_mock.set.call_args
    payload = args[0]
    assert payload["date"] == "2026-06-01"
    assert payload["slot"] == "evt_abc"
    assert payload["type"] == "gym"
    assert payload["planned"] is True
    assert payload["completed"] is True
    assert payload["rpe"] == 7
    assert payload["updated_at"] is _FS.SERVER_TIMESTAMP


def test_log_session_uses_merge_true():
    """log_session uses merge=True for idempotent Garmin silent-sync safety."""
    s = _store()
    doc_mock = MagicMock()
    s._col.document.return_value = doc_mock

    s.log_session(date="2026-06-01", slot="evt_abc")

    args, kwargs = doc_mock.set.call_args
    assert kwargs.get("merge") is True


def test_log_session_idempotent_same_doc():
    """Two log_session calls with the same (date, slot) both use the same doc_id."""
    s = _store()
    doc_mock = MagicMock()
    s._col.document.return_value = doc_mock

    s.log_session(date="2026-06-01", slot="evt_abc", completed=False)
    s.log_session(date="2026-06-01", slot="evt_abc", completed=True)

    assert s._col.document.call_count == 2
    for c in s._col.document.call_args_list:
        assert c == call("2026-06-01_evt_abc")


# ------------------------------------------------------------------ #
# Pitfall 7 — RPE normalisation                                       #
# ------------------------------------------------------------------ #

def test_log_session_normalises_garmin_raw_rpe_70():
    """Garmin raw RPE of 70 (steps-of-10 scale) normalises to 7."""
    s = _store()
    doc_mock = MagicMock()
    s._col.document.return_value = doc_mock

    s.log_session(date="2026-06-01", slot="evt_abc", rpe=70)

    args, kwargs = doc_mock.set.call_args
    assert args[0]["rpe"] == 7


def test_log_session_normalises_garmin_raw_rpe_100():
    """Garmin raw RPE of 100 normalises to 10."""
    s = _store()
    doc_mock = MagicMock()
    s._col.document.return_value = doc_mock

    s.log_session(date="2026-06-01", slot="evt_abc", rpe=100)

    args, kwargs = doc_mock.set.call_args
    assert args[0]["rpe"] == 10


def test_log_session_leaves_normal_rpe_unchanged():
    """RPE already in 1..10 is left unchanged (not divided by 10)."""
    s = _store()
    doc_mock = MagicMock()
    s._col.document.return_value = doc_mock

    s.log_session(date="2026-06-01", slot="evt_abc", rpe=8)

    args, kwargs = doc_mock.set.call_args
    assert args[0]["rpe"] == 8


def test_log_session_rpe_none_stays_none():
    """rpe=None is written as-is (not normalised)."""
    s = _store()
    doc_mock = MagicMock()
    s._col.document.return_value = doc_mock

    s.log_session(date="2026-06-01", slot="evt_abc", rpe=None)

    args, kwargs = doc_mock.set.call_args
    assert args[0]["rpe"] is None


# ------------------------------------------------------------------ #
# get_recent                                                          #
# ------------------------------------------------------------------ #

def test_get_recent_returns_entries_within_cutoff():
    """get_recent(7) returns only entries with date >= today-7, sorted desc."""
    s = _store()
    today = date.today()
    cutoff_date = today - timedelta(days=7)

    old_date = (cutoff_date - timedelta(days=1)).isoformat()  # outside window
    new_date = today.isoformat()                               # inside window
    recent_date = (cutoff_date + timedelta(days=1)).isoformat()  # inside window

    s._col = FakeCollection([
        make_snap(f"{d}_evt", {"date": d, "slot": "evt"})
        for d in [old_date, new_date, recent_date]
    ])
    result = s.get_recent(7)

    returned_dates = [r["date"] for r in result]
    assert old_date not in returned_dates
    assert new_date in returned_dates
    assert recent_date in returned_dates
    # sorted descending
    assert returned_dates == sorted(returned_dates, reverse=True)


def test_get_recent_attaches_doc_id():
    """get_recent attaches doc_id to each result dict."""
    s = _store()
    today = date.today().isoformat()
    s._col = FakeCollection([
        make_snap(f"{today}_evt_xyz", {"date": today, "slot": "evt_xyz"})
    ])

    result = s.get_recent(7)

    assert len(result) == 1
    assert result[0]["doc_id"] == f"{today}_evt_xyz"


def test_get_recent_returns_empty_on_exception():
    """get_recent returns [] on Firestore exception — never raises."""
    s = _store()
    s._col = FailingCollection(RuntimeError("firestore down"))

    result = s.get_recent(7)

    assert result == []


# ------------------------------------------------------------------ #
# get_by_date                                                         #
# ------------------------------------------------------------------ #

def test_get_by_date_returns_matching_entries():
    """get_by_date returns only the entries for that calendar date."""
    s = _store()
    today = "2026-06-01"
    other = "2026-06-02"

    s._col = FakeCollection([
        make_snap(f"{d}_{slot}", {"date": d, "slot": slot})
        for slot, d in [("evt_a", today), ("evt_b", today), ("evt_c", other)]
    ])
    result = s.get_by_date(today)

    result_ids = [r["doc_id"] for r in result]
    assert f"{today}_evt_a" in result_ids
    assert f"{today}_evt_b" in result_ids
    assert f"{other}_evt_c" not in result_ids


def test_get_by_date_returns_empty_on_exception():
    """get_by_date returns [] on Firestore exception — never raises."""
    s = _store()
    s._col = FailingCollection(RuntimeError("down"))
    assert s.get_by_date("2026-06-01") == []


def _snap_with_timestamp():
    """A snap whose to_dict carries an updated_at datetime (like a resolved
    Firestore SERVER_TIMESTAMP)."""
    from datetime import datetime
    today = date.today().isoformat()
    return make_snap(f"{today}_evt", {
        "date": today,
        "slot": "evt",
        "completed": False,
        "skipped_reason": "other",
        "notes": "got home late",
        "updated_at": datetime(2026, 6, 2, 22, 0, 0),
    })


def test_get_recent_json_serialisable_with_server_timestamp():
    """Regression: updated_at (SERVER_TIMESTAMP) is coerced to a string so
    json.dumps(get_recent(...)) — as get_training_history does — never raises."""
    import json
    s = _store()
    s._col = FakeCollection([_snap_with_timestamp()])

    result = s.get_recent(7)

    assert len(result) == 1
    assert isinstance(result[0]["updated_at"], str)
    json.dumps(result)  # must not raise


def test_get_by_date_json_serialisable_with_server_timestamp():
    import json
    s = _store()
    s._col = FakeCollection([_snap_with_timestamp()])

    result = s.get_by_date(date.today().isoformat())

    assert isinstance(result[0]["updated_at"], str)
    json.dumps(result)  # must not raise


def test_get_range_json_serialisable_with_server_timestamp():
    import json
    s = _store()
    s._col = FakeCollection([_snap_with_timestamp()])
    today = date.today().isoformat()

    result = s.get_range(today, today)

    assert isinstance(result[0]["updated_at"], str)
    json.dumps(result)  # must not raise


# ------------------------------------------------------------------ #
# Phase 24 PROG-04 — quality param                                    #
# ------------------------------------------------------------------ #

def test_log_session_accepts_quality_param():
    """log_session accepts a quality keyword arg and writes it to the payload."""
    s = _store()
    doc_mock = MagicMock()
    s._col.document.return_value = doc_mock

    s.log_session(
        date="2026-06-06",
        slot="evt_abc",
        rpe=8,
        quality="grind",
    )

    args, kwargs = doc_mock.set.call_args
    payload = args[0]
    assert "quality" in payload, "payload must contain 'quality' key"
    assert payload["quality"] == "grind"


def test_log_session_quality_defaults_to_none():
    """log_session quality defaults to None when not supplied."""
    s = _store()
    doc_mock = MagicMock()
    s._col.document.return_value = doc_mock

    s.log_session(date="2026-06-06", slot="evt_abc")

    args, kwargs = doc_mock.set.call_args
    payload = args[0]
    assert "quality" in payload
    assert payload["quality"] is None


def test_log_session_quality_strong():
    """quality='strong' is persisted as-is."""
    s = _store()
    doc_mock = MagicMock()
    s._col.document.return_value = doc_mock

    s.log_session(date="2026-06-06", slot="evt_abc", quality="strong")

    args, _ = doc_mock.set.call_args
    assert args[0]["quality"] == "strong"


def test_log_session_quality_neutral():
    """quality='neutral' is persisted as-is."""
    s = _store()
    doc_mock = MagicMock()
    s._col.document.return_value = doc_mock

    s.log_session(date="2026-06-06", slot="evt_abc", quality="neutral")

    args, _ = doc_mock.set.call_args
    assert args[0]["quality"] == "neutral"
