"""GET /api/health/{training,nutrition,sleep} — the Hub's chart data.

The `range` parameter is an allowlist, never int()-parsed from client input.
All bucketing and series alignment lives in core.hub.health_series.
"""
from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from core.hub.health_series import (
    _health_nutrition_daily,
    _health_nutrition_profile,
    _health_nutrition_slots,
    _health_sleep_data,
    _health_sleep_pipeline_active,
    _health_training_benchmarks,
    _health_training_blocks,
    _health_training_runs,
    _health_training_strength,
    _hrv_baseline_with_fallback,
    _MILEAGE_WEEKLY_THRESHOLD_DAYS,
    _NUTRITION_MACRO_KEYS,
    _range_bounds,
    _resolve_calories_target,
    _resolve_range,
    _week_axis_for_dates,
    _WEEKLY_BUCKET_THRESHOLD_DAYS,
    _weekly_bucket_points,
)
from interfaces.hub_auth import require_hub_session

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/api/health/training")
async def api_health_training(
    range: str = "30d",
    _email: str = Depends(require_hub_session),
) -> JSONResponse:
    """Mixed strength+run+benchmark training log + block dividers + trends.

    HLTH-01: one endpoint composing StrengthSessionStore/RunDetailStore/
    BenchmarkStore/BlockStore into a reverse-chronological interleaved log
    tagged by `modality`, plus two {x,y} trend series (run_mileage,
    run_trend) — daily for range<=90d, weekly-bucketed for >90d (D-07).

    Returns:
        JSONResponse: {"range", "entries", "blocks", "run_mileage", "run_trend"}
    Raises:
        HTTPException 401: No valid session cookie (via require_hub_session).
    """
    from memory.firestore_db import _jsonsafe_doc  # lazy import — Shared Pattern 5

    loop = asyncio.get_running_loop()
    start_iso, end_iso = _range_bounds(range)
    days = _resolve_range(range)

    strength, runs, benchmarks, blocks = await asyncio.gather(
        loop.run_in_executor(None, _health_training_strength, start_iso, end_iso),
        loop.run_in_executor(None, _health_training_runs, start_iso, end_iso),
        loop.run_in_executor(None, _health_training_benchmarks, start_iso, end_iso),
        loop.run_in_executor(None, _health_training_blocks),
    )

    entries = (
        [{**s, "modality": "strength"} for s in strength]
        + [{**r, "modality": "run"} for r in runs]
        + [{**b, "modality": "benchmark"} for b in benchmarks]
    )
    entries.sort(key=lambda e: e.get("date", ""), reverse=True)

    # Trend 1: run mileage — distance_m summed per date, surfaced in km. Running
    # mileage progression is the volume signal that matters here (strength
    # tonnage was dropped as low-signal per UAT); strength sessions still appear
    # in the interleaved log below.
    mileage_daily: dict[str, float] = {}
    for r in runs:
        d = r.get("date")
        dist_m = r.get("distance_m")
        if not d or dist_m is None:
            continue
        mileage_daily[d] = mileage_daily.get(d, 0.0) + dist_m
    mileage_points = [
        {"x": d, "y": round(m / 1000.0, 2)} for d, m in sorted(mileage_daily.items())
    ]

    # Trend 2: run pace — avg_pace_sec_per_km averaged per date (lower = faster).
    run_daily: dict[str, list[float]] = {}
    for r in runs:
        d = r.get("date")
        pace = r.get("avg_pace_sec_per_km")
        if not d or pace is None:
            continue
        run_daily.setdefault(d, []).append(pace)
    run_points = [
        {"x": d, "y": round(sum(vals) / len(vals), 1)}
        for d, vals in sorted(run_daily.items())
    ]

    # Mileage buckets to weekly beyond the 7-day view — a weekly progression is
    # the useful read at 30d/90d/1y, while 7d stays daily. Pace keeps the
    # standard >90d weekly threshold (D-07).
    run_mileage = (
        _weekly_bucket_points(mileage_points, agg="sum")
        if days > _MILEAGE_WEEKLY_THRESHOLD_DAYS
        else mileage_points
    )
    run_trend = (
        _weekly_bucket_points(run_points, agg="avg")
        if days > _WEEKLY_BUCKET_THRESHOLD_DAYS
        else run_points
    )

    payload = _jsonsafe_doc({
        "range": range,
        "entries": entries,
        "blocks": blocks,
        "run_mileage": run_mileage,
        "run_trend": run_trend,
    })
    return JSONResponse(content=payload)


