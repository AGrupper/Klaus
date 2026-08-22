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
            "start_block needed): which week he is in, how far through the block, how "
            "many days until its goal, and what that goal's targets are. Call when Amit "
            "asks 'what's my plan?' or 'what week am I in?'."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    })
def _handle_get_plan() -> str:
    """The plan is the run-up to the next dated goal.

    This used to report the seeded blueprint block plus a week number computed
    against a hardcoded 2026-06-21 — "week 9 of 16, Deep Waters -> Peak Engine".
    Amit's verdict on that was "I don't really know what that means", but he
    explicitly asked to KEEP the week count, the sense of progress through the
    block, and how close its goal is. It was the phase name from an abandoned
    plan he was rejecting, not the counter.

    So the block is derived from his own dated goals now (see
    core/training/goal_blocks). Same arithmetic he was already seeing — 16 weeks
    from 2026-06-21 lands two days past the 5K — pointed at a race he is actually
    running. When every goal is behind him, `block` is None rather than a
    position in a plan that has ended.
    """
    from datetime import date as _date

    from core.training.goal_blocks import current_block
    from memory.firestore_db import _jsonsafe_doc

    _blocks, _benchmarks, profiles = _block_stores()
    profile = _jsonsafe_doc(profiles.load())
    goals = profile.get("dated_goals") or []
    today = _date.today().isoformat()

    from core.training.goal_blocks import DEFAULT_ANCHOR

    anchor = profile.get("plan_start_date") or DEFAULT_ANCHOR
    block = current_block(goals, today, anchor_iso=anchor)
    return json.dumps({
        "profile": profile,
        "dated_goals": goals,
        "block": block,
        "upcoming_goals": [
            g for g in goals
            if isinstance(g, dict) and str(g.get("target_date") or "") > today
        ],
    })


@tool({
        "name": "get_block_status",
        "description": (
            "Read the current block — the run-up to Amit's next race — with any "
            "benchmarks recorded inside it and the raw per-facet delta versus the "
            "previous block. Call when Amit asks how the current block is going or "
            "how his numbers compare to last block. He rarely logs benchmarks, so "
            "empty lists here mean 'nothing recorded', not 'no progress'."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    })
def _handle_get_block_status() -> str:
    """The current block + its benchmarks + raw cross-block deltas.

    The block comes from Amit's dated goals (core/training/goal_blocks), the same
    source get_plan uses. It used to come from BlockStore's seeded documents,
    which still describe the retired 16-week half-marathon blueprint — so this
    tool answered "Deep Waters -> Peak Engine, focus facets bench_press_1rm and
    squat_1rm" while get_plan answered with the 5K. Two block tools disagreeing
    is worse than either being wrong alone.

    facet_deltas is raw (current_value - prior_block_value) per facet — NO trend
    projection (Phase 25 scope). The prior value is the most recent benchmark for
    that facet belonging to a DIFFERENT block than the current one.
    """
    from datetime import date as _date

    from core.training.goal_blocks import DEFAULT_ANCHOR, current_block

    _blocks, benchmarks, profiles = _block_stores()
    profile = profiles.load()
    anchor = profile.get("plan_start_date") if isinstance(profile, dict) else None
    block = current_block(
        (profile.get("dated_goals") if isinstance(profile, dict) else None) or [],
        _date.today().isoformat(),
        anchor_iso=anchor if isinstance(anchor, str) and anchor else DEFAULT_ANCHOR,
    )
    if not block:
        return json.dumps({"current_block": None, "benchmarks": [], "facet_deltas": {}})
    block_id = block["block_id"]
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
