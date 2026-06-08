"""Tests for core/pace_history.py — fetch_dense_pace_history().

Covers the Phase 25 code-review fixes:
  - WR-02 / IN-02: per-day aggregation so LIMIT counts distinct days and the
    value for a day is deterministic (no same-day nondeterminism).
  - IN-01: today_iso is honoured — the 90-day window cutoff is derived from the
    caller's date, not server wall-clock NOW().
  - Fail-open to [] on error string / exception (T-25-13 discipline).
"""
from __future__ import annotations

import sys
import types

import core.pace_history as ph


def _install_fake_db(monkeypatch, capture: dict, rows):
    """Install a fake mcp_tools.database_tool.query_health_database."""
    fake_mod = types.ModuleType("mcp_tools.database_tool")

    def _fake_query(sql):
        capture["sql"] = sql
        return rows

    fake_mod.query_health_database = _fake_query
    monkeypatch.setitem(sys.modules, "mcp_tools.database_tool", fake_mod)
    # Ensure parent package import works
    if "mcp_tools" not in sys.modules:
        monkeypatch.setitem(sys.modules, "mcp_tools", types.ModuleType("mcp_tools"))


def test_sql_aggregates_per_day(monkeypatch):
    """The SQL groups by calendar day so LIMIT counts distinct days (WR-02/IN-02)."""
    capture: dict = {}
    _install_fake_db(monkeypatch, capture, [])
    ph.fetch_dense_pace_history("2026-08-01")
    sql = capture["sql"].lower()
    assert "group by" in sql
    # avg over the day's runs — deterministic representative pace
    assert "avg(" in sql
    # never reads the ambiguous avg_pace column (T-25-15)
    assert "avg_pace" not in sql


def test_today_iso_is_honoured_in_window(monkeypatch):
    """The 90-day cutoff is derived from today_iso, not server NOW() (IN-01)."""
    capture: dict = {}
    _install_fake_db(monkeypatch, capture, [])
    ph.fetch_dense_pace_history("2026-08-01")
    # 2026-08-01 minus 90 days = 2026-05-03
    assert "2026-05-03" in capture["sql"]
    # NOW() no longer drives the window
    assert "now()" not in capture["sql"].lower()


def test_returns_shaped_dicts(monkeypatch):
    """Rows map to BenchmarkStore-shaped threshold_pace dicts."""
    capture: dict = {}
    rows = [
        {"activity_date": "2026-07-18", "pace_sec_per_km": 245.0},
        {"activity_date": "2026-07-11", "pace_sec_per_km": 250.0},
    ]
    _install_fake_db(monkeypatch, capture, rows)
    out = ph.fetch_dense_pace_history("2026-08-01")
    assert out == [
        {"date": "2026-07-18", "facet": "threshold_pace", "value": 245.0, "unit": "sec_per_km"},
        {"date": "2026-07-11", "facet": "threshold_pace", "value": 250.0, "unit": "sec_per_km"},
    ]


def test_error_string_fails_open(monkeypatch):
    """A non-list (error string) from the DB tool yields [] (fail-open)."""
    capture: dict = {}
    _install_fake_db(monkeypatch, capture, "ERROR: connection refused")
    assert ph.fetch_dense_pace_history("2026-08-01") == []


def test_malformed_today_iso_fails_open(monkeypatch):
    """A malformed today_iso cannot inject SQL — it fails open to [] (defensive)."""
    capture: dict = {}
    _install_fake_db(monkeypatch, capture, [])
    assert ph.fetch_dense_pace_history("not-a-date'; DROP TABLE activities;--") == []
