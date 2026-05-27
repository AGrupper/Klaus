"""Garmin Connect tool — daily health snapshot + Phase-19 extensions.

Fetches sleep score, HRV, body battery, and resting heart rate for today
(fetch_garmin_today). Phase 19 adds training status / recent activities /
ACWR computation atop the same garminconnect client.

Requires GARMIN_EMAIL and GARMIN_PASSWORD env vars.

Note: garminconnect uses email/password auth (Garmin has no public OAuth).
      Logins are per-call — no persistent session on Cloud Run.
      Tokens are cached in Firestore via the shared _authed_garmin_client()
      helper to mitigate IP rate-limit issues from repeated full logins.
"""
from __future__ import annotations

import collections
import logging
import os
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)


class GarminAuthError(Exception):
    """Raised when Garmin login fails (bad credentials or MFA required)."""


class GarminUnavailableError(Exception):
    """Raised when Garmin data cannot be fetched (API down, parse error)."""


def _get_garmin_tokens_from_firestore() -> str | None:
    try:
        from memory.firestore_db import _make_firestore_client
        project_id = os.environ["GCP_PROJECT_ID"]
        database = os.getenv("FIRESTORE_DATABASE", "(default)")
        client = _make_firestore_client(project_id, database)
        snap = client.collection("config").document("garmin_tokens").get()
        if snap.exists:
            return snap.to_dict().get("tokens_json")
    except Exception as e:
        logger.warning("Failed to retrieve Garmin tokens from Firestore: %s", e)
    return None


def _save_garmin_tokens_to_firestore(tokens_json: str) -> None:
    try:
        from memory.firestore_db import _make_firestore_client
        from google.cloud import firestore
        project_id = os.environ["GCP_PROJECT_ID"]
        database = os.getenv("FIRESTORE_DATABASE", "(default)")
        client = _make_firestore_client(project_id, database)
        client.collection("config").document("garmin_tokens").set({
            "tokens_json": tokens_json,
            "updated_at": firestore.SERVER_TIMESTAMP
        }, merge=True)
    except Exception as e:
        logger.warning("Failed to save Garmin tokens to Firestore: %s", e)


def _authed_garmin_client():
    """Login + token-cache management shared across all garmin fetch_* fns.

    Extracted in Phase 19 Plan 02 from fetch_garmin_today's inline auth dance
    so it can be reused by fetch_garmin_training_status and
    fetch_garmin_activities (RESEARCH §Garmin Live Reads — avoid 3x duplication).

    Returns:
        An authenticated `garminconnect.Garmin` API client.

    Raises:
        GarminAuthError: If GARMIN_EMAIL/GARMIN_PASSWORD env vars are missing
            or the login fails entirely.
        GarminUnavailableError: If the garminconnect package itself is not
            installed (treat as transient unavailability rather than auth).
    """
    email = os.environ.get("GARMIN_EMAIL")
    password = os.environ.get("GARMIN_PASSWORD")

    if not email or not password:
        raise GarminAuthError("GARMIN_EMAIL and GARMIN_PASSWORD env vars are required")

    try:
        from garminconnect import Garmin  # imported lazily — garminconnect is optional
        api = Garmin(email=email, password=password)

        # Try loading tokens from Firestore first to avoid full-login IP rate-limits.
        tokens_json = _get_garmin_tokens_from_firestore()
        tokens_loaded_successfully = False

        if tokens_json:
            try:
                logger.info("Attempting Garmin login using cached tokens from Firestore")
                api.login(tokenstore=tokens_json)
                tokens_loaded_successfully = True
                logger.info("Garmin login successful using cached tokens")
            except Exception as exc:
                logger.warning("Garmin token login failed (tokens may have expired): %s", exc)

        if not tokens_loaded_successfully:
            logger.info("Attempting full Garmin login with email and password")
            api.login()
            logger.info("Garmin full login successful")

        # Extract refreshed tokens and persist them if changed (so the next
        # cold start can reuse them).
        try:
            new_tokens_json = api.client.dumps()
            if new_tokens_json != tokens_json:
                logger.info("Garmin tokens changed/refreshed, saving to Firestore")
                _save_garmin_tokens_to_firestore(new_tokens_json)
        except Exception as exc:
            logger.warning("Failed to dump and save Garmin tokens: %s", exc)

    except ImportError as exc:
        raise GarminUnavailableError(
            "garminconnect package is not installed — run: pip install garminconnect"
        ) from exc
    except GarminAuthError:
        raise
    except Exception as exc:
        raise GarminAuthError(f"Garmin login failed: {exc}") from exc

    return api


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
    api = _authed_garmin_client()

    today = datetime.now(ZoneInfo("Asia/Jerusalem")).date().isoformat()

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


