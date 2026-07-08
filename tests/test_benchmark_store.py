"""Tests for memory/firestore_db.py::BenchmarkStore — Phase 23 BLOCK-03.

RED tests — written before implementation. All should FAIL until BenchmarkStore
is added to memory/firestore_db.py.

Tests cover:
  - log_benchmark writes doc_id "{date}_{facet}" idempotently with merge=True
  - log_benchmark rejects facets outside the 5-facet closed set (ValueError)
  - get_facet_history streams, filters by facet, sorts date-desc, caps at n
  - get_block_benchmarks uses FieldFilter block_id → list date-desc
  - Read paths never raise on Firestore exception (return [])

Mocks google.cloud.firestore at sys.modules level so tests run without the lib
installed — mirrors tests/test_training_log_store.py pattern.
"""
from __future__ import annotations

import sys
from types import ModuleType
from unittest.mock import MagicMock

import pytest


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

    # Mock google.cloud.firestore_v1.base_query so FieldFilter imports succeed
    # in BenchmarkStore.get_block_benchmarks (and BlockStore equivalents).
    field_filter_cls = MagicMock()
    base_query_mod = ModuleType("google.cloud.firestore_v1.base_query")
    base_query_mod.FieldFilter = field_filter_cls  # type: ignore[attr-defined]
    firestore_v1_mod = ModuleType("google.cloud.firestore_v1")
    firestore_v1_mod.__path__ = []  # type: ignore[attr-defined]
    firestore_v1_mod.base_query = base_query_mod  # type: ignore[attr-defined]
    sys.modules["google.cloud.firestore_v1"] = firestore_v1_mod
    sys.modules["google.cloud.firestore_v1.base_query"] = base_query_mod
    setattr(google_cloud_mod, "firestore_v1", firestore_v1_mod)

    dotenv_mod = MagicMock()
    dotenv_mod.load_dotenv = MagicMock()
    sys.modules.setdefault("dotenv", dotenv_mod)

    # Force re-import so `from google.cloud import firestore` rebinds to OUR mock.
    if "memory.firestore_db" in sys.modules:
        del sys.modules["memory.firestore_db"]

    return firestore_mock


# Bound per-test by the autouse fixture below.
BenchmarkStore = None  # type: ignore[assignment]
_FS = None  # type: ignore[assignment]


@pytest.fixture(autouse=True)
def _firestore_mock(isolated_modules):
    global BenchmarkStore, _FS
    import importlib
    _FS = _install_firestore_mock()
    mod = importlib.import_module("memory.firestore_db")
    BenchmarkStore = mod.BenchmarkStore


def _store() -> "BenchmarkStore":
    """Build a BenchmarkStore with a fully-mocked Firestore client."""
    s = BenchmarkStore.__new__(BenchmarkStore)  # bypass __init__
    s._client = MagicMock()
    s._col = MagicMock()
    return s


# 5-facet closed set (D-06)
_VALID_FACETS = ["bench_press_1rm", "squat_1rm", "push_ups", "pull_ups", "threshold_pace"]
_BLOCK_ID = "2026-06-21_aerobic_base"


# ------------------------------------------------------------------ #
# log_benchmark — idempotent write                                    #
# ------------------------------------------------------------------ #

def test_log_benchmark_idempotent():
    """log_benchmark writes doc_id '{date}_{facet}' with merge=True."""
    s = _store()
    doc_mock = MagicMock()
    s._col.document.return_value = doc_mock

    s.log_benchmark(
        date="2026-07-18",
        facet="bench_press_1rm",
        value=92.5,
        unit="kg",
        block_id=_BLOCK_ID,
    )

    s._col.document.assert_called_once_with("2026-07-18_bench_press_1rm")
    args, kwargs = doc_mock.set.call_args
    assert kwargs.get("merge") is True


