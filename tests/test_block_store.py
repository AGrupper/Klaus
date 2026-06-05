"""Tests for memory/firestore_db.py::BlockStore — Phase 23 BLOCK-01.

RED tests — written before implementation. All should FAIL until BlockStore
is added to memory/firestore_db.py.

Tests cover:
  - get_current() resolves active block by DATE RANGE (start_date <= today <= end_date)
  - Automatic Block1 -> Block2 transition without start_block call (D-01 contract)
  - Returns None pre-cycle and post-cycle
  - Never raises on Firestore exception
  - get_current result is json-safe (no DatetimeWithNanoseconds)
  - Week number helper: get_week_num formula correctness
  - upsert uses merge=True
  - set_benchmark_due writes the flag via merge
  - start_block / end_block update status (bookkeeping only)

Mocks google.cloud.firestore at sys.modules level so tests run without the lib
installed — mirrors tests/test_training_log_store.py pattern.
"""
from __future__ import annotations

import json
import sys
from datetime import date, timedelta
from types import ModuleType
from unittest.mock import MagicMock


def _install_firestore_mock() -> MagicMock:
    """Install mock google.cloud.firestore + force re-import of firestore_db.

    Mirrors tests/test_training_log_store.py — evict and re-import memory.firestore_db
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

    # Force re-import so `from google.cloud import firestore` rebinds to OUR mock.
    if "memory.firestore_db" in sys.modules:
        del sys.modules["memory.firestore_db"]

    return firestore_mock


import pytest

# Bound per-test by the autouse fixture below. We deliberately do NOT install
# the mock or import memory.firestore_db at module/collection time — that leaks
# fake google.* modules into sys.modules for the whole session and breaks
# sibling test files.
BlockStore = None  # type: ignore[assignment]
get_week_num = None  # type: ignore[assignment]
_FS = None  # type: ignore[assignment]


@pytest.fixture(autouse=True)
def _firestore_mock(isolated_modules):
    global BlockStore, get_week_num, _FS
    import importlib
    _FS = _install_firestore_mock()
    mod = importlib.import_module("memory.firestore_db")
    BlockStore = mod.BlockStore
    get_week_num = mod.get_week_num


# ---------------------------------------------------------------------------
# Locked 4-block table (from closed_sets in 23-01-PLAN.md)
# ---------------------------------------------------------------------------

_BLOCKS = [
    {
        "block_id": "2026-06-21_aerobic_base",
        "label": "Aerobic Base",
        "start_date": "2026-06-21",
        "end_date": "2026-07-18",
        "status": "active",
        "benchmark_due": False,
        "focus_facets": ["bench_press_1rm", "squat_1rm", "push_ups", "pull_ups", "threshold_pace"],
        "weekly_split_override": None,
        "notes": "",
    },
    {
        "block_id": "2026-07-19_capacity_build",
        "label": "Capacity Build",
        "start_date": "2026-07-19",
        "end_date": "2026-08-15",
        "status": "pending",
        "benchmark_due": False,
        "focus_facets": ["bench_press_1rm", "squat_1rm", "push_ups", "pull_ups", "threshold_pace"],
        "weekly_split_override": None,
        "notes": "",
    },
    {
        "block_id": "2026-08-16_deep_waters___peak_engine",
        "label": "Deep Waters → Peak Engine",
        "start_date": "2026-08-16",
        "end_date": "2026-09-12",
        "status": "pending",
        "benchmark_due": False,
        "focus_facets": ["bench_press_1rm", "squat_1rm", "push_ups", "pull_ups", "threshold_pace"],
        "weekly_split_override": None,
        "notes": "",
    },
    {
        "block_id": "2026-09-13_race_specificity___taper___race_week",
        "label": "Race Specificity → Taper → Race Week",
        "start_date": "2026-09-13",
        "end_date": "2026-10-10",
        "status": "pending",
        "benchmark_due": False,
        "focus_facets": ["bench_press_1rm", "squat_1rm", "push_ups", "pull_ups", "threshold_pace"],
        "weekly_split_override": None,
        "notes": "",
    },
]


def _make_snaps(blocks: list[dict]) -> list[MagicMock]:
    """Build mock Firestore snapshots for a list of block dicts."""
    snaps = []
    for b in blocks:
        snap = MagicMock()
        snap.id = b["block_id"]
        snap.to_dict.return_value = dict(b)
        snaps.append(snap)
    return snaps


def _store() -> "BlockStore":
    """Build a BlockStore with a fully-mocked Firestore client."""
    s = BlockStore.__new__(BlockStore)  # bypass __init__
    s._client = MagicMock()
    s._col = MagicMock()
    return s


# ------------------------------------------------------------------ #
# get_current — date-range resolution (D-01)                          #
# ------------------------------------------------------------------ #

def test_get_current_resolves_by_date_range():
    """get_current returns the block whose date range contains today."""
    s = _store()
    s._col.stream.return_value = _make_snaps(_BLOCKS)

    result = s.get_current(today="2026-06-25")  # inside Block 1 range

    assert result is not None
    assert result["label"] == "Aerobic Base"
    assert result["doc_id"] == "2026-06-21_aerobic_base"


def test_get_current_returns_block2_without_start_block():
    """D-01 automatic-transition contract: Block 2 is returned when today is in
    its date range — even with NO start_block call and Block 2 status still "pending".

    A status==active filter would wrongly return Block 1 (status active) or None.
    get_current MUST resolve purely by date range.
    """
    s = _store()
    s._col.stream.return_value = _make_snaps(_BLOCKS)

    result = s.get_current(today="2026-07-25")  # inside Block 2 range

    assert result is not None, "Expected Block 2 but got None — did get_current filter on status?"
    assert result["label"] == "Capacity Build", (
        f"Expected 'Capacity Build' but got {result.get('label')!r} — "
        "get_current must use date-range resolution, NOT status==active filter"
    )


def test_get_current_returns_none_pre_cycle():
    """get_current returns None when today is before the earliest start_date."""
    s = _store()
    s._col.stream.return_value = _make_snaps(_BLOCKS)

    result = s.get_current(today="2026-06-10")  # before 2026-06-21

    assert result is None


def test_get_current_returns_none_post_cycle():
    """get_current returns None when today is after the latest end_date."""
    s = _store()
    s._col.stream.return_value = _make_snaps(_BLOCKS)

    result = s.get_current(today="2026-10-20")  # after 2026-10-10

    assert result is None


def test_get_current_never_raises():
    """get_current returns None on Firestore exception — never raises."""
    s = _store()
    s._col.stream.side_effect = RuntimeError("firestore down")

    result = s.get_current(today="2026-06-25")

    assert result is None


def test_get_current_jsonsafe():
    """get_current result with SERVER_TIMESTAMP sentinel is json.dumps-safe."""
    s = _store()
    # Simulate a block doc with an updated_at SERVER_TIMESTAMP (resolves to a datetime)
    from datetime import datetime
    block_with_ts = dict(_BLOCKS[0])
    block_with_ts["updated_at"] = datetime(2026, 6, 21, 8, 0, 0)
    snap = MagicMock()
    snap.id = block_with_ts["block_id"]
    snap.to_dict.return_value = block_with_ts
    # Add remaining blocks (no overlap)
    remaining_snaps = [snap] + _make_snaps(_BLOCKS[1:])
    s._col.stream.return_value = remaining_snaps

    result = s.get_current(today="2026-06-25")

    assert result is not None
    # Must not raise
    json.dumps(result)


# ------------------------------------------------------------------ #
# get_week_num helper (D-03)                                          #
# ------------------------------------------------------------------ #

PLAN_START = "2026-06-21"


def test_week_num_formula_boundary_same_day():
    """today == start_date → week 1."""
    assert get_week_num(PLAN_START, "2026-06-21") == 1


def test_week_num_formula_boundary_day_6():
    """start_date + 6 days → still week 1."""
    assert get_week_num(PLAN_START, "2026-06-27") == 1


def test_week_num_formula_boundary_day_7():
    """start_date + 7 days → week 2."""
    assert get_week_num(PLAN_START, "2026-06-28") == 2


def test_week_num_formula_before_start():
    """today < start_date → None."""
    assert get_week_num(PLAN_START, "2026-06-10") is None


# ------------------------------------------------------------------ #
# upsert / set_benchmark_due — merge=True                             #
# ------------------------------------------------------------------ #

def test_upsert_uses_merge_true():
    """BlockStore.upsert calls .set with merge=True."""
    s = _store()
    doc_mock = MagicMock()
    s._col.document.return_value = doc_mock

    block = dict(_BLOCKS[0])
    s.upsert(block)

    args, kwargs = doc_mock.set.call_args
    assert kwargs.get("merge") is True


def test_set_benchmark_due_writes_flag():
    """set_benchmark_due(block_id, True) writes benchmark_due=True via merge."""
    s = _store()
    doc_mock = MagicMock()
    s._col.document.return_value = doc_mock

    s.set_benchmark_due("2026-06-21_aerobic_base", True)

    args, kwargs = doc_mock.set.call_args
    payload = args[0]
    assert payload.get("benchmark_due") is True
    assert kwargs.get("merge") is True


# ------------------------------------------------------------------ #
# start_block / end_block — bookkeeping only                          #
# ------------------------------------------------------------------ #

def test_start_end_block_update_status():
    """start_block sets status 'active'; end_block sets status 'complete' via merge."""
    s = _store()
    doc_mock = MagicMock()
    s._col.document.return_value = doc_mock

    s.start_block("2026-07-19_capacity_build")
    call_args_start = doc_mock.set.call_args
    payload_start = call_args_start[0][0]
    assert payload_start.get("status") == "active"
    assert call_args_start[1].get("merge") is True

    doc_mock.reset_mock()

    s.end_block("2026-07-19_capacity_build")
    call_args_end = doc_mock.set.call_args
    payload_end = call_args_end[0][0]
    assert payload_end.get("status") == "complete"
    assert call_args_end[1].get("merge") is True
