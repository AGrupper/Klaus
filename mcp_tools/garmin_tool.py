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
            "hrv_overnight":       int | None  (overnight average HRV, ms),
            "hrv_baseline":        int | None  (7-day average HRV, ms),
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
        # Numeric HRV for daily_biometrics persistence. Matches zip-ingest
        # semantics: hrv_overnight = overnight average (lastNightAvg),
        # hrv_baseline = the rolling 7-day average (weeklyAvg).
        hrv_overnight = summary.get("lastNightAvg")
        hrv_baseline = summary.get("weeklyAvg")
    except Exception:
        logger.warning("Garmin: could not fetch HRV data", exc_info=True)
        hrv_status = hrv_overnight = hrv_baseline = None

    return {
        "hrv_status": hrv_status,
        "hrv_overnight": hrv_overnight,
        "hrv_baseline": hrv_baseline,
    }


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


# ------------------------------------------------------------------ #
# Run-detail capture — full per-run telemetry (stride, cadence,      #
# vertical oscillation, ground contact, power, HR) + recorded laps.  #
#                                                                    #
# fetch_garmin_activities only returns the SUMMARY (distance/duration/#
# avg pace). These functions pull the per-run DETAIL that already     #
# lives in Garmin Connect — the same depth Hevy gives strength — so   #
# Klaus can coach on actual splits and dynamics, not generic pace.    #
# Persistence is RunDetailStore's job; normalize_run_detail is pure.  #
# ------------------------------------------------------------------ #

# Canonical running activity types (matches core/pace_history.py).
RUNNING_ACTIVITY_TYPES: frozenset[str] = frozenset(
    {"running", "trail_running", "treadmill_running"}
)

# Garmin detail-stream metricDescriptor keys → our canonical summary field.
# Each maps to a {min, avg, max} block in the normalized doc.
_DETAIL_METRIC_KEYS: dict[str, str] = {
    "directHeartRate": "hr_bpm",
    "directDoubleCadence": "cadence_spm",     # steps/min (both feet)
    "directStrideLength": "stride_length_cm",  # source metres → cm (see _to_cm)
    "directVerticalOscillation": "vertical_oscillation_cm",
    "directGroundContactTime": "ground_contact_ms",
    "directPower": "power_w",
    "directSpeed": "speed_mps",
}


def _first(d: dict, keys: tuple[str, ...], default=None):
    """Return the first present, non-None value among ``keys`` in ``d``.

    Garmin's split/lap DTOs vary field names across firmware/export shapes
    (e.g. averageHR vs avgHr), so callers pass every known alias.
    """
    if not isinstance(d, dict):
        return default
    for k in keys:
        v = d.get(k)
        if v is not None:
            return v
    return default


def _to_cm(v):
    """Coerce a stride/oscillation value to centimetres.

    Garmin reports stride length in metres on the detail stream (~1.2) but in
    centimetres on lap DTOs (~120). Heuristic: a value below 5 is metres.
    """
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return round(f * 100.0, 1) if f < 5 else round(f, 1)


def _run_local_date(activity: dict) -> str | None:
    """Asia/Jerusalem YYYY-MM-DD for an activity summary dict.

    Prefers startTimeLocal (already local), falling back to a tz-converted
    startTimeGMT. Returns None when neither parses, so callers fail-open.
    """
    local = activity.get("startTimeLocal") or activity.get("date")
    if isinstance(local, str) and len(local) >= 10 and local[4] == "-":
        return local[:10]
    gmt = activity.get("startTimeGMT") or activity.get("startTimeGmt")
    if isinstance(gmt, str):
        try:
            dt = datetime.fromisoformat(gmt.replace("Z", "+00:00"))
            return dt.astimezone(ZoneInfo("Asia/Jerusalem")).date().isoformat()
        except (ValueError, TypeError):
            return None
    return None


