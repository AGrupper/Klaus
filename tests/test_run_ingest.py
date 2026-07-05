"""Tests for core/run_ingest.py::run_one_batch.

Covers backfill vs delta window selection, presence-check skipping of already
synced runs, non-running filtering, count-bounded draining, the backfill_done
flip on full drain, per-activity error isolation, and fail-open on Garmin errors.

Garmin client functions and the Firestore store/state are patched at the module
level — no network, no Firestore, no sleeps.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

import core.run_ingest as ri


@pytest.fixture
def store():
    return MagicMock(name="RunDetailStore")


@pytest.fixture(autouse=True)
def _patch_common(monkeypatch, store):
    monkeypatch.setattr(
        ri, "normalize_run_detail",
        lambda activity, d, s, h, typed_splits=None: {"activity_id": str(activity["activity_id"])},
    )
    monkeypatch.setattr(
        ri, "fetch_run_detail_raw",
        lambda aid: {"details": {}, "splits": {}, "hr_zones": [], "typed_splits": {}},
    )
    monkeypatch.setattr(ri, "_store", lambda: store)
    state_holder = {"state": {}}
    monkeypatch.setattr(ri, "_get_state", lambda: dict(state_holder["state"]))
    monkeypatch.setattr(ri, "_set_state", lambda f: state_holder["state"].update(f))
    ri._state_holder = state_holder  # type: ignore[attr-defined]
    store.get_run.return_value = None          # nothing synced yet by default
    monkeypatch.setenv("RUN_INGEST_REQUEST_DELAY_SEC", "0")  # no real sleeps


def _state():
    return ri._state_holder["state"]  # type: ignore[attr-defined]


def _runs(*ids, atype="running"):
    return [{"activity_id": i, "type": atype} for i in ids]


# ------------------------------------------------------------------ #
# Backfill                                                           #
# ------------------------------------------------------------------ #

def test_backfill_processes_unsynced_and_flips_done(store):
    acts = _runs(1, 2)
    fga = MagicMock(return_value=acts)
    with patch.object(ri, "fetch_garmin_activities", fga):
        result = ri.run_one_batch()
    assert result["mode"] == "backfill"
    assert result["processed"] == 2
    assert result["remaining"] == 0
    assert result["done"] is True
    assert store.upsert.call_count == 2
    assert _state().get("backfill_done") is True
    fga.assert_called_once_with(120)  # wide backfill window


def test_non_running_activities_filtered(store):
    acts = (
        _runs(1)
        + [{"activity_id": 2, "type": "cycling"}]
        + _runs(3, atype="trail_running")
        + _runs(4, atype="track_running")
    )
    with patch.object(ri, "fetch_garmin_activities", return_value=acts):
        result = ri.run_one_batch()
    assert result["processed"] == 3  # cycling excluded; track_running included
    upserted = {c.args[0]["activity_id"] for c in store.upsert.call_args_list}
    assert upserted == {"1", "3", "4"}


def test_batch_bounded_not_done(monkeypatch, store):
    monkeypatch.setenv("RUN_INGEST_MAX_ACTIVITIES", "1")
    with patch.object(ri, "fetch_garmin_activities", return_value=_runs(1, 2, 3)):
        result = ri.run_one_batch()
    assert result["processed"] == 1
    assert result["remaining"] == 2
    assert result["done"] is False
    assert "backfill_done" not in _state()  # still draining


def test_presence_check_skips_already_synced(store):
    store.get_run.side_effect = lambda aid: {"activity_id": aid} if aid == "1" else None
    with patch.object(ri, "fetch_garmin_activities", return_value=_runs(1, 2)):
        result = ri.run_one_batch()
    assert result["processed"] == 1
    store.upsert.assert_called_once()
    assert store.upsert.call_args.args[0]["activity_id"] == "2"


def test_per_activity_error_isolated(store):
    monkeypatch_raise = MagicMock(side_effect=[RuntimeError("bad detail"), {"details": {}, "splits": {}, "hr_zones": []}])
    with patch.object(ri, "fetch_garmin_activities", return_value=_runs(1, 2)):
        with patch.object(ri, "fetch_run_detail_raw", monkeypatch_raise):
            result = ri.run_one_batch()
    assert result["processed"] == 1   # one failed, one succeeded
    assert result["remaining"] == 1
    assert result["done"] is False


# ------------------------------------------------------------------ #
# Delta                                                              #
# ------------------------------------------------------------------ #

def test_delta_mode_uses_short_window(store):
    ri._set_state({"backfill_done": True})
    fga = MagicMock(return_value=_runs(5))
    with patch.object(ri, "fetch_garmin_activities", fga):
        result = ri.run_one_batch()
    assert result["mode"] == "delta"
    assert result["done"] is True
    fga.assert_called_once_with(14)  # short delta window


# ------------------------------------------------------------------ #
# Fail-open                                                          #
# ------------------------------------------------------------------ #

def test_activities_fetch_failure_returns_not_ok(store):
    with patch.object(ri, "fetch_garmin_activities", side_effect=ri.GarminUnavailableError("garmin down")):
        result = ri.run_one_batch()
    assert result["ok"] is False
    assert "garmin down" in result["error"]
