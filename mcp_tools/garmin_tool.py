"""Garmin Connect tool — daily health snapshot.

Fetches sleep score, HRV, body battery, and resting heart rate for today.
Requires GARMIN_EMAIL and GARMIN_PASSWORD env vars.

Note: garminconnect uses email/password auth (Garmin has no public OAuth).
      Logins are per-call — no persistent session on Cloud Run.
"""
from __future__ import annotations

import logging
import os
from datetime import date

logger = logging.getLogger(__name__)


class GarminAuthError(Exception):
    """Raised when Garmin login fails (bad credentials or MFA required)."""


class GarminUnavailableError(Exception):
    """Raised when Garmin data cannot be fetched (API down, parse error)."""


def fetch_garmin_today() -> dict:
    """Fetch today's health summary from Garmin Connect.

    Returns:
        {
            "date":                str   (YYYY-MM-DD),
            "sleep_score":         int | None,
            "sleep_hours":         float | None,
            "hrv_status":          str | None  (e.g. "BALANCED", "LOW"),
            "body_battery_morning": int | None  (0-100),
            "resting_hr":          int | None,
        }

    Raises:
        GarminAuthError:       If login fails.
        GarminUnavailableError: If data retrieval or parsing fails.
    """
    email = os.environ.get("GARMIN_EMAIL")
    password = os.environ.get("GARMIN_PASSWORD")

    if not email or not password:
        raise GarminAuthError("GARMIN_EMAIL and GARMIN_PASSWORD env vars are required")

    try:
        from garminconnect import Garmin  # imported lazily — garminconnect is optional
        api = Garmin(email=email, password=password)
        api.login()
    except ImportError as exc:
        raise GarminUnavailableError(
            "garminconnect package is not installed — run: pip install garminconnect"
        ) from exc
    except Exception as exc:
        raise GarminAuthError(f"Garmin login failed: {exc}") from exc

    today = date.today().isoformat()

    try:
        result: dict = {"date": today}
        result.update(_fetch_sleep(api, today))
        result.update(_fetch_hrv(api, today))
        result.update(_fetch_body_battery(api, today))
        result.update(_fetch_stats(api, today))
        return result
    except Exception as exc:
        raise GarminUnavailableError(f"Garmin data fetch failed: {exc}") from exc


# ------------------------------------------------------------------ #
# Private helpers — each returns a partial dict, logs on failure     #
# ------------------------------------------------------------------ #

def _fetch_sleep(api, today: str) -> dict:
    try:
        data = api.get_sleep_data(today)
        dto = (data or {}).get("dailySleepDTO") or {}
        score_obj = dto.get("sleepScores") or {}
        overall = score_obj.get("overall") or {}
        sleep_score = overall.get("value")
        sleep_secs = dto.get("sleepTimeSeconds") or 0
        sleep_hours = round(sleep_secs / 3600, 1) if sleep_secs else None
    except Exception:
        logger.warning("Garmin: could not fetch sleep data", exc_info=True)
        sleep_score, sleep_hours = None, None

    return {"sleep_score": sleep_score, "sleep_hours": sleep_hours}


def _fetch_hrv(api, today: str) -> dict:
    try:
        data = api.get_hrv_data(today)
        summary = (data or {}).get("hrvSummary") or {}
        hrv_status = summary.get("status")
    except Exception:
        logger.warning("Garmin: could not fetch HRV data", exc_info=True)
        hrv_status = None

    return {"hrv_status": hrv_status}


def _fetch_body_battery(api, today: str) -> dict:
    try:
        data = api.get_body_battery(today, today)
        # Returns a list of {startTimestampGMT, endTimestampGMT, status, charged, drained}.
        # "charged" after overnight sleep = morning body battery reading.
        morning = None
        if data and isinstance(data, list):
            # Find the first "charged" entry of the day.
            charged_entries = [e for e in data if isinstance(e, dict) and e.get("charged")]
            if charged_entries:
                morning = charged_entries[0]["charged"]
    except Exception:
        logger.warning("Garmin: could not fetch body battery", exc_info=True)
        morning = None

    return {"body_battery_morning": morning}


def _fetch_stats(api, today: str) -> dict:
    try:
        data = api.get_stats(today)
        resting_hr = (data or {}).get("restingHeartRate")
    except Exception:
        logger.warning("Garmin: could not fetch daily stats", exc_info=True)
        resting_hr = None

    return {"resting_hr": resting_hr}
