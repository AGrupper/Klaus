# core/health_reads.py
"""Postgres range reader for daily_biometrics (Phase 30 — HLTH-01/03).

Complements ``core/recovery_metrics.py::fetch_biometric_rows`` — that function
is a "last N days" read with a partial column set, purpose-built for the
recovery-deviation signal, and MUST NOT be modified (RESEARCH.md Pitfall 2).
This module adds a true arbitrary date-range reader over the FULL
``daily_biometrics`` column set, for the health-pages sleep/recovery API route.

Read-only session convention (mirrors mcp_tools/database_tool.py::query_health_database):
``psycopg2.connect(dsn, connect_timeout=5)`` then
``conn.set_session(readonly=True, autocommit=True)``.

Never raises — degrades to ``[]`` on any failure (missing DSN, connection error,
query error). Callers running inside ``async def`` route handlers MUST wrap this
in ``loop.run_in_executor`` — this module makes no async guarantees of its own
(Pitfall 3 / the documented 2026-06-24 weekly-review-500 incident class).
"""
from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)


def fetch_biometric_range(start_date: str, end_date: str) -> list[dict]:
    """Read daily_biometrics rows in [start_date, end_date], oldest-first.

    Full column set: date, resting_hr, hrv_baseline, hrv_overnight, sleep_score,
    sleep_duration, body_battery_max, training_readiness.

    Args:
        start_date: ISO YYYY-MM-DD, inclusive lower bound.
        end_date:   ISO YYYY-MM-DD, inclusive upper bound.

    Returns:
        List of dicts (date isoformat str + the 7 biometric columns), oldest-first.
        ``[]`` when DATABASE_URL/PG_CONNECTION_STRING is unset, on any connection
        failure, or on any query error — never raises.
    """
    try:
        import psycopg2  # lazy import — keeps cold-start cheap when unused

        dsn = os.environ.get("DATABASE_URL") or os.environ.get("PG_CONNECTION_STRING")
        if not dsn:
            return []

        conn = psycopg2.connect(dsn, connect_timeout=5)
        try:
            conn.set_session(readonly=True, autocommit=True)
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT date::date, resting_hr, hrv_baseline, hrv_overnight, "
                    "sleep_score, sleep_duration, body_battery_max, training_readiness "
                    "FROM daily_biometrics "
                    "WHERE date >= %s AND date <= %s "
                    "ORDER BY date ASC",
                    (start_date, end_date),
                )
                rows = cur.fetchall()
        finally:
            conn.close()

        return [
            {
                "date": r[0].isoformat() if hasattr(r[0], "isoformat") else str(r[0]),
                "resting_hr": r[1],
                "hrv_baseline": r[2],
                "hrv_overnight": r[3],
                "sleep_score": r[4],
                "sleep_duration": r[5],
                "body_battery_max": r[6],
                "training_readiness": r[7],
            }
            for r in rows
        ]
    except Exception:
        logger.warning(
            "fetch_biometric_range(%r, %r) failed", start_date, end_date, exc_info=True
        )
        return []