def test_log_benchmark_payload_fields():
    """log_benchmark writes all expected fields in the payload."""
    s = _store()
    doc_mock = MagicMock()
    s._col.document.return_value = doc_mock

    s.log_benchmark(
        date="2026-07-18",
        facet="squat_1rm",
        value=115.0,
        unit="kg",
        block_id=_BLOCK_ID,
        notes="tested fresh",
    )

    args, kwargs = doc_mock.set.call_args
    payload = args[0]
    assert payload["date"] == "2026-07-18"
    assert payload["facet"] == "squat_1rm"
    assert payload["value"] == 115.0
    assert payload["unit"] == "kg"
    assert payload["block_id"] == _BLOCK_ID
    assert payload["notes"] == "tested fresh"
    assert payload["updated_at"] is _FS.SERVER_TIMESTAMP


# ------------------------------------------------------------------ #
# log_benchmark — closed-set validation (V5 / T-23-01)               #
# ------------------------------------------------------------------ #

def test_log_benchmark_rejects_unknown_facet():
    """log_benchmark raises ValueError for a facet outside the 5-facet closed set."""
    s = _store()

    with pytest.raises(ValueError):
        s.log_benchmark(
            date="2026-07-18",
            facet="deadlift_1rm",  # not in the closed set
            value=140.0,
            unit="kg",
            block_id=_BLOCK_ID,
        )


@pytest.mark.parametrize("facet", _VALID_FACETS)
def test_log_benchmark_accepts_all_valid_facets(facet):
    """log_benchmark does not raise for any of the 5 valid facets."""
    s = _store()
    doc_mock = MagicMock()
    s._col.document.return_value = doc_mock

    # Should not raise
    s.log_benchmark(date="2026-07-18", facet=facet, value=1.0, unit="reps", block_id=_BLOCK_ID)


# ------------------------------------------------------------------ #
# get_facet_history                                                   #
# ------------------------------------------------------------------ #

def _make_benchmark_snap(date_str: str, facet: str, value: float) -> MagicMock:
    snap = MagicMock()
    snap.id = f"{date_str}_{facet}"
    snap.to_dict.return_value = {
        "date": date_str,
        "facet": facet,
        "value": value,
        "unit": "kg",
        "block_id": _BLOCK_ID,
        "notes": "",
    }
    return snap


def test_get_facet_history():
    """get_facet_history returns only the requested facet, date-desc, capped at n."""
    s = _store()
    snaps = [
        _make_benchmark_snap("2026-07-18", "bench_press_1rm", 92.5),
        _make_benchmark_snap("2026-06-21", "bench_press_1rm", 88.0),
        _make_benchmark_snap("2026-07-18", "squat_1rm", 115.0),  # different facet
    ]
    s._col.stream.return_value = snaps

    result = s.get_facet_history("bench_press_1rm", n=10)

    assert len(result) == 2
    # All returned should be the requested facet
    assert all(r["facet"] == "bench_press_1rm" for r in result)
    # Sorted date-desc
    assert result[0]["date"] == "2026-07-18"
    assert result[1]["date"] == "2026-06-21"


def test_get_facet_history_capped_at_n():
    """get_facet_history respects the n limit."""
    s = _store()
    snaps = [
        _make_benchmark_snap(f"2026-0{i}-01", "push_ups", float(i))
        for i in range(1, 8)  # 7 entries
    ]
    s._col.stream.return_value = snaps

    result = s.get_facet_history("push_ups", n=3)

    assert len(result) == 3


def test_get_facet_history_attaches_doc_id():
    """get_facet_history attaches doc_id to each result dict."""
    s = _store()
    snap = _make_benchmark_snap("2026-07-18", "pull_ups", 35.0)
    s._col.stream.return_value = [snap]

    result = s.get_facet_history("pull_ups", n=10)

    assert len(result) == 1
    assert result[0]["doc_id"] == "2026-07-18_pull_ups"


def test_benchmark_reads_never_raise_facet_history():
    """get_facet_history returns [] on Firestore exception — never raises."""
    s = _store()
    s._col.stream.side_effect = RuntimeError("firestore down")

    result = s.get_facet_history("bench_press_1rm", n=10)

    assert result == []


