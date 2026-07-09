"""Tests for GET /api/health/sleep aggregator (Plan 30-02 Task 3 — HLTH-03).

WHY this module exists: Phase 30 (Health Pages) adds GET /api/health/sleep —
a read-only aggregator over Postgres daily_biometrics (core.health_reads.
fetch_biometric_range), executor-wrapped (Pitfall 3 — the 2026-06-24
weekly-review-500 incident class: a synchronous psycopg2 call inside async def
starves the event loop), exposing a pipeline_active flag distinct from an
empty range (Pitfall 4), and a rolling-median-of-hrv_overnight fallback when
the stored hrv_baseline column is sparse (Pitfall 5).

Pattern: mirrors tests/test_api_today.py's `_stub_web_server_imports` pattern
for route-level tests (helpers monkeypatched, no real Postgres I/O). The
range_reader test mocks psycopg2 at sys.modules level, mirroring
tests/test_health_reads.py's own convention (isolated_modules fixture).
"""
from __future__ import annotations

import os
import sys
from unittest.mock import MagicMock, patch

import pytest


_ENV = {
    "HUB_SESSION_SECRET": "test-secret-32-bytes-long-enough!",
    "HUB_ALLOWED_EMAIL": "amit.grupper@gmail.com",
    "GOOGLE_OAUTH_CLIENT_ID": "fake-client-id.apps.googleusercontent.com",
    "CRON_DEV_BYPASS": "true",
    "GCP_PROJECT_ID": "test-project",
    "FIRESTORE_DATABASE": "(default)",
    "TELEGRAM_BOT_TOKEN": "1234:fake",
    "TELEGRAM_ALLOWED_USER_IDS": "123456",
}


def _stub_web_server_imports() -> dict:
    """Mirrors tests/test_api_today.py::_stub_web_server_imports exactly."""
    stubs = {
        "telegram": sys.modules.get("telegram", MagicMock(name="telegram")),
        "telegram.ext": sys.modules.get("telegram.ext", MagicMock()),
        "telegram.error": sys.modules.get("telegram.error", MagicMock()),
        "core.auth_google": MagicMock(name="core.auth_google"),
        "core.main": MagicMock(name="core.main"),
        "interfaces._router": MagicMock(name="interfaces._router"),
    }
    for key in list(sys.modules.keys()):
        if (
            key == "interfaces.web_server"
            or key.startswith("interfaces.web_server.")
            or key == "interfaces.hub_auth"
            or key.startswith("interfaces.hub_auth.")
        ):
            del sys.modules[key]
    return stubs


_ROWS_FIXTURE = [
    {"date": "2026-07-01", "resting_hr": 52, "hrv_baseline": 60.0, "hrv_overnight": 58.0,
     "sleep_score": 78, "sleep_duration": 7.2, "body_battery_max": 68, "training_readiness": 8},
    {"date": "2026-07-02", "resting_hr": 51, "hrv_baseline": 61.0, "hrv_overnight": 59.5,
     "sleep_score": 82, "sleep_duration": 7.5, "body_battery_max": 72, "training_readiness": 9},
]


# ------------------------------------------------------------------ #
# Route-level tests (helpers monkeypatched — no real Postgres I/O)    #
# ------------------------------------------------------------------ #


def test_sleep_returns_series_header_stats_pipeline_active_true():
    """Rows present -> series + header_stats (from newest row) + pipeline_active True."""
    stubs = _stub_web_server_imports()
    with patch.dict(sys.modules, stubs):
        import interfaces.web_server as ws  # noqa: PLC0415
        from fastapi.testclient import TestClient  # noqa: PLC0415

        with patch.dict(os.environ, _ENV):
            ws._health_sleep_data = lambda start, end: _ROWS_FIXTURE
            ws._health_sleep_pipeline_active = lambda: True

            client = TestClient(ws.app, raise_server_exceptions=True)
            response = client.get("/api/health/sleep?range=30d")

        assert response.status_code == 200, response.text
        data = response.json()
        assert data["pipeline_active"] is True
        for key in ["hrv_overnight", "sleep_score", "sleep_duration", "body_battery_max",
                    "hrv_baseline"]:
            assert key in data["series"], f"Missing series key '{key}'"
        assert data["header_stats"]["date"] == "2026-07-02"
        assert data["header_stats"]["hrv_overnight"] == 59.5
        assert data["header_stats"]["resting_hr"] == 51
        assert data["header_stats"]["training_readiness"] == 9


