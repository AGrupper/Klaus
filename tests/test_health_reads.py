"""Tests for core/health_reads.py::fetch_biometric_range — Phase 30 HLTH-01/03.

Tests cover:
  - Missing DSN (both env vars unset) -> [] without touching psycopg2
  - Successful fetch maps rows to the full 8-key dict, oldest-first
  - Read-only session convention: connect_timeout=5 + set_session(readonly=True, autocommit=True)
  - Query is parameterized (%s placeholders over the date range args), not f-string built
  - Connection failure (psycopg2.connect raises) -> [] (never raises)

Mocks psycopg2 at sys.modules level (the module under test does a lazy
`import psycopg2` inside the function) — mirrors tests/test_ingest_garmin.py
convention.
"""
from __future__ import annotations

import sys
from datetime import date
from unittest.mock import MagicMock

import pytest

from core.health_reads import fetch_biometric_range


@pytest.fixture(autouse=True)
def _clear_dsn_env(monkeypatch):
    """Every test starts with no DSN configured unless it opts in."""
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("PG_CONNECTION_STRING", raising=False)


def _install_psycopg2_mock() -> MagicMock:
    mock = MagicMock()
    sys.modules["psycopg2"] = mock
    return mock


# ------------------------------------------------------------------ #
# range_reader — missing DSN                                          #
# ------------------------------------------------------------------ #

def test_range_reader_missing_dsn_returns_empty():
    """No DATABASE_URL/PG_CONNECTION_STRING -> [] without touching psycopg2."""
    result = fetch_biometric_range("2026-06-01", "2026-06-30")
    assert result == []


# ------------------------------------------------------------------ #
# range_reader — success path                                         #
# ------------------------------------------------------------------ #

def test_range_reader_success_maps_full_column_set(monkeypatch):
    """A successful fetch maps rows to the full 8-key dict."""
    monkeypatch.setenv("DATABASE_URL", "postgresql://fake")
    psy = _install_psycopg2_mock()

    conn = MagicMock()
    cur = MagicMock()
    conn.cursor.return_value.__enter__.return_value = cur
    cur.fetchall.return_value = [
        (date(2026, 6, 15), 52, 61.0, 58.5, 78, 7.2, 68, 8),
    ]
    psy.connect.return_value = conn

    result = fetch_biometric_range("2026-06-01", "2026-06-30")

    assert result == [
        {
            "date": "2026-06-15",
            "resting_hr": 52,
            "hrv_baseline": 61.0,
            "hrv_overnight": 58.5,
            "sleep_score": 78,
            "sleep_duration": 7.2,
            "body_battery_max": 68,
            "training_readiness": 8,
        }
    ]

    # connect_timeout=5, read-only session (mirrors database_tool.py convention)
    psy.connect.assert_called_once_with("postgresql://fake", connect_timeout=5)
    conn.set_session.assert_called_once_with(readonly=True, autocommit=True)

    # Parameterized query — %s placeholders, args passed as a tuple (never f-string built)
    args, _kwargs = cur.execute.call_args
    sql, params = args
    assert "%s" in sql
    assert params == ("2026-06-01", "2026-06-30")


# ------------------------------------------------------------------ #
# range_reader — connection failure                                   #
# ------------------------------------------------------------------ #

def test_range_reader_connection_failure_returns_empty(monkeypatch):
    """psycopg2.connect raising -> [] (never raises)."""
    monkeypatch.setenv("DATABASE_URL", "postgresql://fake")
    psy = _install_psycopg2_mock()
    psy.connect.side_effect = RuntimeError("connection refused")

    result = fetch_biometric_range("2026-06-01", "2026-06-30")

    assert result == []


def test_range_reader_query_failure_returns_empty(monkeypatch):
    """A cursor.execute exception -> [] (never raises)."""
    monkeypatch.setenv("PG_CONNECTION_STRING", "postgresql://fallback")
    psy = _install_psycopg2_mock()

    conn = MagicMock()
    cur = MagicMock()
    conn.cursor.return_value.__enter__.return_value = cur
    cur.execute.side_effect = RuntimeError("query failed")
    psy.connect.return_value = conn

    result = fetch_biometric_range("2026-06-01", "2026-06-30")

    assert result == []