def fetch_run_detail_raw(activity_id) -> dict:
    """Pull the three per-activity payloads for ONE run. Network-only.

    Each sub-fetch is independently guarded, so a treadmill run with no running
    dynamics (no foot-pod / no strap) still yields a usable splits + summary doc
    rather than failing the whole activity.

    Args:
        activity_id: Garmin activity id.

    Returns:
        ``{"details": dict, "splits": dict|list, "hr_zones": list|dict}`` —
        any sub-key is ``{}``/``[]`` if that fetch failed.

    Raises:
        GarminAuthError / GarminUnavailableError: only if the client itself
            cannot be built (auth / package missing). Per-payload failures are
            swallowed.
    """
    api = _authed_garmin_client()
    out: dict = {"details": {}, "splits": {}, "hr_zones": []}

    try:
        # maxchart/maxpoly cap the returned point count at the source so the
        # detail payload stays bounded before it ever reaches the normalizer.
        out["details"] = api.get_activity_details(activity_id, maxchart=2000, maxpoly=4000) or {}
    except Exception:
        logger.warning("run_detail: get_activity_details(%s) failed", activity_id, exc_info=True)

    try:
        out["splits"] = api.get_activity_typed_splits(activity_id) or {}
    except Exception:
        logger.warning("run_detail: get_activity_typed_splits(%s) failed", activity_id, exc_info=True)
        try:
            out["splits"] = api.get_activity_splits(activity_id) or {}
        except Exception:
            logger.warning("run_detail: get_activity_splits(%s) failed", activity_id, exc_info=True)

    try:
        out["hr_zones"] = api.get_activity_hr_in_timezones(activity_id) or []
    except Exception:
        logger.warning("run_detail: get_activity_hr_in_timezones(%s) failed", activity_id, exc_info=True)

    return out


def _extract_summary(details: dict) -> dict:
    """Whole-run {min, avg, max} per metric from the detail time-series.

    Builds a metricDescriptor key→index map, then walks activityDetailMetrics
    rows. Preserves the full range of every data point (min/avg/max) without
    storing the raw per-second arrays. Returns {} when descriptors are absent.
    """
    descriptors = details.get("metricDescriptors") or []
    rows = details.get("activityDetailMetrics") or []
    if not descriptors or not rows:
        return {}

    idx: dict[str, int] = {}
    for desc in descriptors:
        key = desc.get("key")
        mi = desc.get("metricsIndex")
        if key in _DETAIL_METRIC_KEYS and isinstance(mi, int):
            idx[key] = mi

    collected: dict[str, list[float]] = {k: [] for k in idx}
    for row in rows:
        metrics = row.get("metrics") if isinstance(row, dict) else None
        if not isinstance(metrics, list):
            continue
        for key, mi in idx.items():
            if mi < len(metrics):
                v = metrics[mi]
                if v is not None:
                    try:
                        collected[key].append(float(v))
                    except (TypeError, ValueError):
                        continue

    summary: dict = {}
    for key, field in _DETAIL_METRIC_KEYS.items():
        vals = collected.get(key) or []
        if not vals:
            continue
        is_stride = key in ("directStrideLength", "directVerticalOscillation")
        lo, avg, hi = min(vals), sum(vals) / len(vals), max(vals)
        if is_stride:
            summary[field] = {"min": _to_cm(lo), "avg": _to_cm(avg), "max": _to_cm(hi)}
        else:
            summary[field] = {"min": round(lo, 1), "avg": round(avg, 1), "max": round(hi, 1)}
    return summary


def _extract_splits(splits) -> list[dict]:
    """Normalize Garmin laps EXACTLY as the watch recorded them.

    For an easy/tempo run Garmin auto-laps every 1 km → per-km rows; for an
    interval session the laps are the actual reps + recoveries. No re-chunking.

    Accepts either the typed-splits envelope (``{"splits": [...]}``) or the
    plain-splits envelope (``{"lapDTOs": [...]}``). Returns a list of canonical
    lap rows; ``[]`` when neither shape is present.
    """
    if isinstance(splits, dict):
        rows = splits.get("splits") or splits.get("lapDTOs") or []
    elif isinstance(splits, list):
        rows = splits
    else:
        rows = []

    out: list[dict] = []
    for i, lap in enumerate(rows):
        if not isinstance(lap, dict):
            continue
        dist = _first(lap, ("distance", "totalDistance"))
        dur = _first(lap, ("duration", "movingDuration", "elapsedDuration"))
        try:
            dist_f = float(dist) if dist is not None else None
            dur_f = float(dur) if dur is not None else None
        except (TypeError, ValueError):
            dist_f = dur_f = None
        pace = (
            round(dur_f / dist_f * 1000.0, 1)
            if dist_f and dur_f and dist_f > 0
            else None
        )
        out.append({
            "index": i + 1,
            "type": _first(lap, ("type", "splitType", "intensityType")),
            "distance_m": round(dist_f, 1) if dist_f is not None else None,
            "duration_sec": round(dur_f, 1) if dur_f is not None else None,
            "pace_sec_per_km": pace,
            "avg_hr": _first(lap, ("averageHR", "avgHr", "averageHr")),
            "avg_cadence_spm": _first(
                lap, ("averageRunningCadenceInStepsPerMinute", "averageRunCadence", "averageDoubleCadence")
            ),
            "avg_stride_length_cm": _to_cm(_first(lap, ("strideLength", "avgStrideLength"))),
            "avg_power_w": _first(lap, ("averagePower", "avgPower")),
            "elev_gain_m": _first(lap, ("elevationGain", "totalElevationGain")),
        })
    return out


