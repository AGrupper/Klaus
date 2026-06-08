"""Dense Garmin running pace history for threshold_pace trend — Phase 25 D-04.

fetch_dense_pace_history(today_iso) queries the Postgres `activities` table for
recent running activities and returns BenchmarkStore-shaped point dicts for use
by _handle_get_goal_projection (reactive path) and the Sunday cron (Plan 03).

Design decisions:
  - Pace derived as duration_sec / distance_m * 1000 (sec/km) — RESOLVED Open
    Question #1 in RESEARCH.md. Do NOT read the ambiguous `avg_pace` column.
  - Running activity types: 'running', 'trail_running', 'treadmill_running'.
  - Minimum distance: 3000m. duration_sec must be > 0.
  - Last 90 days, newest-first, LIMIT 20.
  - today_iso is accepted for signature parity / future use but the SQL uses
    server-side NOW() — caller must NOT pass user/LLM input into the query.
  - Fails open to [] on any error — never raises.
  - SQL contains only hardcoded literals + server-side NOW() (T-25-13 mitigation).
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

logger = logging.getLogger(__name__)


def fetch_dense_pace_history(today_iso: str) -> list[dict]:
    """Return up to 20 recent running activity paces as BenchmarkStore-shaped dicts.

    Each returned dict has the shape:
        {"date": "YYYY-MM-DD", "facet": "threshold_pace",
         "value": <float sec_per_km>, "unit": "sec_per_km"}

    Args:
        today_iso: Today's ISO date string "YYYY-MM-DD" (provided by caller per
                   CR-01 lesson; SQL uses server-side NOW() and does not embed this
                   value — it is accepted for signature parity with future callers).

    Returns:
        List of pace dicts, newest first. Empty list on any error.
    """
    try:
        from mcp_tools.database_tool import query_health_database

        sql = (
            "SELECT "
            "    date::date AS activity_date, "
            "    duration_sec, "
            "    distance_m, "
            "    ROUND((duration_sec::numeric / distance_m * 1000), 1) AS pace_sec_per_km "
            "FROM activities "
            "WHERE type IN ('running', 'trail_running', 'treadmill_running') "
            "  AND date >= NOW() - INTERVAL '90 days' "
            "  AND distance_m >= 3000 "
            "  AND duration_sec > 0 "
            "ORDER BY date DESC "
            "LIMIT 20"
        )

        rows = query_health_database(sql)

        if not isinstance(rows, list):
            # query_health_database returns a str on error
            logger.warning(
                "pace_history: query_health_database returned error: %s", rows
            )
            return []

        result: list[dict] = []
        for row in rows:
            pace = row.get("pace_sec_per_km")
            if pace is None:
                continue
            activity_date = row.get("activity_date")
            if activity_date is None:
                continue
            # Normalize date to ISO string (Postgres may return a date object or string)
            if hasattr(activity_date, "isoformat"):
                date_str = activity_date.isoformat()
            else:
                date_str = str(activity_date)[:10]
            result.append({
                "date": date_str,
                "facet": "threshold_pace",
                "value": float(pace),
                "unit": "sec_per_km",
            })

        return result

    except Exception:
        logger.warning("pace_history: fetch_dense_pace_history failed", exc_info=True)
        return []