def test_sleep_serializes_decimal_rows_without_500():
    """Decimal-valued rows (psycopg2 NUMERIC columns) must serialize to 200, not
    500. Regression for "Object of type Decimal is not JSON serializable" — the
    payload routes through _jsonsafe_doc, which now coerces Decimal → float even
    if a reader leaks one.
    """
    from decimal import Decimal  # noqa: PLC0415

    decimal_rows = [
        {"date": "2026-07-01", "resting_hr": 52, "hrv_baseline": Decimal("60.0"),
         "hrv_overnight": Decimal("58.5"), "sleep_score": 78,
         "sleep_duration": Decimal("7.2"), "body_battery_max": 68,
         "training_readiness": 8},
    ]
    stubs = _stub_web_server_imports()
    with patch.dict(sys.modules, stubs):
        import interfaces.web_server as ws  # noqa: PLC0415
        from fastapi.testclient import TestClient  # noqa: PLC0415

        with patch.dict(os.environ, _ENV):
            ws._health_sleep_data = lambda start, end: decimal_rows
            ws._health_sleep_pipeline_active = lambda: True

            client = TestClient(ws.app, raise_server_exceptions=True)
            response = client.get("/api/health/sleep?range=30d")

        assert response.status_code == 200, response.text
        data = response.json()
        assert data["header_stats"]["hrv_overnight"] == 58.5
        # Decimal coerced to a JSON number (float), not a string.
        assert isinstance(data["header_stats"]["hrv_overnight"], float)


def test_sleep_empty_table_pipeline_active_false():
    """Table entirely empty -> pipeline_active False + empty series/header_stats.

    Distinct from an empty-range test: pipeline_active is independently sourced
    (checked over the FULL table span, not the requested range).
    """
    stubs = _stub_web_server_imports()
    with patch.dict(sys.modules, stubs):
        import interfaces.web_server as ws  # noqa: PLC0415
        from fastapi.testclient import TestClient  # noqa: PLC0415

        with patch.dict(os.environ, _ENV):
            ws._health_sleep_data = lambda start, end: []
            ws._health_sleep_pipeline_active = lambda: False

            client = TestClient(ws.app, raise_server_exceptions=True)
            response = client.get("/api/health/sleep?range=30d")

        data = response.json()
        assert data["pipeline_active"] is False
        assert data["header_stats"] is None
        for series in data["series"].values():
            assert series == []


def test_sleep_empty_range_but_pipeline_active_true():
    """No rows in THIS range but the table has data elsewhere -> pipeline_active True.

    The key distinction Pitfall 4 requires: an empty selected range must not be
    conflated with a pipeline that has never run.
    """
    stubs = _stub_web_server_imports()
    with patch.dict(sys.modules, stubs):
        import interfaces.web_server as ws  # noqa: PLC0415
        from fastapi.testclient import TestClient  # noqa: PLC0415

        with patch.dict(os.environ, _ENV):
            ws._health_sleep_data = lambda start, end: []  # nothing in THIS range
            ws._health_sleep_pipeline_active = lambda: True  # but the table has rows

            client = TestClient(ws.app, raise_server_exceptions=True)
            response = client.get("/api/health/sleep?range=7d")

        data = response.json()
        assert data["pipeline_active"] is True
        assert data["header_stats"] is None  # nothing in range to derive stats from