def _extract_hr_zones(hr_zones) -> list[dict]:
    """Normalize HR-in-timezones into ``[{zone, seconds, pct}]``."""
    rows = hr_zones if isinstance(hr_zones, list) else (hr_zones or {}).get("zones") or []
    out: list[dict] = []
    total = 0.0
    parsed: list[tuple[int, float]] = []
    for z in rows:
        if not isinstance(z, dict):
            continue
        zone = _first(z, ("zoneNumber", "zone"))
        secs = _first(z, ("secsInZone", "secondsInZone"), 0) or 0
        try:
            secs = float(secs)
        except (TypeError, ValueError):
            secs = 0.0
        total += secs
        parsed.append((zone, secs))
    for zone, secs in parsed:
        out.append({
            "zone": zone,
            "seconds": round(secs, 1),
            "pct": round(secs / total * 100.0, 1) if total > 0 else None,
        })
    return out


def _active_laps(splits: list[dict]) -> list[dict]:
    """Laps that are running effort (exclude rest/recovery/walk/stand laps).

    Garmin types recovery laps ``INTERVAL_REST`` / ``RWD_WALK`` / ``RWD_STAND``.
    Untyped laps (steady auto-km laps) count as active.
    """
    out = []
    for lap in splits:
        t = (lap.get("type") or "").upper()
        if any(tok in t for tok in ("REST", "WALK", "STAND", "RECOVERY")):
            continue
        if lap.get("pace_sec_per_km") is not None:
            out.append(lap)
    return out


# A "split shape" is only a real pattern from a structured run. Fewer laps than
# this are almost always manual stops (a drink break, a crossing) — calling a
# 2-lap run a "negative split" reads an artifact as intent. Require enough laps
# AND a swing past the band before asserting a direction.
_SPLIT_SHAPE_MIN_LAPS = 4
_SPLIT_SHAPE_BAND = 0.04  # within ±4% reads "even", not negative/positive


