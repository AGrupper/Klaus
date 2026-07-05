"""Tests for core/biometric_ingest.py::run_one_batch.

Covers backfill vs delta window selection, presence-diff against Postgres,
the always-refetch of today+yesterday, the skipped_dates ledger for empty
Garmin days (so the backfill can drain), batch bounds, the backfill_done flip,
per-day error isolation, and fail-open on Garmin errors.

Garmin fetch, the Postgres writer/presence query, and the Firestore state are
patched at the module level — no network, no Postgres, no Firestore, no sleeps.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

import pytest

import core.biometric_ingest as bi


def _today_iso() -> str:
    return datetime.now(ZoneInfo("Asia/Jerusalem")).date().isoformat()


def _day(offset: int) -> str:
    d = datetime.now(ZoneInfo("Asia/Jerusalem")).date() - timedelta(days=offset)
    return d.isoformat()


def _daily(date_iso: str, **overrides) -> dict:
    base = {
        "date": date_iso,
        "sleep_score": 82, "sleep_hours": 7.5, "hrv_status": "BALANCED",
        "hrv_overnight": 62, "hrv_baseline": 60, "body_battery_morning": 90,
        "resting_hr": 47, "training_readiness": 75,
    }
    base.update(overrides)
    return base


@pytest.fixture
def writer():
    return MagicMock(name="write_biometrics_to_postgres")


@pytest.fixture(autouse=True)
def _patch_common(monkeypatch, writer):
    monkeypatch.setattr(bi, "fetch_garmin_daily", lambda d: _daily(d))
    monkeypatch.setattr(bi, "write_biometrics_to_postgres", writer)
    state_holder = {"state": {}}
    monkeypatch.setattr(bi, "_get_state", lambda: dict(state_holder["state"]))
    monkeypatch.setattr(bi, "_set_state", lambda f: state_holder["state"].update(f))
    bi._state_holder = state_holder  # type: ignore[attr-defined]
    monkeypatch.setenv("BIOMETRIC_INGEST_REQUEST_DELAY_SEC", "0")  # no real sleeps


def _state():
    return bi._state_holder["state"]  # type: ignore[attr-defined]


# ------------------------------------------------------------------ #
# Backfill                                                           #
# ------------------------------------------------------------------ #

def test_backfill_fetches_missing_days_and_flips_done(monkeypatch, writer):
    # 90-day window; everything present except 3 old days (+ today/yesterday
    # which are always refetched).
    monkeypatch.setenv("BIOMETRIC_INGEST_MAX_DAYS", "10")
    missing = {_day(5), _day(6), _day(7)}
    present = {_day(i) for i in range(91)} - missing
    with patch.object(bi, "_present_dates", return_value=present):
        result = bi.run_one_batch()
    assert result["mode"] == "backfill"
    assert result["processed"] == 5  # today + yesterday + 3 missing
    assert result["done"] is True
    assert _state().get("backfill_done") is True
    written = {c.args[0]["date"] for c in writer.call_args_list}
    assert missing <= written and _today_iso() in written


def test_today_and_yesterday_always_refetched_even_when_present(writer):
    # Delta mode, every day present — the daily heal still refetches 2 days.
    bi._state_holder["state"] = {"backfill_done": True}  # type: ignore[attr-defined]
    present = {_day(i) for i in range(8)}
    with patch.object(bi, "_present_dates", return_value=present):
        result = bi.run_one_batch()
    assert result["mode"] == "delta"
    assert result["processed"] == 2
    written = {c.args[0]["date"] for c in writer.call_args_list}
    assert written == {_day(0), _day(1)}


def test_batch_bounded_not_done(monkeypatch, writer):
    monkeypatch.setenv("BIOMETRIC_INGEST_MAX_DAYS", "3")
    with patch.object(bi, "_present_dates", return_value=set()):
        result = bi.run_one_batch()
    assert result["processed"] == 3
    assert result["remaining"] > 0
    assert result["done"] is False
    assert "backfill_done" not in _state()  # still draining


# ------------------------------------------------------------------ #
# skipped_dates ledger                                               #
# ------------------------------------------------------------------ #

def test_empty_days_go_to_skip_ledger_not_postgres(monkeypatch, writer):
    empty = {
        "date": None, "sleep_score": None, "sleep_hours": None,
        "hrv_status": None, "hrv_overnight": None, "hrv_baseline": None,
        "body_battery_morning": None, "resting_hr": None, "training_readiness": None,
    }
    monkeypatch.setattr(
        bi, "fetch_garmin_daily",
        lambda d: dict(empty, date=d) if d == _day(4) else _daily(d),
    )
    present = {_day(i) for i in range(91)} - {_day(4)}
    with patch.object(bi, "_present_dates", return_value=present):
        result = bi.run_one_batch()
    assert result["done"] is True
    assert _state().get("skipped_dates") == [_day(4)]
    written = {c.args[0]["date"] for c in writer.call_args_list}
    assert _day(4) not in written


def test_ledgered_days_not_retried(writer):
    bi._state_holder["state"] = {"skipped_dates": [_day(4)]}  # type: ignore[attr-defined]
    present = {_day(i) for i in range(91)} - {_day(4)}
    with patch.object(bi, "_present_dates", return_value=present):
        result = bi.run_one_batch()
    # Only the always-heal pair — the ledgered day is not a target.
    assert result["processed"] == 2
    assert result["done"] is True
    assert _state().get("backfill_done") is True


def test_empty_today_not_ledgered(monkeypatch, writer):
    # Today may simply have no data YET (05:30 predates wake-up) — it must be
    # retried tomorrow, never written off.
    empty = {k: None for k in bi._METRIC_FIELDS}
    monkeypatch.setattr(
        bi, "fetch_garmin_daily",
        lambda d: dict(empty, date=d) if d == _day(0) else _daily(d),
    )
    present = {_day(i) for i in range(91)}
    with patch.object(bi, "_present_dates", return_value=present):
        bi.run_one_batch()
    assert "skipped_dates" not in _state()


# ------------------------------------------------------------------ #
# Failure modes                                                      #
# ------------------------------------------------------------------ #

def test_presence_failure_falls_back_to_daily_heal_without_flip(writer):
    with patch.object(bi, "_present_dates", return_value=None):
        result = bi.run_one_batch()
    assert result["ok"] is True
    assert result["processed"] == 2  # today + yesterday only
    # Diff was unknowable — backfill_done must NOT flip.
    assert "backfill_done" not in _state()


def test_garmin_failure_on_first_day_fails_open(monkeypatch):
    def _boom(d):
        raise bi.GarminUnavailableError("net down")
    monkeypatch.setattr(bi, "fetch_garmin_daily", _boom)
    with patch.object(bi, "_present_dates", return_value=set()):
        result = bi.run_one_batch()
    assert result["ok"] is False
    assert "error" in result


def test_garmin_failure_mid_batch_stops_cleanly(monkeypatch, writer):
    calls = {"n": 0}

    def _second_fails(d):
        calls["n"] += 1
        if calls["n"] >= 2:
            raise bi.GarminAuthError("token expired")
        return _daily(d)

    monkeypatch.setattr(bi, "fetch_garmin_daily", _second_fails)
    with patch.object(bi, "_present_dates", return_value=set()):
        result = bi.run_one_batch()
    assert result["ok"] is True
    assert result["processed"] == 1
    assert result["done"] is False


def test_per_day_unexpected_error_isolated(monkeypatch, writer):
    def _first_raises(d):
        if d == _day(0):
            raise RuntimeError("weird payload")
        return _daily(d)

    monkeypatch.setattr(bi, "fetch_garmin_daily", _first_raises)
    present = {_day(i) for i in range(91)}
    with patch.object(bi, "_present_dates", return_value=present):
        result = bi.run_one_batch()
    assert result["ok"] is True
    assert result["processed"] == 2  # bad day counted, good day written
    written = {c.args[0]["date"] for c in writer.call_args_list}
    assert written == {_day(1)}