@router.get("/api/health/nutrition")
async def api_health_nutrition(
    range: str = "30d",
    _email: str = Depends(require_hub_session),
) -> JSONResponse:
    """Per-day (or weekly >90d) macro series + slot-adherence grid + targets.

    HLTH-02: macro series/averages/targets/protein-g-per-kg math is shared with
    core.tools._handle_fetch_nutrition_trend (never reimplemented — RESEARCH.md
    Anti-Patterns). Unlogged days are gaps in `missing_dates`, never zero-filled
    (D-08). Slot adherence is keyed on slot LABEL only — no clock time on the
    wire (CLAUDE.md §6). The per-day Firestore pass is shared between the macro
    series and the slot grid and TTL-cached for >90d ranges (Pitfall 1).

    Returns:
        JSONResponse: {"range", "series", "missing_dates", "averages", "targets",
                       "avg_protein_g_per_kg", "slot_adherence"}
    Raises:
        HTTPException 401: No valid session cookie (via require_hub_session).
    """
    from memory.firestore_db import _jsonsafe_doc  # lazy import — Shared Pattern 5
    from core.tools import (  # lazy import — Shared Pattern 5
        _compute_nutrition_averages,
        _nutrition_targets_and_protein_ratio,
    )

    loop = asyncio.get_running_loop()
    start_iso, end_iso = _range_bounds(range)
    days = _resolve_range(range)

    daily, profile = await asyncio.gather(
        loop.run_in_executor(None, _health_nutrition_daily, start_iso, end_iso),
        loop.run_in_executor(None, _health_nutrition_profile),
    )

    day_records = daily["day_records"]
    missing_dates = daily.get("missing_dates", [])
    # Build each series over the FULL date range so an unlogged day is an
    # explicit {y: null} gap the LineChart splits on (D-08) — NOT an absent
    # point the line would bridge across. `missing_dates` alone is insufficient:
    # nothing on the client reconstructs the gaps from it (CR-01).
    record_by_date = {r["date"]: r for r in day_records}
    all_dates = sorted(record_by_date.keys() | set(missing_dates))
    points_by_key: dict[str, list[dict]] = {}
    for key in _NUTRITION_MACRO_KEYS:
        pts = [
            {"x": d, "y": record_by_date[d].get(key) if d in record_by_date else None}
            for d in all_dates
        ]
        if days > _WEEKLY_BUCKET_THRESHOLD_DAYS:
            pts = _weekly_bucket_points(pts, agg="avg")
        points_by_key[key] = pts

    averages = _compute_nutrition_averages(day_records, _NUTRITION_MACRO_KEYS)
    extra = _nutrition_targets_and_protein_ratio(profile, averages)
    targets = dict(extra.get("targets") or {})

    calories_target, derived = _resolve_calories_target(targets)
    if calories_target is not None:
        targets["calories"] = calories_target
        if derived:
            targets["calories_target_derived"] = True

    slot_adherence = _health_nutrition_slots(daily)

    payload = _jsonsafe_doc({
        "range": range,
        "series": points_by_key,
        "missing_dates": daily["missing_dates"],
        "averages": averages,
        "targets": targets,
        "avg_protein_g_per_kg": extra.get("avg_protein_g_per_kg"),
        "slot_adherence": slot_adherence,
    })
    return JSONResponse(content=payload)


@router.get("/api/health/sleep")
async def api_health_sleep(
    range: str = "30d",
    _email: str = Depends(require_hub_session),
) -> JSONResponse:
    """HRV/sleep/body-battery trend series + header stat row + pipeline_active.

    HLTH-03: reads Postgres daily_biometrics via run_in_executor (Pitfall 3 —
    never call psycopg2 synchronously inside async def). Missing days are
    gaps (null), never zero (D-08 — watch-not-worn != HRV of 0). `pipeline_active`
    is true iff the table has EVER had a row, distinct from "no rows in this
    specific range" (D-19 pipeline-not-live guard). range=1y (>90d) returns
    weekly-bucketed series (D-07). hrv_baseline falls back to a rolling median
    of hrv_overnight when the stored column is sparse (Pitfall 5).

    Returns:
        JSONResponse: {"range", "series", "header_stats", "pipeline_active"}
    Raises:
        HTTPException 401: No valid session cookie (via require_hub_session).
    """
    from memory.firestore_db import _jsonsafe_doc  # lazy import — Shared Pattern 5

    loop = asyncio.get_running_loop()
    start_iso, end_iso = _range_bounds(range)
    days = _resolve_range(range)

    rows, pipeline_active = await asyncio.gather(
        loop.run_in_executor(None, _health_sleep_data, start_iso, end_iso),
        loop.run_in_executor(None, _health_sleep_pipeline_active),
    )

    rows_sorted = sorted(rows, key=lambda r: r.get("date", ""))
    baseline_by_date = _hrv_baseline_with_fallback(rows_sorted)

    # WR-04: bucket every sleep series onto ONE shared week axis so the overlaid
    # pairs (HRV overnight+baseline, sleep score+duration) stay index-aligned —
    # an empty week in one series becomes a null point, never a dropped index
    # that would slide the dashed baseline off the overnight line.
    week_axis = (
        _week_axis_for_dates([r["date"] for r in rows_sorted])
        if days > _WEEKLY_BUCKET_THRESHOLD_DAYS
        else None
    )

    metric_keys = ["hrv_overnight", "sleep_score", "sleep_duration", "body_battery_max"]
    series: dict[str, list[dict]] = {}
    for key in metric_keys:
        pts = [{"x": r["date"], "y": r.get(key)} for r in rows_sorted]
        if week_axis is not None:
            pts = _weekly_bucket_points(pts, agg="avg", week_axis=week_axis)
        series[key] = pts

    baseline_points = [
        {"x": r["date"], "y": baseline_by_date.get(r["date"])} for r in rows_sorted
    ]
    if week_axis is not None:
        baseline_points = _weekly_bucket_points(baseline_points, agg="avg", week_axis=week_axis)
    series["hrv_baseline"] = baseline_points

    header_stats = None
    if rows_sorted:
        latest = rows_sorted[-1]
        header_stats = {
            "date": latest.get("date"),
            "hrv_overnight": latest.get("hrv_overnight"),
            "sleep_score": latest.get("sleep_score"),
            "body_battery_max": latest.get("body_battery_max"),
            "resting_hr": latest.get("resting_hr"),
            "training_readiness": latest.get("training_readiness"),
        }

    payload = _jsonsafe_doc({
        "range": range,
        "series": series,
        "header_stats": header_stats,
        "pipeline_active": pipeline_active,
    })
    return JSONResponse(content=payload)
