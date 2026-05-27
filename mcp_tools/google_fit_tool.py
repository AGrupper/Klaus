"""Google Fit Nutrition tool — Lifesum-sourced meal sync.

Fetches nutrition data points (calories, macros, meal_type, optional food_item)
via the Google Fit REST API (com.google.nutrition data type). Reuses the
shared GoogleAuthManager (Gmail + Calendar + Fitness) after operator re-consent
for the fitness.nutrition.read scope (Pitfall 1).

Pipeline:
    Lifesum (Android) → Health Connect → Google Fit → fetch_recent_meals() →
    _normalize_point() → MealStore.upsert() (idempotent on source_id).

The source_id `{dataStreamId}:{startTimeNanos}` is the integrity anchor.
Re-syncs from Lifesum land on the same Firestore doc, so duplicate writes
collapse to a single document (Pitfall 2 mitigation).

PHASE 19 Plan 03 — NUTR-01.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from googleapiclient.discovery import build

logger = logging.getLogger(__name__)

_TZ = ZoneInfo("Asia/Jerusalem")

# Google Fit nutrition data type — used to filter dataSources.list().
_NUTRITION_DATA_TYPE = "com.google.nutrition"


class GoogleFitUnavailableError(Exception):
    """Raised when Fit data cannot be fetched at all (API down, scope missing).

    Per-dataset errors are logged + skipped (so a partial outage on one
    source doesn't blank the entire result). This exception only fires when
    the *initial* dataSources.list() call fails, i.e. there's nothing we can
    do other than surface the error to the caller.
    """


def _fit_service():
    """Build a Fitness v1 service via the shared GoogleAuthManager.

    Lazy-imports `core.auth_google` so tests can monkey-patch this function
    without dragging the real auth manager into the import graph.
    """
    from core.auth_google import build_auth_manager_from_env  # lazy import
    manager = build_auth_manager_from_env()
    return build(
        "fitness", "v1",
        credentials=manager.get_credentials(),
        cache_discovery=False,
    )


def fetch_recent_meals(hours: int = 24) -> list[dict]:
    """Return Fit nutrition entries from the last ``hours`` hours.

    Args:
        hours: Hours back from "now" (Asia/Jerusalem) to fetch. Default 24.

    Returns:
        Flat list of normalized meal dicts (see ``_normalize_point`` for
        shape). Empty list when Fit has no entries in the window OR every
        individual data-source query errored (each error is logged at WARNING).

    Raises:
        GoogleFitUnavailableError: ``dataSources.list`` failed — the outer
            API call is unrecoverable (token-revoked, scope-missing, API down).
    """
    svc = _fit_service()
    end = datetime.now(_TZ)
    start = end - timedelta(hours=hours)
    start_nanos = int(start.timestamp() * 1e9)
    end_nanos = int(end.timestamp() * 1e9)

    try:
        sources = (
            svc.users().dataSources()
            .list(userId="me", dataTypeName=_NUTRITION_DATA_TYPE)
            .execute()
        ).get("dataSource", [])
    except Exception as exc:
        # Outer call failed — nothing to fall back to. Tell the caller.
        raise GoogleFitUnavailableError(
            f"dataSources.list failed: {exc}"
        ) from exc

    out: list[dict] = []
    for src in sources:
        ds_id = src.get("dataStreamId")
        if not ds_id:
            continue
        try:
            ds = (
                svc.users().dataSources().datasets()
                .get(
                    userId="me",
                    dataSourceId=ds_id,
                    datasetId=f"{start_nanos}-{end_nanos}",
                )
                .execute()
            )
        except Exception:
            # Per-source outage — log + continue with other sources.
            # (Common in practice: a stale dataStreamId for a deleted app.)
            logger.warning(
                "google_fit: dataset.get failed for %s", ds_id, exc_info=True
            )
            continue
        for point in ds.get("point", []):
            try:
                out.append(_normalize_point(point, ds_id))
            except Exception:
                logger.warning(
                    "google_fit: normalize_point failed", exc_info=True
                )
                continue
    return out


def _normalize_point(point: dict, ds_id: str) -> dict:
    """Convert a Fit dataPoint dict into Klaus's meal shape.

    Args:
        point: Raw dataPoint dict from Fit (startTimeNanos + value list).
        ds_id: dataStreamId of the source — feeds the idempotency key.

    Returns:
        Dict with keys ``source_id, timestamp, meal_type, calories,
        protein_g, carbs_g, fat_g, food_item, source``.

        source_id is ``{ds_id}:{startTimeNanos}`` so re-syncs from Lifesum
        produce ONE Firestore doc per (source, time) regardless of arrival
        order or count (Pitfall 2 mitigation).

        timestamp is ISO-8601 with Asia/Jerusalem offset for human-readability
        in the morning briefing prompt.

        source is always ``"google_fit"`` (caller may attribute multi-source
        meals in a later phase by extending this field).
    """
    nanos = int(point.get("startTimeNanos", 0))
    ts = (
        datetime.fromtimestamp(nanos / 1e9, _TZ).isoformat()
        if nanos
        else ""
    )
    source_id = f"{ds_id}:{nanos}"

    # Fit's value list mixes typed entries:
    #   {"mapVal": [...]} → macro dict
    #   {"intVal": N}     → meal_type (1=breakfast, 2=lunch, 3=dinner, 4=snack, 5=unknown)
    #   {"stringVal": s}  → food_item (Lifesum populates this with the dish name)
    macros: dict[str, float] = {}
    meal_type = 1
    food_item: str | None = None
    for v in point.get("value", []):
        if "mapVal" in v:
            for kv in v["mapVal"]:
                key = kv.get("key")
                value = kv.get("value", {})
                if key and "fpVal" in value:
                    macros[key] = value["fpVal"]
        elif "intVal" in v:
            meal_type = v["intVal"]
        elif "stringVal" in v:
            food_item = v["stringVal"]

    return {
        "source_id": source_id,
        "timestamp": ts,
        "meal_type": meal_type,
        "calories": macros.get("calories"),
        "protein_g": macros.get("protein"),
        "carbs_g": macros.get("carbs.total"),
        "fat_g": macros.get("fat.total"),
        "food_item": food_item,
        "source": "google_fit",
    }


def sync_recent_meals(since_hours: int, store) -> list[dict]:
    """Fetch + upsert into MealStore. Returns the meals that were synced.

    NUTR-04 helper: called by ``core/autonomous.py``'s ``gather_situation()``
    layer 0 (free data layer). Idempotent on source_id so re-syncs from the
    same window are safe (Pitfall 2 mitigation).

    Args:
        since_hours: Hours back to fetch.
        store:       A MealStore instance — anything with an
                     ``upsert(source_id, meal)`` method. Failures on a
                     single upsert are logged + skipped so the loop never
                     aborts mid-batch.

    Returns:
        The full list of meals returned by ``fetch_recent_meals`` (whether
        or not each individual upsert succeeded). Callers may use this to
        render a "just-synced" view to the user.
    """
    meals = fetch_recent_meals(hours=since_hours)
    for m in meals:
        try:
            store.upsert(source_id=m["source_id"], meal=m)
        except Exception:
            logger.warning(
                "sync_recent_meals: upsert failed for %s",
                m.get("source_id"), exc_info=True,
            )
    return meals
