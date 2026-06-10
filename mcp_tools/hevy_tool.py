"""Hevy strength-training tool — pull full per-set workout data from the Hevy API.

The Hevy developer API (https://api.hevyapp.com) is **Pro-only**.  Requires the
``HEVY_API_KEY`` env var (a UUID generated at https://hevy.com/settings?developer),
sent as the ``api-key`` request header.

Hevy exposes **no webhooks**, so sync is pull-based.  The daily strength-ingest cron
(`core/strength_ingest.py`) calls :func:`fetch_workout_events` with a ``since`` cursor
for cheap incremental delta sync, falling back to :func:`fetch_workouts` pagination on
the very first run.

This module is **stateless** — it fetches and normalizes; persistence is the job of
``memory.firestore_db.StrengthSessionStore``.  :func:`normalize_workout` converts a raw
Hevy workout into the canonical store shape and pre-computes the derived strength
metrics Klaus reasons over (top set, estimated 1RM, per-exercise and session volume).
"""
from __future__ import annotations

import logging
import os
from datetime import datetime
from zoneinfo import ZoneInfo

import requests

logger = logging.getLogger(__name__)

HEVY_BASE_URL = "https://api.hevyapp.com/v1"
_TZ = ZoneInfo("Asia/Jerusalem")

# Hevy caps page size at 10 for both /workouts and /workouts/events.
_MAX_PAGE_SIZE = 10


class HevyAuthError(Exception):
    """Raised when HEVY_API_KEY is missing or rejected (401/403)."""


class HevyUnavailableError(Exception):
    """Raised on network error or unexpected (non-2xx, non-auth) API response."""


def _api_key() -> str:
    key = os.environ.get("HEVY_API_KEY")
    if not key:
        raise HevyAuthError("HEVY_API_KEY env var is not set (Hevy Pro required)")
    return key


_session: requests.Session | None = None


def _get_session() -> requests.Session:
    """Shared keep-alive session — reuses the TLS connection across API calls.

    The strength-ingest cron pages through /workouts back-to-back; a session
    avoids a fresh TCP + TLS handshake per page. No auth state lives on the
    session (the api-key header is passed per call), so sharing is safe.
    """
    global _session
    if _session is None:
        _session = requests.Session()
    return _session


def _request(path: str, params: dict) -> dict:
    """GET ``{HEVY_BASE_URL}{path}`` with the api-key header; return parsed JSON.

    Raises:
        HevyAuthError:        On missing key or HTTP 401/403.
        HevyUnavailableError: On network failure, non-JSON body, or other non-2xx.
    """
    try:
        resp = _get_session().get(
            f"{HEVY_BASE_URL}{path}",
            headers={"api-key": _api_key(), "Accept": "application/json"},
            params=params,
            timeout=20,
        )
    except requests.RequestException as exc:
        raise HevyUnavailableError(f"Hevy request failed: {exc}") from exc

    if resp.status_code in (401, 403):
        raise HevyAuthError("Hevy rejected the api-key — check HEVY_API_KEY / Pro status")
    if not resp.ok:
        raise HevyUnavailableError(
            f"Hevy returned HTTP {resp.status_code}: {resp.text[:200]}"
        )
    try:
        return resp.json()
    except ValueError as exc:
        raise HevyUnavailableError(f"Hevy returned non-JSON: {exc}") from exc


def fetch_workouts(page: int = 1, page_size: int = _MAX_PAGE_SIZE) -> dict:
    """Fetch a page of completed workouts (newest-first), for first-run backfill.

    Args:
        page:      1-based page number.
        page_size: Items per page (clamped to Hevy's max of 10).

    Returns:
        Raw Hevy envelope: ``{"page": int, "page_count": int, "workouts": [...]}``.
    """
    return _request(
        "/workouts",
        {"page": page, "pageSize": min(page_size, _MAX_PAGE_SIZE)},
    )


def fetch_workout_events(since: str, page: int = 1, page_size: int = _MAX_PAGE_SIZE) -> dict:
    """Fetch workout change-events (updates + deletes) since ``since``.

    The events endpoint lets the cron keep its local cache current without
    re-pulling the whole history — events are newest-first.

    Args:
        since:     ISO-8601 timestamp; only events after this are returned.
        page:      1-based page number.
        page_size: Items per page (clamped to Hevy's max of 10).

    Returns:
        Raw Hevy envelope: ``{"page": int, "page_count": int, "events": [...]}``.
        Each event is ``{"type": "updated", "workout": {...}}`` or
        ``{"type": "deleted", "id": str, "deleted_at": str}``.
    """
    return _request(
        "/workouts/events",
        {"since": since, "page": page, "pageSize": min(page_size, _MAX_PAGE_SIZE)},
    )


# ------------------------------------------------------------------ #
# Normalization + derived strength metrics                           #
# ------------------------------------------------------------------ #

