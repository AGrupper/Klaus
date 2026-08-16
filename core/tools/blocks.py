"""Mesocycle blocks, benchmark results and goal projection.

Split out of core/tools.py; registered automatically on import.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime

from core.tools.registry import tool

logger = logging.getLogger(__name__)


# Default cycle start used for week-number framing when the profile has no
# plan_start_date set yet (anchor: first mesocycle block, 2026-06-21).
_PLAN_START_DEFAULT = "2026-06-21"


def _block_stores():
    """Construct (BlockStore, BenchmarkStore, UserProfileStore) from env."""
    from memory.firestore_db import BlockStore, BenchmarkStore, UserProfileStore
    project_id = os.environ["GCP_PROJECT_ID"]
    database = os.environ.get("FIRESTORE_DATABASE", "(default)")
    return (
        BlockStore(project_id=project_id, database=database),
        BenchmarkStore(project_id=project_id, database=database),
        UserProfileStore(project_id=project_id, database=database),
    )


@tool({
        "name": "get_plan",
        "description": (
            "Read Amit's living training plan merged with the currently-active "
            "mesocycle block. Returns the stored profile/plan fields "
            "plus the active block (resolved automatically by today's date — no "
            "start_block needed) and the current 1-based week number. Call when Amit "
            "asks 'what's my plan?' or 'what block/week am I in?'."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    })
def _handle_get_plan() -> str:
    """BLOCK-01 profile/plan merged with the date-resolved active block.

    The block is resolved by date range (get_current) — never depends on a manual
    start_block call (D-01). week_num is computed against the profile plan_start_date
    (default 2026-06-21).
    """
    from memory.firestore_db import get_week_num, _jsonsafe_doc
    from datetime import date as _date
    blocks, _benchmarks, profiles = _block_stores()
    profile = _jsonsafe_doc(profiles.load())
    block = blocks.get_current()
    today = _date.today().isoformat()
    plan_start = profile.get("plan_start_date") or _PLAN_START_DEFAULT
    week_num = get_week_num(plan_start, today)
    return json.dumps({
        "profile": profile,
        "current_block": block,
        "week_num": week_num,
        "plan_start_date": plan_start,
    })


@tool({
        "name": "get_block_status",
        "description": (
            "Read the currently-active mesocycle block (resolved by today's date), "
            "its recorded benchmarks, and the raw per-facet delta versus the prior "
            "block. Call when Amit asks how the current block is going "
            "or how his benchmarks compare to last block."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    })
def _handle_get_block_status() -> str:
    """BLOCK-01/BLOCK-03 active block + its benchmarks + raw cross-block deltas.

    facet_deltas is raw (current_value - prior_block_value) per facet — NO trend
    projection (Phase 25 scope). The prior value is the most recent benchmark for
    that facet belonging to a DIFFERENT block than the current one.
    """
    blocks, benchmarks, _profiles = _block_stores()
    block = blocks.get_current()
    if not block:
        return json.dumps({"current_block": None, "benchmarks": [], "facet_deltas": {}})
    block_id = block.get("doc_id") or block.get("block_id")
    current = benchmarks.get_block_benchmarks(block_id)
    facet_deltas: dict[str, float] = {}
    for entry in current:
        facet = entry.get("facet")
        if not facet or facet in facet_deltas:
            continue
        history = benchmarks.get_facet_history(facet, n=20)
        prior = next((h for h in history if h.get("block_id") != block_id), None)
        if (
            prior is not None
            and isinstance(entry.get("value"), (int, float))
            and isinstance(prior.get("value"), (int, float))
        ):
            facet_deltas[facet] = round(entry["value"] - prior["value"], 2)
    return json.dumps({
        "current_block": block,
        "benchmarks": current,
        "facet_deltas": facet_deltas,
    })


@tool({
        "name": "log_benchmark",
        "description": (
            "Record one benchmark result for the current block. "
            "Record it and tell him; only confirm first if the value is genuinely ambiguous. Valid facets "
            "(closed set): bench_press_1rm, squat_1rm, push_ups, pull_ups, "
            "threshold_pace. For a bench/squat top-set (weight x reps), compute the "
            "1RM estimate first (Epley: weight x (1 + reps/30)) and pass it as value."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "date": {"type": "string", "description": "YYYY-MM-DD date of the benchmark."},
                "facet": {
                    "type": "string",
                    "description": (
                        "One of: bench_press_1rm, squat_1rm, push_ups, pull_ups, "
                        "threshold_pace."
                    ),
                },
                "value": {"type": "number", "description": "Numeric result."},
                "unit": {"type": "string", "description": "'kg' | 'reps' | 'sec_per_km'."},
                "block_id": {
                    "type": "string",
                    "description": "FK to the training_blocks doc id (use get_block_status).",
                },
                "notes": {
                    "type": "string",
                    "description": "Optional context (e.g. 'Epley estimate from 85kg x 5').",
                },
            },
            "required": ["date", "facet", "value", "unit", "block_id"],
        },
    })
def _handle_log_benchmark(
    date: str, facet: str, value: float, unit: str, block_id: str, notes: str = ""
) -> str:
    """BLOCK-03 record a benchmark. Store raises ValueError on bad facet."""
    _blocks, benchmarks, _profiles = _block_stores()
    try:
        benchmarks.log_benchmark(
            date=date, facet=facet, value=value, unit=unit, block_id=block_id, notes=notes
        )
        return json.dumps({"ok": True})
    except Exception as exc:
        return json.dumps({"error": str(exc)})


@tool({
        "name": "get_benchmark_history",
        "description": (
            "Read the cross-block history for one benchmark facet, newest first. "
            "Call when Amit asks how a lift/run has trended over time."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "facet": {
                    "type": "string",
                    "description": (
                        "One of: bench_press_1rm, squat_1rm, push_ups, pull_ups, "
                        "threshold_pace."
                    ),
                },
                "n": {
                    "type": "integer",
                    "description": "Max number of entries to return (default 10).",
                },
            },
            "required": ["facet"],
        },
    })
def _handle_get_benchmark_history(facet: str, n: int = 10) -> str:
    """BLOCK-03 cross-block history for one facet, newest first."""
    _blocks, benchmarks, _profiles = _block_stores()
    return json.dumps({"facet": facet, "history": benchmarks.get_facet_history(facet, n=n)})


@tool({
        "name": "get_goal_projection",
        "description": (
            "Compute a deterministic linear-trend projection for one benchmark facet "
            "toward its dated goal. Call when Amit asks 'am I on track "
            "for my October bench target?' or similar. Returns a ProjectionResult dict "
            "with projected_value, behind_by (positive = behind target for EVERY facet, "
            "including pace), on_track, confidence, and confidence_label computed "
            "server-side — numbers are never LLM-invented. Prefer behind_by over the raw "
            "gap, whose sign flips between higher-is-better and lower-is-better facets."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "facet": {
                    "type": "string",
                    "description": (
                        "One of: bench_press_1rm, squat_1rm, push_ups, pull_ups, "
                        "threshold_pace."
                    ),
                },
            },
            "required": ["facet"],
        },
    })
def _handle_get_goal_projection(facet: str) -> str:
    """PROG-02 project one facet toward its dated goal.

    Validates facet against _BENCHMARK_FACETS (V5 / T-25-05 pattern, mirrors
    _handle_log_benchmark). Returns a JSON ProjectionResult dict. Never raises —
    errors surface as a no_data confidence result (T-25-07).

    Source selection per D-04:
      - threshold_pace: prefers dense Garmin Postgres history (fetch_dense_pace_history),
        falls back to sparse BenchmarkStore only when the Postgres list is empty.
      - strength facets (bench_press_1rm, squat_1rm, push_ups, pull_ups): BenchmarkStore.

    today_iso computed via ZoneInfo("Asia/Jerusalem") — never date.today() (CR-01, T-25-14).
    """
    from memory.firestore_db import _BENCHMARK_FACETS, _jsonsafe_doc
    if facet not in _BENCHMARK_FACETS:
        return json.dumps(
            {"error": f"Unknown facet: {facet!r}. Valid: {sorted(_BENCHMARK_FACETS)}"}
        )

    from zoneinfo import ZoneInfo
    from core.training.projection import project_goal_progress

    today_iso = datetime.now(ZoneInfo("Asia/Jerusalem")).date().isoformat()

    _blocks, benchmarks, profiles = _block_stores()
    profile = _jsonsafe_doc(profiles.load())
    dated_goals = profile.get("dated_goals") or []

    # D-04: threshold_pace uses dense Garmin Postgres points; strength facets use BenchmarkStore.
    if facet == "threshold_pace":
        from core.training.pace_history import fetch_dense_pace_history
        history = fetch_dense_pace_history(today_iso)
        if not history:
            # Fallback to sparse BenchmarkStore when no Garmin running data exists
            history = benchmarks.get_facet_history(facet, n=10)
    else:
        history = benchmarks.get_facet_history(facet, n=10)

    result = project_goal_progress(facet, history, dated_goals, today_iso)
    return json.dumps(result)


@tool({
        "name": "start_block",
        "description": (
            "Bookkeeping: mark a block active and set the current_block_id FK. "
            "NOTE: get_plan/get_block_status already resolve the active "
            "block by date automatically — only call this for explicit bookkeeping."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "block_id": {"type": "string", "description": "training_blocks doc id."},
            },
            "required": ["block_id"],
        },
    })
def _handle_start_block(block_id: str) -> str:
    """BLOCK-01 available through Claude MCP bookkeeping: mark block active + set current_block_id FK."""
    blocks, _benchmarks, profiles = _block_stores()
    try:
        blocks.start_block(block_id)
        profiles.update({"current_block_id": block_id})
        return json.dumps({"ok": True})
    except Exception as exc:
        return json.dumps({"error": str(exc)})


@tool({
        "name": "end_block",
        "description": (
            "Bookkeeping: mark a block complete and clear the current_block_id FK. "
            "The next block is surfaced automatically by date."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "block_id": {"type": "string", "description": "training_blocks doc id."},
            },
            "required": ["block_id"],
        },
    })
def _handle_end_block(block_id: str) -> str:
    """BLOCK-01 available through Claude MCP bookkeeping: mark block complete + clear current_block_id FK."""
    blocks, _benchmarks, profiles = _block_stores()
    try:
        blocks.end_block(block_id)
        profiles.update({"current_block_id": None})
        return json.dumps({"ok": True})
    except Exception as exc:
        return json.dumps({"error": str(exc)})