def _compute_derived(splits: list[dict], summary: dict) -> dict:
    """Verdict-free coaching signals computed once from the recorded laps.

    - split_shape: negative / positive / even — ONLY from >= 4 active laps with a
      swing past ±4%; None otherwise (too few laps to read a real shape; few/uneven
      laps are usually manual stops, not a pacing strategy).
    - active_lap_count: how many running laps the watch recorded (lets coaching see
      "only 2 laps" and not over-read them).
    - cadence_drift: avg cadence first third vs last third of active laps (spm).
    - hr_drift: (2nd-half − 1st-half mean HR) / 1st-half, over active laps.
    - pace_cv: coefficient of variation of active-lap pace = interval consistency.
    """
    active = _active_laps(splits)
    derived: dict = {
        "split_shape": None,
        "active_lap_count": len(active),
        "cadence_drift": None,
        "hr_drift": None,
        "pace_cv": None,
    }
    if len(active) < 2:
        return derived

    paces = [l["pace_sec_per_km"] for l in active if l.get("pace_sec_per_km") is not None]
    half = len(active) // 2

    if len(paces) >= 2:
        # pace_cv is a fact for any multi-lap run; split_shape needs enough laps.
        mean = sum(paces) / len(paces)
        if mean > 0:
            var = sum((p - mean) ** 2 for p in paces) / len(paces)
            derived["pace_cv"] = round((var ** 0.5) / mean, 3)

        if len(paces) >= _SPLIT_SHAPE_MIN_LAPS:
            first = paces[: len(paces) // 2]
            second = paces[len(paces) // 2 :]
            m1, m2 = sum(first) / len(first), sum(second) / len(second)
            if m1 > 0:
                delta = (m2 - m1) / m1
                if delta < -_SPLIT_SHAPE_BAND:
                    derived["split_shape"] = "negative"
                elif delta > _SPLIT_SHAPE_BAND:
                    derived["split_shape"] = "positive"
                else:
                    derived["split_shape"] = "even"

    cad = [l["avg_cadence_spm"] for l in active if l.get("avg_cadence_spm") is not None]
    if len(cad) >= 3:
        third = max(1, len(cad) // 3)
        c1 = sum(cad[:third]) / third
        c2 = sum(cad[-third:]) / third
        derived["cadence_drift"] = round(c2 - c1, 1)

    hrs = [l["avg_hr"] for l in active if l.get("avg_hr") is not None]
    if len(hrs) >= 2:
        h1 = hrs[:half] or hrs[:1]
        h2 = hrs[half:] or hrs[-1:]
        mh1, mh2 = sum(h1) / len(h1), sum(h2) / len(h2)
        if mh1 > 0:
            derived["hr_drift"] = round((mh2 - mh1) / mh1, 3)

    return derived


def normalize_run_detail(activity: dict, details: dict, splits, hr_zones) -> dict:
    """Convert raw Garmin run payloads into the canonical RunDetailStore shape.

    Pure function (no I/O) — mirrors ``mcp_tools.hevy_tool.normalize_workout``.
    Stores per-lap detail + whole-run {min,avg,max} summary + derived signals,
    NOT the raw per-second streams (kept Firestore-doc-sized, brain-reasoning-sized).

    Args:
        activity: a summary dict from :func:`fetch_garmin_activities` (gives
            activity_id, type, date, duration_sec, distance_m).
        details:  raw ``get_activity_details`` envelope.
        splits:   raw ``get_activity_typed_splits`` (or ``get_activity_splits``).
        hr_zones: raw ``get_activity_hr_in_timezones``.

    Returns:
        Canonical run-detail doc (see plan). ``has_dynamics`` is False when the
        run carries no cadence/stride telemetry (treadmill / no strap), so the
        prompt can gate dynamics commentary and never fabricate it.
    """
    summary = _extract_summary(details)
    lap_rows = _extract_splits(splits)
    zones = _extract_hr_zones(hr_zones)
    derived = _compute_derived(lap_rows, summary)

    dist = activity.get("distance_m")
    dur = activity.get("duration_sec")
    try:
        avg_pace = (
            round(float(dur) / float(dist) * 1000.0, 1)
            if dist and dur and float(dist) > 0
            else None
        )
    except (TypeError, ValueError):
        avg_pace = None

    has_dynamics = bool(summary.get("cadence_spm") or summary.get("stride_length_cm"))

    return {
        "activity_id": str(activity.get("activity_id")),
        "date": _run_local_date(activity),
        "type": activity.get("type"),
        "duration_sec": dur,
        "distance_m": dist,
        "avg_pace_sec_per_km": avg_pace,
        "summary": summary,
        "splits": lap_rows,
        "hr_zones": zones,
        "derived": derived,
        "has_dynamics": has_dynamics,
    }


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


def write_today_biometrics_to_postgres(garmin: dict) -> None:
    """Best-effort UPSERT of today's biometrics into Postgres (GARMIN-05).

    Called from core/morning_briefing.py _gather_data after fetch_garmin_today
    succeeds. Postgres outage MUST NOT block the briefing — all exceptions
    logged + swallowed.

    Maps fetch_garmin_today's snake_case dict to daily_biometrics columns:
      date, resting_hr, hrv_baseline, hrv_overnight, sleep_score,
      sleep_duration, body_battery_max, training_readiness, vo2_max

    Args:
        garmin: dict from fetch_garmin_today (must include 'date').

    Returns:
        None always — best-effort write, never raises.
    """
    dsn = os.environ.get("DATABASE_URL") or os.environ.get("PG_CONNECTION_STRING")
    if not dsn:
        logger.info("write_today_biometrics: DATABASE_URL unset — skipping")
        return None
    try:
        import psycopg2  # lazy import — keeps cold-start cheap when unused
    except ImportError:
        logger.warning("write_today_biometrics: psycopg2 not installed")
        return None
    try:
        date_str = garmin.get("date")
        if not date_str:
            logger.warning("write_today_biometrics: garmin dict missing 'date' key")
            return None
        params = (
            date_str,
            garmin.get("resting_hr"),
            garmin.get("hrv_baseline"),
            garmin.get("hrv_overnight"),
            garmin.get("sleep_score"),
            garmin.get("sleep_duration") or garmin.get("sleep_hours"),
            garmin.get("body_battery_max"),
            garmin.get("training_readiness"),
            garmin.get("vo2_max"),
        )
        sql = """
            INSERT INTO daily_biometrics (
                date, resting_hr, hrv_baseline, hrv_overnight, sleep_score,
                sleep_duration, body_battery_max, training_readiness, vo2_max
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (date) DO UPDATE SET
                resting_hr = EXCLUDED.resting_hr,
                hrv_baseline = EXCLUDED.hrv_baseline,
                hrv_overnight = EXCLUDED.hrv_overnight,
                sleep_score = EXCLUDED.sleep_score,
                sleep_duration = EXCLUDED.sleep_duration,
                body_battery_max = EXCLUDED.body_battery_max,
                training_readiness = EXCLUDED.training_readiness,
                vo2_max = EXCLUDED.vo2_max
        """
        with psycopg2.connect(dsn) as conn:
            with conn.cursor() as cur:
                cur.execute(sql, params)
    except Exception:
        logger.warning(
            "write_today_biometrics: best-effort write failed", exc_info=True,
        )
        return None
    return None
