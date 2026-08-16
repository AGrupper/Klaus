"""Dense Garmin running pace history for threshold_pace trend — Phase 25 D-04.

fetch_dense_pace_history(today_iso) queries the Postgres `activities` table for
recent running activities and returns BenchmarkStore-shaped point dicts for use
by _handle_get_goal_projection (reactive path) and the Sunday cron (Plan 03).

Design decisions:
  - Pace derived as duration_sec / distance_m * 1000 (sec/km) — RESOLVED Open
    Question #1 in RESEARCH.md. Do NOT read the ambiguous `avg_pace` column.
  - Running activity types come from garmin_tool.RUNNING_ACTIVITY_TYPES (the
    single canonical set — includes track_running).
  - Minimum distance: 3000m. duration_sec must be > 0.
  - Aggregated per calendar day (AVG pace) so a day with several qualifying runs
    yields ONE deterministic point and LIMIT counts distinct days, not raw
    activities (WR-02 / IN-02). Last 90 days, newest day first, 20 distinct days.
  - today_iso is honoured (IN-01): the 90-day window cutoff is derived from the
    caller's date, not server wall-clock NOW(). It is validated with
    date.fromisoformat before being embedded, so only a self-computed ISO date
    literal (digits + hyphens) reaches the SQL — no user/LLM input, no injection
    surface (T-25-13 mitigation preserved). A malformed today_iso fails open to [].
  - Fails open to [] on any error — never raises.
"""
from __future__ import annotations

import logging
from datetime import date, timedelta

logger = logging.getLogger(__name__)


def fetch_dense_pace_history(today_iso: str) -> list[dict]:
    """Return up to 20 recent running-day paces as BenchmarkStore-shaped dicts.

    Each returned dict has the shape:
        {"date": "YYYY-MM-DD", "facet": "threshold_pace",
         "value": <float sec_per_km>, "unit": "sec_per_km"}

    Args:
        today_iso: Today's ISO date string "YYYY-MM-DD" (provided by caller per
                   CR-01 lesson). The 90-day window cutoff is computed from this
                   value; it is validated before being embedded in the SQL.

    Returns:
        List of pace dicts, newest day first. Empty list on any error.
    """
    try:
        from mcp_tools.database_tool import query_health_database
        from mcp_tools.garmin_tool import RUNNING_ACTIVITY_TYPES

        # IN-01: derive the window cutoff from the caller's date. Validating with
        # date.fromisoformat guarantees the embedded literal is a real ISO date
        # (a malformed/injection string raises here → caught → []), so the SQL
        # stays free of any unvalidated user/LLM input (T-25-13 preserved).
        cutoff = (date.fromisoformat(today_iso) - timedelta(days=90)).isoformat()

        # RUNNING_ACTIVITY_TYPES is a module-level frozenset constant (no
        # user/LLM input), so embedding it keeps the T-25-13 posture intact.
        type_list = ", ".join(f"'{t}'" for t in sorted(RUNNING_ACTIVITY_TYPES))

        sql = (
            "SELECT "
            "    date::date AS activity_date, "
            "    ROUND(AVG(duration_sec::numeric / distance_m * 1000), 1) AS pace_sec_per_km "
            "FROM activities "
            f"WHERE type IN ({type_list}) "
            f"  AND date >= '{cutoff}' "
            "  AND distance_m >= 3000 "
            "  AND duration_sec > 0 "
            "GROUP BY date::date "
            "ORDER BY activity_date DESC "
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
            if row.get("_truncated"):
                # Row-cap sentinel from query_health_database — not a data row.
                continue
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