# ------------------------------------------------------------------ #
# get_block_benchmarks                                                #
# ------------------------------------------------------------------ #

def test_get_block_benchmarks():
    """get_block_benchmarks returns benchmarks for the given block, sorted date-desc."""
    s = _store()

    # Mock the FieldFilter query result
    query_mock = MagicMock()
    s._col.where.return_value = query_mock
    snaps = [
        _make_benchmark_snap("2026-07-18", "bench_press_1rm", 92.5),
        _make_benchmark_snap("2026-07-17", "squat_1rm", 115.0),
    ]
    query_mock.stream.return_value = snaps

    result = s.get_block_benchmarks(_BLOCK_ID)

    assert len(result) == 2
    # sorted date-desc
    assert result[0]["date"] == "2026-07-18"
    assert result[1]["date"] == "2026-07-17"


def test_benchmark_reads_never_raise_block_benchmarks():
    """get_block_benchmarks returns [] on Firestore exception — never raises."""
    s = _store()
    s._col.where.side_effect = RuntimeError("firestore down")

    result = s.get_block_benchmarks(_BLOCK_ID)

    assert result == []


def test_log_benchmark_rejects_bad_date_format():
    """IN-02: a malformed date raises ValueError before touching Firestore."""
    s = _store()
    with pytest.raises(ValueError):
        s.log_benchmark(
            date="2026/07/18",  # slash-separated, not ISO
            facet="bench_press_1rm",
            value=92.5,
            unit="kg",
            block_id=_BLOCK_ID,
        )


# ------------------------------------------------------------------ #
# get_range (Phase 30 — HLTH-01/03)                                   #
# ------------------------------------------------------------------ #

def _chained_query_mock(col_mock: MagicMock) -> MagicMock:
    """Return the terminal query mock at the end of a two-.where() chain."""
    return col_mock.where.return_value.where.return_value


def test_benchmark_get_range_in_range_newest_first():
    """get_range returns in-range docs sorted newest-first."""
    s = _store()
    snaps = [
        _make_benchmark_snap("2026-06-10", "bench_press_1rm", 90.0),
        _make_benchmark_snap("2026-06-20", "squat_1rm", 118.0),
    ]
    _chained_query_mock(s._col).stream.return_value = snaps

    result = s.get_range("2026-06-01", "2026-06-30")

    assert len(result) == 2
    assert result[0]["date"] == "2026-06-20"
    assert result[1]["date"] == "2026-06-10"


def test_benchmark_get_range_excludes_out_of_range():
    """get_range only returns docs that Firestore's FieldFilter chain yields —
    out-of-range docs are simulated as simply absent from the mocked stream."""
    s = _store()
    snaps = [_make_benchmark_snap("2026-06-15", "pull_ups", 22.0)]
    _chained_query_mock(s._col).stream.return_value = snaps

    result = s.get_range("2026-06-01", "2026-06-30")

    assert len(result) == 1
    assert result[0]["date"] == "2026-06-15"


def test_benchmark_get_range_interleaves_all_facets():
    """get_range returns benchmarks across all 5 facets in one call, not one facet."""
    s = _store()
    snaps = [
        _make_benchmark_snap("2026-06-01", "bench_press_1rm", 90.0),
        _make_benchmark_snap("2026-06-02", "squat_1rm", 118.0),
        _make_benchmark_snap("2026-06-03", "push_ups", 40.0),
        _make_benchmark_snap("2026-06-04", "pull_ups", 20.0),
        _make_benchmark_snap("2026-06-05", "threshold_pace", 4.2),
    ]
    _chained_query_mock(s._col).stream.return_value = snaps

    result = s.get_range("2026-06-01", "2026-06-30")

    facets_seen = {r["facet"] for r in result}
    assert facets_seen == set(_VALID_FACETS)


def test_benchmark_get_range_never_raises():
    """get_range returns [] on a mocked Firestore exception — never raises."""
    s = _store()
    s._col.where.side_effect = RuntimeError("firestore down")

    result = s.get_range("2026-06-01", "2026-06-30")

    assert result == []