def test_sleep_weekly_bucket_selectable():
    """range=1y series are weekly-bucketed; range=30d stays daily (D-07)."""
    stubs = _stub_web_server_imports()
    with patch.dict(sys.modules, stubs):
        import interfaces.web_server as ws  # noqa: PLC0415
        from fastapi.testclient import TestClient  # noqa: PLC0415

        with patch.dict(os.environ, _ENV):
            rows = [
                {"date": f"2026-06-{d:02d}", "resting_hr": 50, "hrv_baseline": 60.0,
                 "hrv_overnight": 58.0, "sleep_score": 80, "sleep_duration": 7.3,
                 "body_battery_max": 70, "training_readiness": 8}
                for d in range(1, 21)
            ]
            ws._health_sleep_data = lambda start, end: rows
            ws._health_sleep_pipeline_active = lambda: True

            client = TestClient(ws.app, raise_server_exceptions=True)
            resp_30d = client.get("/api/health/sleep?range=30d")
            resp_1y = client.get("/api/health/sleep?range=1y")

        daily_points = resp_30d.json()["series"]["sleep_score"]
        weekly_points = resp_1y.json()["series"]["sleep_score"]
        assert len(daily_points) == 20
        assert len(weekly_points) < len(daily_points)


def test_sleep_weekly_series_share_one_aligned_axis():
    """WR-04: at range=1y every sleep series (incl. hrv_overnight + hrv_baseline)
    buckets onto the SAME week axis — identical length + identical x labels —
    even when a metric is missing for a whole week (null-filled, not dropped), so
    overlaid lines/bars never slide out of alignment."""
    stubs = _stub_web_server_imports()
    with patch.dict(sys.modules, stubs):
        import interfaces.web_server as ws  # noqa: PLC0415
        from fastapi.testclient import TestClient  # noqa: PLC0415

        # 3 ISO weeks; the MIDDLE week has sleep_score/duration but NO
        # hrv_overnight — pre-fix this dropped that week from the HRV series only.
        rows = []
        for d in range(1, 22):  # 2026-06-01 .. 06-21 spans 3 iso weeks
            wk_missing_hrv = 8 <= d <= 14
            rows.append({
                "date": f"2026-06-{d:02d}", "resting_hr": 50,
                "hrv_baseline": None if wk_missing_hrv else 60.0,
                "hrv_overnight": None if wk_missing_hrv else 58.0,
                "sleep_score": 80, "sleep_duration": 7.3,
                "body_battery_max": 70, "training_readiness": 8,
            })
        with patch.dict(os.environ, _ENV):
            ws._health_sleep_data = lambda start, end: rows
            ws._health_sleep_pipeline_active = lambda: True
            client = TestClient(ws.app, raise_server_exceptions=True)
            data = client.get("/api/health/sleep?range=1y").json()["series"]

        # All series share one axis: same length and same ordered x labels.
        x_axes = {key: [p["x"] for p in pts] for key, pts in data.items()}
        reference = x_axes["sleep_score"]
        for key, xs in x_axes.items():
            assert xs == reference, f"series '{key}' x-axis diverged from the shared week axis"
        # The HRV-missing middle week is present as a null point, not dropped.
        hrv = data["hrv_overnight"]
        assert len(hrv) == len(data["sleep_score"])
        assert any(p["y"] is None for p in hrv)


def test_sleep_unauthenticated_returns_401():
    """GET /api/health/sleep without a valid hub session -> 401."""
    stubs = _stub_web_server_imports()
    with patch.dict(sys.modules, stubs):
        import interfaces.web_server as ws  # noqa: PLC0415
        from fastapi.testclient import TestClient  # noqa: PLC0415

        env_no_bypass = {**_ENV, "CRON_DEV_BYPASS": "false"}
        with patch.dict(os.environ, env_no_bypass):
            client = TestClient(ws.app, raise_server_exceptions=False)
            response = client.get("/api/health/sleep")

        assert response.status_code == 401, (
            f"Expected 401, got {response.status_code}: {response.text}"
        )