def _local_date(iso_ts: str | None) -> str | None:
    """Convert an ISO-8601 timestamp to an Asia/Jerusalem ``YYYY-MM-DD`` date.

    Hevy timestamps are UTC (often with a trailing ``Z``). Returns None when the
    input is missing or unparseable so callers can fail-open.
    """
    if not iso_ts:
        return None
    try:
        dt = datetime.fromisoformat(iso_ts.replace("Z", "+00:00"))
        return dt.astimezone(_TZ).date().isoformat()
    except (ValueError, TypeError):
        return None


def _duration_min(start: str | None, end: str | None) -> float | None:
    try:
        s = datetime.fromisoformat((start or "").replace("Z", "+00:00"))
        e = datetime.fromisoformat((end or "").replace("Z", "+00:00"))
        return round((e - s).total_seconds() / 60.0, 1)
    except (ValueError, TypeError):
        return None


def _epley_1rm(weight_kg: float, reps: int) -> float:
    """Epley estimated one-rep max: ``w * (1 + reps/30)`` (standard form).

    Note the classic Epley formula slightly overestimates at 1 rep
    (``w * 31/30``); it is intended for multi-rep estimation. We keep the
    canonical form rather than special-casing reps==1 so trend comparisons stay
    consistent across rep ranges.
    """
    return weight_kg * (1.0 + reps / 30.0)


def _normalize_exercise(raw_ex: dict) -> dict:
    """Normalize one Hevy exercise + derive top_set / est_1rm / volume.

    Derived metrics use **working sets only** — warmup sets (``type == "warmup"``)
    are excluded, and sets without a numeric weight+reps pair (bodyweight or
    distance/duration cardio) are skipped for the weight-based metrics.

    - ``top_set``: the heaviest working set ``{weight_kg, reps}`` (ties → more reps).
    - ``est_1rm``: the best Epley estimate across working sets (a lighter, higher-rep
      set can imply a higher 1RM than the heaviest set, so we take the max).
    - ``volume_kg``: Σ ``weight_kg × reps`` over working sets.
    """
    sets_out: list[dict] = []
    top_set: dict | None = None
    est_1rm: float | None = None
    volume_kg = 0.0

    for raw_set in raw_ex.get("sets") or []:
        set_type = raw_set.get("type")
        clean = {
            "index": raw_set.get("index"),
            "type": set_type,
            "weight_kg": raw_set.get("weight_kg"),
            "reps": raw_set.get("reps"),
            "rpe": raw_set.get("rpe"),
            "distance_meters": raw_set.get("distance_meters"),
            "duration_seconds": raw_set.get("duration_seconds"),
        }
        sets_out.append(clean)

        weight = raw_set.get("weight_kg")
        reps = raw_set.get("reps")
        if set_type == "warmup" or weight is None or reps is None:
            continue
        try:
            weight = float(weight)
            reps = int(reps)
        except (TypeError, ValueError):
            continue
        volume_kg += weight * reps
        if top_set is None or (weight, reps) > (top_set["weight_kg"], top_set["reps"]):
            top_set = {"weight_kg": weight, "reps": reps}
        one_rm = _epley_1rm(weight, reps)
        if est_1rm is None or one_rm > est_1rm:
            est_1rm = one_rm

    return {
        "name": raw_ex.get("title"),
        "template_id": raw_ex.get("exercise_template_id"),
        "notes": raw_ex.get("notes") or "",
        "sets": sets_out,
        "set_count": sum(1 for s in sets_out if s.get("type") != "warmup"),
        "top_set": top_set,
        "est_1rm": round(est_1rm, 1) if est_1rm is not None else None,
        "volume_kg": round(volume_kg, 1),
    }


def normalize_workout(raw: dict) -> dict:
    """Convert a raw Hevy workout into the canonical StrengthSessionStore shape.

    Args:
        raw: A Hevy ``Workout`` object (from /v1/workouts or an "updated" event).

    Returns:
        ``{
            "workout_id", "title", "description",
            "start_time", "end_time", "date", "duration_min",
            "exercises": [ {name, template_id, notes, sets[],
                            set_count, top_set, est_1rm, volume_kg}, ... ],
            "total_volume_kg",
        }``
        ``date`` is the Asia/Jerusalem calendar date derived from ``start_time``.
    """
    start = raw.get("start_time")
    end = raw.get("end_time")
    exercises = [_normalize_exercise(ex) for ex in (raw.get("exercises") or [])]
    total_volume = round(sum(ex["volume_kg"] for ex in exercises), 1)
    return {
        "workout_id": raw.get("id"),
        "title": raw.get("title") or "",
        "description": raw.get("description") or "",
        "start_time": start,
        "end_time": end,
        "date": _local_date(start),
        "duration_min": _duration_min(start, end),
        "exercises": exercises,
        "total_volume_kg": total_volume,
    }