# ------------------------------------------------------------------ #
# PHASE 19 (Plan 02) — training-status / activities / ACWR           #
# ------------------------------------------------------------------ #

def _safe_extract_key(*sources, keys: tuple[str, ...]):
    """Best-effort extraction across known Garmin envelope shapes.

    Tries each `source` dict in order:
      1. Look for any of `keys` at the top level.
      2. Recurse one level into nested dict values (Garmin often wraps
         the actual data inside a single envelope key like
         {"someEnvelope": {...real fields...}}).

    Returns the first non-None match, else None.
    """
    for src in sources:
        if not isinstance(src, dict):
            continue
        for k in keys:
            if k in src and src[k] is not None:
                return src[k]
        for v in src.values():
            if isinstance(v, dict):
                for k in keys:
                    if k in v and v[k] is not None:
                        return v[k]
    return None


def fetch_garmin_training_status() -> dict:
    """Return today's Garmin training status, VO2 max, and load focus.

    GARMIN-01.

    Returns:
        {
            "vo2_max":         float | None,
            "training_status": str   | None,  # PRODUCTIVE / MAINTAINING / RECOVERY / DETRAINING / OVERREACHING
            "load_focus":      str   | None,  # BALANCED / HIGH_AEROBIC / ANAEROBIC / ...
        }

    Raises:
        GarminUnavailableError: On any fetch/parse failure.
    """
    api = _authed_garmin_client()
    today = datetime.now(ZoneInfo("Asia/Jerusalem")).date().isoformat()
    try:
        ts_raw = api.get_training_status(today) or {}
        mm_raw = api.get_max_metrics(today) or {}
        return {
            "vo2_max": _safe_extract_key(
                mm_raw, ts_raw,
                keys=("vO2MaxValue", "vo2MaxValue", "VO2MaxValue"),
            ),
            "training_status": _safe_extract_key(
                ts_raw, keys=("trainingStatus",),
            ),
            "load_focus": _safe_extract_key(
                ts_raw, keys=("loadFocus",),
            ),
        }
    except Exception as exc:
        raise GarminUnavailableError(f"training_status fetch failed: {exc}") from exc


def fetch_garmin_activities(days: int = 7) -> list[dict]:
    """Return normalized list of the last `days` activities.

    GARMIN-02.

    Args:
        days: How many days of history to fetch (inclusive of today).
            days=7 → window is today-6..today.

    Returns:
        List of dicts with keys:
          activity_id, date, type, duration_sec, distance_m,
          perceived_exertion, feel, training_load.
        Any value may be None when Garmin did not capture it.

    Raises:
        GarminUnavailableError: On fetch failure.
    """
    api = _authed_garmin_client()
    today = datetime.now(ZoneInfo("Asia/Jerusalem")).date()
    start = (today - timedelta(days=days - 1)).isoformat()
    end = today.isoformat()
    try:
        raw = api.get_activities_by_date(start, end) or []
    except Exception as exc:
        raise GarminUnavailableError(f"activities fetch failed: {exc}") from exc

    out: list[dict] = []
    for entry in raw:
        atype = entry.get("activityType")
        if isinstance(atype, dict):
            atype = atype.get("typeKey", "unknown")
        try:
            duration_sec = int(entry.get("duration") or 0)
        except (TypeError, ValueError):
            duration_sec = 0
        try:
            distance_m = float(entry["distance"]) if entry.get("distance") else None
        except (TypeError, ValueError, KeyError):
            distance_m = None
        out.append({
            "activity_id": entry.get("activityId"),
            "date": entry.get("startTimeLocal") or entry.get("startTimeGMT") or entry.get("startTimeGmt"),
            "type": atype or "unknown",
            "duration_sec": duration_sec,
            "distance_m": distance_m,
            "perceived_exertion": entry.get("directWorkoutRpe"),
            "feel": entry.get("directWorkoutFeel"),
            "training_load": entry.get("activityTrainingLoad"),
        })
    return out