def test_sleep_baseline_fallback_fires_when_hrv_baseline_sparse():
    """hrv_baseline mostly null across in-range rows but hrv_overnight dense ->
    the HRV baseline series is populated via rolling-median-of-hrv_overnight
    fallback, not left all-null (Pitfall 5 / -k baseline_fallback)."""
    stubs = _stub_web_server_imports()
    with patch.dict(sys.modules, stubs):
        import interfaces.web_server as ws  # noqa: PLC0415
        from fastapi.testclient import TestClient  # noqa: PLC0415

        with patch.dict(os.environ, _ENV):
            rows = []
            for d in range(1, 11):
                rows.append({
                    "date": f"2026-06-{d:02d}",
                    "resting_hr": 50,
                    # Only the first 2 of 10 rows carry a stored baseline — sparse.
                    "hrv_baseline": 60.0 if d <= 2 else None,
                    "hrv_overnight": 55.0 + d,  # dense across all 10 rows
                    "sleep_score": 80,
                    "sleep_duration": 7.0,
                    "body_battery_max": 70,
                    "training_readiness": 8,
                })
            ws._health_sleep_data = lambda start, end: rows
            ws._health_sleep_pipeline_active = lambda: True

            client = TestClient(ws.app, raise_server_exceptions=True)
            response = client.get("/api/health/sleep?range=30d")

        baseline_series = response.json()["series"]["hrv_baseline"]
        non_null = [p for p in baseline_series if p["y"] is not None]
        assert non_null, (
            "hrv_baseline series left all-null — rolling-median fallback did not fire"
        )
        # The fallback must be a genuine rolling median of hrv_overnight, not the
        # (sparse) stored column re-surfaced verbatim.
        assert any(p["y"] != 60.0 for p in non_null)


def test_sleep_baseline_uses_stored_column_when_dense():
    """hrv_baseline densely populated -> the stored column is used as-is, no
    fallback substitution (guards against always-fallback regressions)."""
    stubs = _stub_web_server_imports()
    with patch.dict(sys.modules, stubs):
        import interfaces.web_server as ws  # noqa: PLC0415
        from fastapi.testclient import TestClient  # noqa: PLC0415

        with patch.dict(os.environ, _ENV):
            rows = [
                {"date": f"2026-06-{d:02d}", "resting_hr": 50, "hrv_baseline": 60.0 + d,
                 "hrv_overnight": 58.0, "sleep_score": 80, "sleep_duration": 7.0,
                 "body_battery_max": 70, "training_readiness": 8}
                for d in range(1, 11)
            ]
            ws._health_sleep_data = lambda start, end: rows
            ws._health_sleep_pipeline_active = lambda: True

            client = TestClient(ws.app, raise_server_exceptions=True)
            response = client.get("/api/health/sleep?range=30d")

        baseline_series = response.json()["series"]["hrv_baseline"]
        values = [p["y"] for p in baseline_series]
        assert values == [60.0 + d for d in range(1, 11)]


# ------------------------------------------------------------------ #
# range_reader — connection-failure test (redundant w/ test_health_  #
# reads.py at the module level, selectable within THIS file too per  #
# the plan's acceptance criteria)                                     #
# ------------------------------------------------------------------ #


def test_sleep_range_reader_connection_failure_returns_empty(monkeypatch, isolated_modules):
    """core.health_reads.fetch_biometric_range never raises on a connection
    failure — returns [] so the route degrades gracefully (-k range_reader)."""
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("PG_CONNECTION_STRING", raising=False)
    monkeypatch.setenv("DATABASE_URL", "postgresql://fake")

    psy = MagicMock()
    psy.connect.side_effect = RuntimeError("connection refused")
    sys.modules["psycopg2"] = psy

    from core.health_reads import fetch_biometric_range

    result = fetch_biometric_range("2026-06-01", "2026-06-30")

    assert result == []
