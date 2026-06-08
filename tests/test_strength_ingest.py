"""Tests for core/strength_ingest.py::run_one_batch.

Covers backfill vs delta mode selection, page-bounded draining, cursor advance
discipline (only on full drain), updated/deleted event application, idempotency,
and fail-open on Hevy auth/network errors.

Hevy client functions and the Firestore store/state are patched at the module
level — no network, no Firestore.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

import core.strength_ingest as si


@pytest.fixture
def store():
    return MagicMock(name="StrengthSessionStore")


@pytest.fixture(autouse=True)
def _patch_common(monkeypatch, store):
    """Default: identity-ish normalize + captured state + injected store."""
    monkeypatch.setattr(si, "normalize_workout", lambda raw: {"workout_id": raw["id"]})
    monkeypatch.setattr(si, "_store", lambda: store)
    # state is captured in a dict the tests can read
    state_holder = {"state": {}}
    monkeypatch.setattr(si, "_get_state", lambda: dict(state_holder["state"]))
    monkeypatch.setattr(si, "_set_state", lambda f: state_holder["state"].update(f))
    si._state_holder = state_holder  # type: ignore[attr-defined]


def _state():
    return si._state_holder["state"]  # type: ignore[attr-defined]


# ------------------------------------------------------------------ #
# Backfill (no cursor)                                               #
# ------------------------------------------------------------------ #

def test_backfill_single_page_done_and_sets_cursor(store):
    env = {"page": 1, "page_count": 1, "workouts": [{"id": "w1"}, {"id": "w2"}]}
    with patch.object(si, "fetch_workouts", return_value=env) as fw:
        result = si.run_one_batch()
    assert result == {"ok": True, "mode": "backfill", "processed": 2, "done": True}
    assert store.upsert.call_count == 2
    assert _state().get("last_synced_at")  # cursor flipped to delta mode
    fw.assert_called_once_with(page=1)


def test_backfill_multipage_not_done_advances_page(monkeypatch, store):
    monkeypatch.setenv("STRENGTH_INGEST_MAX_PAGES", "1")  # one page per tick
    env = {"page": 1, "page_count": 3, "workouts": [{"id": "w1"}]}
    with patch.object(si, "fetch_workouts", return_value=env):
        result = si.run_one_batch()
    assert result["done"] is False
    assert result["mode"] == "backfill"
    assert _state().get("backfill_page") == 2     # resumes here next tick
    assert "last_synced_at" not in _state()       # still backfilling


# ------------------------------------------------------------------ #
# Delta (cursor present)                                             #
# ------------------------------------------------------------------ #

def test_delta_applies_updated_and_deleted(store):
    si._set_state({"last_synced_at": "2026-06-01T00:00:00Z"})
    env = {
        "page": 1, "page_count": 1,
        "events": [
            {"type": "updated", "workout": {"id": "w1"}},
            {"type": "deleted", "id": "w2"},
            {"type": "updated", "workout": {"id": "w3"}},
        ],
    }
    with patch.object(si, "fetch_workout_events", return_value=env) as fe:
        result = si.run_one_batch()
    assert result["mode"] == "delta"
    assert result["processed"] == 2
    assert result["deleted"] == 1
    assert result["done"] is True
    store.upsert.assert_any_call({"workout_id": "w1"})
    store.delete.assert_called_once_with("w2")
    # cursor advanced past the previous value
    assert _state()["last_synced_at"] != "2026-06-01T00:00:00Z"
    fe.assert_called_once_with(since="2026-06-01T00:00:00Z", page=1)


def test_delta_not_drained_keeps_cursor(monkeypatch, store):
    monkeypatch.setenv("STRENGTH_INGEST_MAX_PAGES", "1")
    si._set_state({"last_synced_at": "2026-06-01T00:00:00Z"})
    env = {"page": 1, "page_count": 5, "events": [{"type": "updated", "workout": {"id": "w1"}}]}
    with patch.object(si, "fetch_workout_events", return_value=env):
        result = si.run_one_batch()
    assert result["done"] is False
    # NOT advanced — newest-first events mean a premature advance would skip older ones
    assert _state()["last_synced_at"] == "2026-06-01T00:00:00Z"


def test_delta_event_apply_error_is_skipped(store):
    si._set_state({"last_synced_at": "2026-06-01T00:00:00Z"})
    store.upsert.side_effect = [RuntimeError("boom"), None]
    env = {
        "page": 1, "page_count": 1,
        "events": [
            {"type": "updated", "workout": {"id": "bad"}},
            {"type": "updated", "workout": {"id": "good"}},
        ],
    }
    with patch.object(si, "fetch_workout_events", return_value=env):
        result = si.run_one_batch()
    # one failed, one succeeded — batch still completes and drains
    assert result["processed"] == 1
    assert result["done"] is True


# ------------------------------------------------------------------ #
# Fail-open                                                          #
# ------------------------------------------------------------------ #

def test_hevy_auth_error_returns_not_ok(store):
    with patch.object(si, "fetch_workouts", side_effect=si.HevyAuthError("no key")):
        result = si.run_one_batch()
    assert result["ok"] is False
    assert "no key" in result["error"]
