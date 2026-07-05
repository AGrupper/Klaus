# core/recovery_metrics.py
"""Rolling recovery-deviation signal from the daily_biometrics history.

Answers one question: is TODAY's recovery (waking HRV / resting HR) genuinely
off Amit's own 7-day baseline? Consumed by the morning briefing and the
autonomous tick so Klaus can shape the day's training call — e.g. warn before
a planned hard track session when the trend is tanking.

Distinct from ``core.training_checkin.compute_recovery_concern``: that is
intensity-collision logic (high ACWR / low sleep score / Garmin's own HRV
status flag against TODAY's planned session). This module is pure baseline
math over the biometrics history that core/biometric_ingest.py now keeps
populated.

Silent-omit contract (D-13): returns None when nothing genuinely deviates or
there isn't enough history to know — never an "all clear" placeholder, never
noise narration (feedback: coaching calibration).
"""
from __future__ import annotations

import logging
import os
from statistics import median

logger = logging.getLogger(__name__)

# Deviation thresholds (v0 — tune with lived data; mirrors the
# RECOVERY_THRESHOLDS style in core/training_checkin.py).
DEVIATION_THRESHOLDS = {
    # today's overnight HRV below this fraction of the 7-day baseline → hrv_low
    "hrv_low_ratio": 0.90,
    # today's resting HR this many bpm above the 7-day baseline → rhr_elevated
    "rhr_elevated_bpm": 5,
    # minimum prior days with data before any baseline is trusted
    "min_baseline_days": 4,
}


def fetch_biometric_rows(days: int = 14) -> list[dict]:
    """Read recent daily_biometrics rows from Postgres. Never raises.

    Returns newest-first ``[{date, resting_hr, hrv_overnight, hrv_baseline,
    sleep_score}]``; ``[]`` on any failure (mirrors compute_acwr_from_db).
    """
    try:
        import psycopg2  # lazy import — keeps cold-start cheap when unused
        dsn = os.environ.get("DATABASE_URL") or os.environ.get("PG_CONNECTION_STRING")
        if not dsn:
            return []
        with psycopg2.connect(dsn) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT date::date, resting_hr, hrv_overnight, hrv_baseline, sleep_score "
                    "FROM daily_biometrics "
                    "WHERE date >= CURRENT_DATE - %s::int "
                    "ORDER BY date DESC",
                    (days,),
                )
                rows = cur.fetchall()
        return [
            {
                "date": r[0].isoformat() if hasattr(r[0], "isoformat") else str(r[0]),
                "resting_hr": r[1],
                "hrv_overnight": r[2],
                "hrv_baseline": r[3],
                "sleep_score": r[4],
            }
            for r in rows
        ]
    except Exception:
        logger.warning("recovery_metrics: biometrics read failed", exc_info=True)
        return []


def _numeric(values: list) -> list[float]:
    out = []
    for v in values:
        try:
            if v is not None:
                out.append(float(v))
        except (TypeError, ValueError):
            continue
    return out


def compute_recovery_deviation(rows: list[dict], today_iso: str) -> dict | None:
    """Compare today's HRV/RHR against the prior-7-day baseline. Pure.

    Baselines exclude today: HRV baseline prefers Garmin's own rolling weekly
    average (today's ``hrv_baseline`` column) when present, else the median of
    the prior days' ``hrv_overnight``; RHR baseline is the median of the prior
    days' ``resting_hr``.

    Returns None when today's row is absent, fewer than
    ``min_baseline_days`` prior days have data, or nothing crosses a
    threshold — silence is the default, deviation is the exception.
    """
    if not rows or not today_iso:
        return None

    today_row = next((r for r in rows if r.get("date") == today_iso), None)
    if not today_row:
        return None

    prior = [r for r in rows if r.get("date") and r["date"] < today_iso]
    # Prior 7 calendar days at most (rows come newest-first).
    prior = sorted(prior, key=lambda r: r["date"], reverse=True)[:7]

    prior_hrv = _numeric([r.get("hrv_overnight") for r in prior])
    prior_rhr = _numeric([r.get("resting_hr") for r in prior])
    days_of_data = max(len(prior_hrv), len(prior_rhr))
    if days_of_data < DEVIATION_THRESHOLDS["min_baseline_days"]:
        return None

    flags: list[str] = []
    out: dict = {"days_of_data": days_of_data}

    hrv_today = _numeric([today_row.get("hrv_overnight")])
    hrv_base = _numeric([today_row.get("hrv_baseline")])  # Garmin's weeklyAvg
    hrv_baseline = hrv_base[0] if hrv_base else (median(prior_hrv) if prior_hrv else None)
    if hrv_today and hrv_baseline and hrv_baseline > 0:
        ratio = hrv_today[0] / hrv_baseline
        out["hrv_overnight"] = hrv_today[0]
        out["hrv_baseline_7d"] = round(hrv_baseline, 1)
        out["hrv_deviation_pct"] = round((ratio - 1.0) * 100.0, 1)
        if ratio < DEVIATION_THRESHOLDS["hrv_low_ratio"]:
            flags.append("hrv_low")

    rhr_today = _numeric([today_row.get("resting_hr")])
    if rhr_today and prior_rhr:
        rhr_baseline = median(prior_rhr)
        delta = rhr_today[0] - rhr_baseline
        out["resting_hr"] = rhr_today[0]
        out["rhr_baseline_7d"] = round(rhr_baseline, 1)
        out["rhr_delta"] = round(delta, 1)
        if delta >= DEVIATION_THRESHOLDS["rhr_elevated_bpm"]:
            flags.append("rhr_elevated")

    if not flags:
        return None
    out["flags"] = flags
    return out


def get_recovery_deviation(today_iso: str, days: int = 14) -> dict | None:
    """Convenience: fetch rows + compute deviation. Never raises."""
    try:
        return compute_recovery_deviation(fetch_biometric_rows(days), today_iso)
    except Exception:
        logger.warning("recovery_metrics: deviation computation failed", exc_info=True)
        return None