def compute_acwr(activities: list[dict], today: date | None = None) -> dict:
    """Acute:Chronic Workload Ratio (pure function — no I/O).

    GARMIN-03.

    ACWR = mean(7d training_load) / mean(28d training_load).

    Sport-science context: ratio < 0.8 = undertraining; 0.8..1.3 = sweet spot;
    >= 1.5 = elevated injury risk.

    Args:
        activities: List of dicts with at minimum {"date": ISO-8601 string,
            "training_load": float | None}.
        today: Reference date (defaults to current Asia/Jerusalem date).
            The acute window is today-6..today; chronic window is today-27..today.

    Returns:
        {
            "acute":   float,           # mean training_load over last 7 days
            "chronic": float | None,    # mean over last 28 days; None if <14 days have data
            "ratio":   float | None,    # acute/chronic; None when chronic baseline is insufficient
        }
    """
    if today is None:
        today = datetime.now(ZoneInfo("Asia/Jerusalem")).date()

    by_date: dict[date, float] = collections.defaultdict(float)
    for a in activities:
        try:
            d = date.fromisoformat(str(a["date"])[:10])
        except (KeyError, ValueError, TypeError):
            continue
        load = a.get("training_load")
        if load is not None:
            try:
                by_date[d] += float(load)
            except (TypeError, ValueError):
                continue

    acute_days = [today - timedelta(days=i) for i in range(7)]
    chronic_days = [today - timedelta(days=i) for i in range(28)]

    acute = sum(by_date.get(d, 0.0) for d in acute_days) / 7.0
    chronic_days_with_data = sum(1 for d in chronic_days if d in by_date)

    if chronic_days_with_data < 14:
        return {"acute": round(acute, 1), "chronic": None, "ratio": None}

    chronic = sum(by_date.get(d, 0.0) for d in chronic_days) / 28.0
    ratio = (acute / chronic) if chronic else None
    return {
        "acute": round(acute, 1),
        "chronic": round(chronic, 1),
        "ratio": round(ratio, 2) if ratio is not None else None,
    }


def compute_acwr_from_db() -> dict:
    """Postgres-backed convenience wrapper for autonomous-tick layer 0.

    Reads the last 28 days from `activities` table and calls compute_acwr.
    Returns a sentinel `{"acute": 0.0, "chronic": None, "ratio": None}` on any
    failure — autonomous-tick layer 0 must never raise.
    """
    try:
        import psycopg2
        dsn = os.environ.get("DATABASE_URL") or os.environ.get("PG_CONNECTION_STRING")
        if not dsn:
            return {"acute": 0.0, "chronic": None, "ratio": None}
        today = datetime.now(ZoneInfo("Asia/Jerusalem")).date()
        cutoff = today - timedelta(days=28)
        with psycopg2.connect(dsn) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT date::date, training_load FROM activities WHERE date >= %s",
                    (cutoff,),
                )
                rows = cur.fetchall()
        acts = [{"date": r[0].isoformat(), "training_load": r[1]} for r in rows]
        return compute_acwr(acts, today=today)
    except Exception:
        logger.warning("compute_acwr_from_db failed", exc_info=True)
        return {"acute": 0.0, "chronic": None, "ratio": None}
